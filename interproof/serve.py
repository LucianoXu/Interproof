"""The same reader, live: the page stays open while the sources change.

Static artifacts are for sending; this is for working.  The viewer is rendered
once and never again — it is the same page `site.build_site` writes, and the
only difference is the boot payload, which tells it to fetch the manifest, the
documents and a stream of events instead of carrying them.  What moves is
underneath: a thread watches the sources, rebuilds only what the edit reached,
and nudges the page.

Two properties are worth more than everything else here:

  * **A failed build must not take the reader down.**  A LaTeX error, a broken
    `interproof.toml`, a half-saved Lean file — all of these are the normal
    condition of a working session, and in every one of them the last good
    manifest keeps being served and the error is put where it can be read.
  * **A `.lean` edit must not invoke latexmk.**  The whole reason to watch is
    that the loop is short; a formalization edit that waits on a document
    rebuild is a loop nobody stays inside.

Everything is standard library, watching included.  See `_scan` for why
polling is the right answer at this size.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import __version__
from .config import Config, ConfigError, Document
from .config import load as load_config
from .site import boot_literal, render_html

POLL = 0.5          # seconds between scans
DEBOUNCE = 0.25     # an editor's save is several events; wait for the last one
PING = 15.0         # seconds between keep-alive comments on the event stream

# What a change to a document means a rebuild of the document.  `.sty` and
# `.cls` are in here because a class file is edited exactly as often as the
# prose in the kind of project this tool is for.
TEX_SUFFIXES = {".tex", ".bib", ".cls", ".sty"}

# Exception names that mean "the build failed for a reason the user can read".
# Names rather than classes: importing the peer modules' exceptions here would
# make this module unimportable whenever one of them is mid-edit, which is
# precisely the situation the server exists to survive.
_EXPECTED = {"ConfigError", "PdfBuildError", "ManifestError", "SiteError",
             "SyncTexError", "CalledProcessError", "FileNotFoundError"}


# --------------------------------------------------------------------------
# the pipeline, held at arm's length
# --------------------------------------------------------------------------

def _build_manifest(cfg: Config, elaborate: bool | None = None) -> dict:
    """The manifest, imported at call time rather than at import time.

    Late binding buys two things: the server can be imported and its routing
    and watching exercised without the parsers being loaded, and a peer module
    that fails to import shows up as a failed rebuild — visible in the page,
    recoverable by fixing the file — instead of a server that will not start.
    """
    from . import manifest as manifest_module
    return manifest_module.build(cfg, elaborate=elaborate)


def _compile_docs(cfg: Config, doc_ids: set[str] | None = None) -> None:
    from . import pdf as pdf_module
    docs = None if doc_ids is None else [d for d in cfg.documents
                                         if d.id in doc_ids]
    pdf_module.compile_docs(cfg, docs=docs)


# --------------------------------------------------------------------------
# shared state
# --------------------------------------------------------------------------

class _Live:
    """What the request threads read and the watcher thread writes.

    The lock is around the whole quartet — configuration, manifest, generation
    and error — because they are one answer: serving a manifest built from a
    configuration that has since been replaced is worse than serving a stale
    one, since nothing tells the reader it happened.
    """

    def __init__(self, cfg: Config, *, skip_pdf: bool = False,
                 elaborate: bool | None = None) -> None:
        self._lock = threading.Lock()
        self._cfg = cfg
        # `--skip-pdf` is for the session where the document is already being
        # compiled by an editor or a `latexmk -pvc`: the PDFs on disk are
        # someone else's business, and running latexmk over them from here
        # would fight that process for the same `.fdb_latexmk`.
        self._skip_pdf = skip_pdf
        # A live session is the one place elaboration is paid for repeatedly,
        # so it leans on the extraction cache: only the modules whose text — or
        # whose imports' text — moved are handed to Lean again.
        self._elaborate = elaborate
        # the elaborated pass runs behind the rebuild, one at a time, and the
        # newest request wins — see `_want_enrich`
        self._enrich_lock = threading.Lock()
        self._enrich_busy = False
        self._enrich_next: tuple[Config, list[str]] | None = None
        self._manifest: dict | None = None
        self._gen = 0
        self._error: str | None = None
        self._subs: list[queue.Queue] = []
        self._subs_lock = threading.Lock()

    # -- reading ----------------------------------------------------------

    @property
    def cfg(self) -> Config:
        with self._lock:
            return self._cfg

    @property
    def manifest(self) -> dict | None:
        with self._lock:
            return self._manifest

    def status(self) -> dict:
        with self._lock:
            return {"ok": self._error is None, "error": self._error,
                    "gen": self._gen}

    # -- the event stream -------------------------------------------------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._subs_lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        # Under `_subs_lock` and tolerant of a double removal: a client that
        # closes during shutdown is unsubscribed by its own handler and woken
        # by `close`, and neither may leave a queue behind for the other.
        with self._subs_lock:
            if q in self._subs:
                self._subs.remove(q)

    def _publish(self, msg: dict | None) -> None:
        with self._subs_lock:
            subs = list(self._subs)
        for q in subs:
            q.put(msg)

    def close(self) -> None:
        """Wake every event stream so its thread can end."""
        self._publish(None)

    # -- rebuilding -------------------------------------------------------

    def rebuild(self, *, doc_ids: set[str] | None = None,
                compile_tex: bool = True, reload_config: bool = False) -> None:
        """One pass of the pipeline; never raises.

        `doc_ids is None` means every document.  A `.lean` edit arrives with
        `compile_tex=False`, which is the whole point of the grading: latexmk
        is incremental and fast, but it is not free, and it has nothing to say
        about a Lean file.
        """
        t0 = time.monotonic()
        cfg = self.cfg
        errors: list[str] = []

        if reload_config:
            try:
                cfg = load_config(cfg.path)
            except ConfigError as e:
                # The configuration is the only input whose failure invalidates
                # everything downstream, so on a bad one nothing else is
                # attempted and the previous configuration stays in force.
                self._settle(None, None, [str(e)], t0, "config")
                return

        if compile_tex and not self._skip_pdf:
            try:
                _compile_docs(cfg, doc_ids)
            except Exception as e:                    # noqa: BLE001
                # Deliberately broad, and deliberately not fatal: the documents
                # on disk are still the last ones that compiled, so the reader
                # keeps working against them while the error is on screen.
                errors.append(_describe(e))

        manifest: dict | None = None
        try:
            # Always the text-only pass first, whatever this session was asked
            # for.  Reading the sources is a fraction of a second and handing
            # each module to Lean is not — see `_enrich` — and a reader whose
            # page stops following their edits for a minute has lost the thing
            # `serve` exists to give them.
            manifest = _build_manifest(cfg, False)
        except Exception as e:                        # noqa: BLE001
            errors.append(_describe(e))

        self._settle(cfg, manifest, errors, t0,
                     "config" if reload_config else
                     ("tex" if compile_tex else "lean"))
        if manifest is not None:
            self._want_enrich(cfg, errors)

    # -- elaboration, behind the rebuild ------------------------------------
    #
    # Elaboration cannot go in the pass above.  Every module is handed to Lean
    # separately and each invocation imports that module's whole closure, so
    # the cost is seconds on a development with no dependencies and minutes on
    # one built over Mathlib — and it is not only the edited module: a type
    # shown in a module downstream genuinely changes when the module it imports
    # does, so an edit to a base module re-elaborates everything that imports
    # it.  Blocking on that would mean an editor whose page follows a `.lean`
    # edit a minute later, which is not following.
    #
    # So the page is published twice.  The first is the reader this tool has
    # always produced, within the second it has always taken; the second
    # replaces it with the elaborated one when Lean is done.  The reader sees
    # their edit immediately and the types catch up.

    def _want_enrich(self, cfg: Config, errors: list[str]) -> None:
        """Ask for an elaborated pass, superseding any that is queued."""
        on = cfg.elaborate if self._elaborate is None else self._elaborate
        if not on:
            return
        with self._enrich_lock:
            self._enrich_next = (cfg, list(errors))
            if self._enrich_busy:
                # one is running; it will pick this up when it finishes rather
                # than a second `lake` fighting the first for the same lock
                return
            self._enrich_busy = True
        threading.Thread(target=self._enrich, daemon=True).start()

    def _enrich(self) -> None:
        while True:
            with self._enrich_lock:
                want = self._enrich_next
                self._enrich_next = None
                if want is None:
                    self._enrich_busy = False
                    return
            cfg, errors = want
            with self._lock:
                started = self._gen
            t0 = time.monotonic()
            try:
                manifest = _build_manifest(cfg, True)
            except Exception as e:                    # noqa: BLE001
                self._settle(None, None, errors + [_describe(e)], t0, "lean+")
                continue
            with self._lock:
                stale = self._gen != started
            if stale:
                # the sources moved while Lean was working; publishing this
                # would put types from the previous edit on the current text
                continue
            self._settle(cfg, manifest, errors, t0, "lean+")

    def _settle(self, cfg: Config | None, manifest: dict | None,
                errors: list[str], t0: float, kind: str) -> None:
        full = "\n".join(errors)
        with self._lock:
            if cfg is not None:
                self._cfg = cfg
            if manifest is not None:
                self._manifest = manifest
                self._gen += 1
            # Clipped for the wire, whole for the terminal.  A failed latexmk
            # run reports its log, which is tens of kilobytes; the browser
            # wants to know that something broke and roughly what, and the
            # person who can fix it is reading the other window.
            self._error = _clip(full) or None
            # The same shape as `/status`, so a client may read either without
            # learning two spellings of one answer.
            state = {"ok": self._error is None, "error": self._error,
                     "gen": self._gen}

        took = time.monotonic() - t0
        stamp = time.strftime("%H:%M:%S")
        # Flushed, because this line is the session's only feedback and a
        # server whose output is piped to a log would otherwise hold it until
        # the buffer fills — which is to say, until it no longer matters.
        if state["ok"]:
            print(f"[{stamp}] {kind:6s} rebuilt   gen {state['gen']}"
                  f"   {took:.2f}s", flush=True)
        else:
            print(f"[{stamp}] {kind:6s} FAILED"
                  f"{'  (serving the previous build)' if self._served() else ''}"
                  f"   {took:.2f}s", file=sys.stderr)
            print(_indent(full), file=sys.stderr)
        # Published on failure too: the page has no other way to learn that
        # what it is showing is not what is on disk.
        self._publish(state)

    def _served(self) -> bool:
        with self._lock:
            return self._manifest is not None


def _describe(e: BaseException) -> str:
    """An error as the person watching the terminal needs to see it."""
    name = type(e).__name__
    if name in _EXPECTED:
        return str(e) or name
    # An exception the pipeline did not name is a bug in the pipeline, and a
    # bug reported without its traceback costs an hour of guessing.
    return "".join(traceback.format_exception(e)).rstrip()


def _clip(s: str, limit: int = 2000) -> str:
    return s if len(s) <= limit else s[:limit] + "\n… (see the terminal)"


def _indent(s: str) -> str:
    return "\n".join("    " + ln for ln in s.splitlines())


# --------------------------------------------------------------------------
# watching
# --------------------------------------------------------------------------

def _scan(cfg: Config, extra: Sequence[str] = ()) -> tuple[
        dict[str, tuple[float, int]], dict[str, set[str]]]:
    """Every relevant file's `(mtime, size)`, and which documents claim it.

    Polling, not inotify.  A file-system watcher is a third-party dependency on
    every platform this runs on, and the project's whole promise is that a
    Python and a LaTeX install are enough.  The cost is bounded by the size of
    the thing being watched: a paper and a formalization are tens to a few
    hundred files, one `stat` each, twice a second — below the noise floor of
    the editor that is also open on them.  If a project ever reaches the scale
    where this shows up in a profile, that is the moment to reach for a
    watcher, and not before.
    """
    stamps: dict[str, tuple[float, int]] = {}
    owners: dict[str, set[str]] = {}
    skip = {_key(cfg.build_dir), _key(cfg.out_dir)}
    root = _key(cfg.root)

    def add(p: Path, owner: str | None) -> None:
        k = _key(p)
        if any(k == s or k.startswith(s + os.sep) for s in skip):
            return
        if k not in stamps:
            try:
                st = p.stat()
            except OSError:
                # A file mid-save can be absent for an instant.  Its
                # reappearance is itself a change, so skipping it here costs
                # nothing but a poll.
                return
            stamps[k] = (st.st_mtime, st.st_size)
        if owner is not None:
            owners.setdefault(k, set()).add(owner)

    add(cfg.path, None)
    for doc in cfg.documents:
        for p in _walk(doc.root, skip, TEX_SUFFIXES):
            add(p, doc.id)
        # The `.fls` is latexmk's own answer to "what did this document read",
        # which is the only way to learn about a shared preamble that lives
        # outside every document root.  It exists only after a first compile,
        # so it refines the watch set rather than defining it.
        for p in _fls_inputs(doc, root):
            add(p, doc.id)
    for p in cfg.lean_files():
        add(p, None)
    # `extra` is the last successful build's own list of what it read, which
    # catches the one thing the `.fls` cannot: bibtex's inputs never appear
    # there, so a `.bib` outside every document root is invisible until the
    # manifest names it.  Unattributed on purpose — a shared bibliography
    # belongs to whichever document cites it, which is all of them.
    for rel in extra:
        add(_project_path(cfg.root, rel), None)
    return stamps, owners


def _project_path(root: Path, rel: str) -> Path:
    # The inverse of the manifest's `_outside/` spelling for a source that
    # lives above the project root.
    if rel.startswith("_outside/"):
        return Path("/" + rel[len("_outside/"):])
    return root / rel


def _walk(root: Path, skip: set[str], suffixes: set[str]) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        # Pruned, not filtered afterwards: the build directory holds a copy of
        # every intermediate the document produced, and walking into it means
        # the build's own output is watched — a loop that rebuilds forever.
        dirnames[:] = [d for d in sorted(dirnames)
                       if not d.startswith(".") and _key(here / d) not in skip]
        for f in sorted(filenames):
            if Path(f).suffix in suffixes:
                out.append(here / f)
    return out


def _fls_inputs(doc: Document, root: str) -> list[Path]:
    fls = doc.build_dir / (Path(doc.main).stem + ".fls")
    try:
        text = fls.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[Path] = []
    for line in text.splitlines():
        if not line.startswith("INPUT "):
            continue
        p = Path(line[6:].strip())
        # Relative entries are relative to the directory latexmk ran in, which
        # is the document root — not the build directory the `.fls` sits in.
        if not p.is_absolute():
            p = doc.root / p
        k = _key(p)
        # Only inputs inside the project: the rest is the TeX distribution,
        # thousands of files that change when the machine is updated and never
        # otherwise.
        if k == root or k.startswith(root + os.sep):
            out.append(p)
    return out


def _key(p: Path) -> str:
    try:
        return os.path.normcase(str(p.resolve()))
    except OSError:
        return os.path.normcase(str(p.absolute()))


def _diff(a: dict[str, tuple[float, int]],
          b: dict[str, tuple[float, int]]) -> set[str]:
    return {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}


def _read_sources(manifest: dict | None) -> list[str]:
    if not manifest:
        return []
    return [s["path"] for s in manifest.get("sources") or []] + \
           [a["path"] for a in manifest.get("assets") or []]


def _watch(live: _Live, stop: threading.Event) -> None:
    stamps, _ = _scan(live.cfg, _read_sources(live.manifest))
    while not stop.wait(POLL):
        cfg, extra = live.cfg, _read_sources(live.manifest)
        fresh, owners = _scan(cfg, extra)
        changed = _diff(stamps, fresh)
        if not changed:
            stamps = fresh
            continue

        # Settle first.  A save is often a truncate, a write and a rename, and
        # rebuilding on the truncate means compiling an empty file and showing
        # the reader an error that was never true.
        while not stop.wait(DEBOUNCE):
            newer, owners = _scan(cfg, extra)
            again = _diff(fresh, newer)
            fresh = newer
            changed |= again
            if not again:
                break
        if stop.is_set():
            return

        config_changed, lean, docs = _classify(cfg, changed, owners)
        if config_changed:
            live.rebuild(reload_config=True)
        elif docs:
            live.rebuild(doc_ids=docs, compile_tex=True)
        elif lean:
            live.rebuild(compile_tex=False)
        # Re-scanned after the build, not before: the build writes into the
        # source tree (a `.bbl`, a regenerated `.cls`) often enough that
        # carrying the pre-build stamps forward would rebuild a second time.
        stamps, _ = _scan(live.cfg, _read_sources(live.manifest))


def _classify(cfg: Config, changed: set[str],
              owners: dict[str, set[str]]) -> tuple[bool, bool, set[str]]:
    """(the configuration moved, some Lean moved, which documents moved)."""
    config_key = _key(cfg.path)
    config_changed = config_key in changed
    lean = False
    docs: set[str] = set()
    for k in changed:
        if k == config_key:
            continue
        if k.endswith(".lean"):
            lean = True
        elif k in owners:
            docs |= owners[k]
        else:
            # A watched file nobody claims: a shared bibliography, or one that
            # was deleted between two scans.  Neither is attributable, and a
            # needless latexmk run — which latexmk itself will cut short — is
            # cheaper than a document left stale.
            docs |= {d.id for d in cfg.documents}
    return config_changed, lean, docs


# --------------------------------------------------------------------------
# the server
# --------------------------------------------------------------------------

def _handler(live: _Live, page: bytes) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 so the event stream is not closed after each response — and
        # therefore every reply below must carry an accurate Content-Length or
        # send `Connection: close`, or the browser waits for a body that never
        # ends.
        protocol_version = "HTTP/1.1"
        server_version = f"interproof/{__version__}"

        def do_GET(self) -> None:                      # noqa: N802
            path = unquote(urlsplit(self.path).path)
            if path == "/":
                return self._send(page, "text/html; charset=utf-8")
            if path == "/manifest.json":
                m = live.manifest
                if m is None:
                    return self._json(
                        {"error": live.status()["error"] or "no build yet"},
                        code=503)
                return self._send(
                    json.dumps(m, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            if path == "/status":
                return self._json(live.status())
            if path == "/events":
                return self._events()
            if path.startswith("/pdf/") and path.endswith(".pdf"):
                return self._pdf(path[len("/pdf/"):-len(".pdf")])
            self.send_error(404, "not found")

        # -- documents ----------------------------------------------------

        def _pdf(self, doc_id: str) -> None:
            """A document by its id, looked up in the configuration.

            By id and never by path: the only file this server will read is one
            a `[[document]]` names, so no amount of `..` in a URL reaches
            anything else.  There is nothing else to serve — the viewer is in
            the page — so this is the whole of the file surface.
            """
            doc = live.cfg.document(doc_id)
            if doc is None or not doc.pdf.is_file():
                return self.send_error(404, "no such document")
            try:
                data = doc.pdf.read_bytes()
            except OSError as e:
                return self.send_error(500, e.strerror or "unreadable")
            self._send(data, "application/pdf")

        # -- events -------------------------------------------------------

        def _events(self) -> None:
            q = live.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                # Buffering proxies hold a stream until it is large enough to
                # be worth forwarding, which for an event stream means the
                # event arrives after the reload it was meant to cause.
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self.close_connection = True
                # A client that connects after a rebuild has missed it, and
                # would otherwise sit on a stale manifest until the next edit.
                self._event(live.status())
                while True:
                    try:
                        msg = q.get(timeout=PING)
                    except queue.Empty:
                        # A comment line: idle connections are dropped by
                        # proxies and by browsers, and a dropped stream is a
                        # page that silently stops updating.
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    if msg is None:
                        break
                    self._event(msg)
            except (BrokenPipeError, ConnectionResetError):
                pass                    # the tab was closed; not an error
            finally:
                live.unsubscribe(q)

        def _event(self, msg: dict) -> None:
            self.wfile.write(
                b"data: " + json.dumps(msg).encode("utf-8") + b"\n\n")
            self.wfile.flush()

        # -- plumbing -----------------------------------------------------

        def _json(self, obj: dict, code: int = 200) -> None:
            self._send(json.dumps(obj).encode("utf-8"),
                       "application/json; charset=utf-8", code=code)

        def _send(self, data: bytes, ctype: str, code: int = 200) -> None:
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                # Everything here is rebuilt while the page is open, so nothing
                # here may be cached: a conditional request answered from the
                # browser's cache is exactly the stale document the reader
                # reloaded to get rid of.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt: str, *args) -> None:
            # Silent by choice.  The viewer makes a request per document and
            # holds one open per tab; a line for each buries the build output,
            # which is the only reason anyone is watching this terminal.
            pass

        def log_error(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return Handler


def serve(cfg: Config, *, host: str = "127.0.0.1", port: int = 8777,
          watch: bool = True, open_browser: bool = False,
          skip_pdf: bool = False, elaborate: bool | None = None) -> int:
    """Serve the reader live until interrupted.  Returns a process exit code."""
    if not _loopback(host):
        print(f"!! binding {host}: this server runs latexmk on the files it is "
              f"given and has no authentication of any kind.\n"
              f"!! it is a development tool for one machine; do not put it on "
              f"a network.", file=sys.stderr)

    live = _Live(cfg, skip_pdf=skip_pdf, elaborate=elaborate)
    # Rendered once.  The page is the viewer, and the viewer is not what the
    # session edits; re-rendering it per request would inline pdf.js on every
    # reload and still show the same bytes.
    page = render_html(cfg, boot_literal({
        "mode": "live",
        "manifest_url": "manifest.json",
        "pdf_url": "pdf/",
        "events_url": "events",
    })).encode("utf-8")

    try:
        httpd = ThreadingHTTPServer((host, port), _handler(live, page))
    except OSError as e:
        print(f"cannot listen on {host}:{port} — {e.strerror or e}",
              file=sys.stderr)
        return 1
    httpd.daemon_threads = True
    # `server_close` joins every handler thread by default, and one of those
    # threads is an event stream writing to a browser that may have stopped
    # reading without closing.  The streams are woken explicitly below; this
    # is the guarantee that a client which does not cooperate cannot keep the
    # server alive after Ctrl-C.
    httpd.block_on_close = False

    url = f"http://{host}:{port}/"
    print(f"interproof  {cfg.title}")
    print(f"   {url}")
    print(f"   watching {'on' if watch else 'off'}"
          f"{'   latexmk skipped' if skip_pdf else ''}"
          f"   {len(cfg.documents)} document(s), "
          f"{len(cfg.lean_files())} Lean modules", flush=True)
    live.rebuild()

    stop = threading.Event()
    _install_signals(stop)
    threads = [threading.Thread(target=httpd.serve_forever, name="http",
                                daemon=True)]
    if watch:
        threads.append(threading.Thread(target=_watch, args=(live, stop),
                                        name="watch", daemon=True))
    for t in threads:
        t.start()
    if open_browser:
        threading.Timer(0.3, webbrowser.open, [url]).start()

    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        print()
    finally:
        stop.set()
        httpd.shutdown()
        # Woken before the socket closes, so a stream thread ends on its own
        # sentinel rather than on a write to a closed file.
        live.close()
        httpd.server_close()
    return 0


def _install_signals(stop: threading.Event) -> None:
    """Ctrl-C, and a supervisor's TERM, both mean the same thing here.

    A flag rather than a trusted `KeyboardInterrupt`: the exception reaches
    only the main thread and only where the interpreter installed its own
    SIGINT handler, which a process started as a background job does not get.
    A server that has to be killed twice is a server nobody trusts to stop.
    """
    def handler(signum, frame) -> None:                # noqa: ARG001
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            # Not the main thread; the caller's own handling stands.
            pass


def _loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost", "")
