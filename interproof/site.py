"""The artifact: one folder that holds the reader and everything it reads.

The deliverable is not a page, it is a *folder you can hand to someone* — a
referee, a coauthor, a supervisor — who has neither LaTeX nor Lean nor a
server, double-clicks `index.html`, and reads the paper beside its
formalization.  Everything else in the layout follows from that sentence:

  * the PDFs are inlined as base64, because `file://` refuses `fetch` of a
    sibling file and an artifact that needs a web server is an artifact the
    recipient will not open;
  * the same PDFs are written again under `pdf/`, because a folder that keeps
    only a 5 MB HTML blob cannot be diffed, re-compiled, or salvaged when the
    viewer is three versions obsolete;
  * `sources/` and `interproof.toml` are there so the artifact reproduces
    itself: the folder carries what it was built from, not only what it shows.

The duplication of the PDF is deliberate and is reported in the build summary,
so the cost is a decision rather than a surprise.
"""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

from .config import Config

WEB = Path(__file__).resolve().parent / "web"

# Where the artifact records what it wrote.  Without it a rebuild cannot tell
# its own stale output from a file the user dropped in the folder, and the only
# safe move would be to leave both — which is how an artifact accumulates the
# PDF of a document that was deleted from the configuration two builds ago.
INVENTORY = ".interproof-files"


class SiteError(Exception):
    """A build that cannot produce a readable artifact.

    Carries what was expected and where it was looked for: this is raised at
    the end of a long build, and the message is all the reader gets.
    """


# The paper grain, as a data URI, so the page stays self-contained.  It is
# generated rather than shipped because it is 300 bytes of SVG filter and a
# binary texture would be 40 KB.
GRAIN_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' "
    "numOctaves='3' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/>"
    "</filter><rect width='180' height='180' filter='url(#n)' opacity='.055'/></svg>"
)

# Placeholder -> the file under `web/` that fills it.  The template belongs to
# the viewer and this table is the whole of the contract between them: a
# renamed placeholder fails the build with the name, rather than shipping a
# page with a literal `/*APPJS*/` in it.
_ASSETS = {
    "/*FONTS*/": "fonts.css",
    "/*APPCSS*/": "app.css",
    "/*PDFJS*/": "vendor/pdf.min.mjs",
    "/*PDFJSWORKER*/": "vendor/pdf.worker.min.mjs",
    "/*PDFVIEW*/": "pdfview.js",
    "/*LEANVIEW*/": "leanview.js",
    "/*DOWNLOAD*/": "download.js",
    "/*APPJS*/": "app.js",
}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def boot_literal(payload: dict) -> str:
    """`payload` as a JS object literal safe to sit inside `<script>`.

    Two escapes, both learned the hard way:

    `<` is rewritten to `\\u003c`.  Inside a `<script>` the HTML parser is
    still hunting for `</script`, and one Lean file containing `</script>` in a
    comment would truncate the page.  `<` can only occur inside a JSON string,
    so the escape keeps the literal valid JSON *and* valid JS while making the
    sequence unspellable.  (The base64 alphabet cannot spell it either, which
    is why the PDFs need no such treatment.)

    U+2028 and U+2029 are rewritten for the same reason a JSON payload is not
    a JS literal: they are legal in JSON strings and were, until ES2019, line
    terminators in JavaScript.  Escaping costs nothing and removes a failure
    that only ever shows up in someone else's browser.
    """
    return (json.dumps(payload, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def render_html(cfg: Config, boot: str) -> str:
    """The viewer, with every asset inlined and `boot` as its only input.

    `boot` is the one place the static artifact and the live server differ:
    same page, same code, different answer to "where does the data come from".
    Keeping the divergence to a single argument is what stops the two modes
    from drifting into two viewers.
    """
    tpl = _read(WEB / "index.template.html")
    pieces = {k: _read(WEB / rel) for k, rel in _ASSETS.items()}
    pieces["/*APPCSS*/"] = _with_grain(pieces["/*APPCSS*/"])
    pieces["/*BOOT*/"] = boot
    # The title reaches both the <title> element and the page header, so it is
    # HTML, not text: a project called `A <-> B` must not close the head.
    pieces["<!--TITLE-->"] = html.escape(cfg.title)

    missing = [k for k in pieces if k not in tpl]
    if missing:
        raise SiteError(
            f"{WEB / 'index.template.html'}: no placeholder "
            f"{', '.join(sorted(missing))}.\n"
            f"    The template and this module disagree about the page; one of "
            f"them was renamed without the other.")
    return _substitute(tpl, pieces)


def _substitute(tpl: str, pieces: dict[str, str]) -> str:
    """Every placeholder replaced in one pass.

    One pass, not a loop of `str.replace`: the inlined app.js is free to
    contain the literal text `/*FONTS*/` in a comment, and a second pass would
    happily expand it.  And the replacement is a function rather than a string
    because `re.sub` reads backslashes in replacements — which would quietly
    corrupt every regex in the viewer and every `\\\\` in a Lean source.
    """
    pat = re.compile("|".join(re.escape(k) for k in
                              sorted(pieces, key=len, reverse=True)))
    return pat.sub(lambda m: pieces[m.group(0)], tpl)


def _with_grain(app_css: str) -> str:
    grain = 'url("data:image/svg+xml;base64,%s")' % base64.b64encode(
        GRAIN_SVG.encode()).decode()
    decl = "  --grain: %s;\n" % grain
    # The anchor is app.css's, and app.css is not this module's file.  When the
    # stylesheet moves its variable block, a trailing `:root` rule has the same
    # effect by the cascade, so a rename there is a cosmetic diff and not a
    # build failure.
    if "--rail: 268px;" in app_css:
        return app_css.replace("--rail: 268px;", "--rail: 268px;\n" + decl, 1)
    return app_css + "\n:root {\n" + decl + "}\n"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        raise SiteError(f"{p}: {e.strerror or e}.\n"
                        f"    The viewer's assets ship inside the package; a "
                        f"missing one means an incomplete install.") from None


# --------------------------------------------------------------------------
# the folder
# --------------------------------------------------------------------------

def build_site(cfg: Config, manifest: dict, out: Path,
               *, inline: bool = True) -> None:
    """Write the whole artifact to `out`, and report what it cost."""
    out = Path(out)
    docs = manifest.get("docs") or []
    if not docs:
        raise SiteError("the manifest holds no documents; there is nothing to "
                        "read against the formalization")

    pdfs = _read_pdfs(cfg, docs)
    boot: dict = {"mode": "static", "manifest": manifest}
    if inline:
        boot["pdfs"] = {i: base64.b64encode(b).decode() for i, b in pdfs.items()}
    else:
        boot["pdf_url"] = "pdf/"
    page = render_html(cfg, boot_literal(boot)).encode("utf-8")

    files: dict[str, bytes] = {"index.html": page}
    # The same encoding as the copy embedded in the page, so the two are the
    # same bytes and a reader comparing them is not misled by whitespace.
    files["manifest.json"] = json.dumps(
        manifest, ensure_ascii=False).encode("utf-8")
    for doc_id, data in pdfs.items():
        files[f"pdf/{doc_id}.pdf"] = data

    sources, missing = _sources(cfg, manifest)
    files.update(sources)
    files["interproof.toml"] = (
        manifest.get("config") or cfg.text).encode("utf-8")
    files["README.md"] = _readme(cfg, manifest, inline=inline).encode("utf-8")

    kept = _write_all(out, files)

    _report(out, files, len(sources), inline=inline, kept=kept, missing=missing)


def _read_pdfs(cfg: Config, docs: list[dict]) -> dict[str, bytes]:
    pdfs: dict[str, bytes] = {}
    for d in docs:
        doc = cfg.document(d["id"])
        if doc is None:
            raise SiteError(
                f"the manifest names a document {d['id']!r} that "
                f"{cfg.path} does not declare; rebuild the manifest")
        if not doc.pdf.is_file():
            raise SiteError(
                f"{doc.pdf} missing — compile {doc.id} first "
                f"(`interproof pdf`, or `interproof build` which does both)")
        pdfs[doc.id] = doc.pdf.read_bytes()
    return pdfs


def _sources(cfg: Config, manifest: dict) -> tuple[dict[str, bytes], list[str]]:
    """Everything the artifact carries under `sources/`, and what it could not.

    Paths arrive relative to a root, and a root is read from a configuration
    that may point anywhere — `root = "../shared/paper"` is legal and useful.
    A relative path is therefore not automatically a *safe* path, and a single
    `..` would have the build writing outside the folder it was handed.  Every
    path is checked rather than trusted.
    """
    out: dict[str, bytes] = {}
    missing: list[str] = []
    for s in manifest.get("sources") or []:
        out["sources/" + _safe(s["path"], "sources")] = s["text"].encode("utf-8")
    lean_root = _safe(manifest.get("lean_root") or "lean", "lean_root")
    for f in manifest.get("lean") or []:
        out["sources/" + lean_root + "/" + _safe(f["path"], "lean")] = \
            f["text"].encode("utf-8")
    for a in manifest.get("assets") or []:
        rel = _safe(a["path"], "assets")
        if a.get("b64"):
            out["sources/" + rel] = base64.b64decode(a["b64"])
            continue
        # A figure too large for the page is still small enough for a folder.
        # The manifest names it and leaves it on disk precisely so that the
        # artifact can take the copy the page declined — `sources/` that will
        # not compile for want of a plot is not a source tree.
        try:
            out["sources/" + rel] = _on_disk(cfg.root, rel).read_bytes()
        except OSError:
            missing.append(rel)
    return out, missing


def _on_disk(root: Path, rel: str) -> Path:
    # The inverse of the manifest's `_outside/` spelling for a document root
    # that lives above the project.
    if rel.startswith("_outside/"):
        return Path("/" + rel[len("_outside/"):])
    return root / rel


def _safe(rel: str, what: str) -> str:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise SiteError(
            f"{what}: refusing to place {rel!r} in the artifact — it escapes "
            f"the folder.\n"
            f"    A source outside the project root cannot be carried by a "
            f"relative layout; move it under the root, or point the "
            f"configuration at a root that contains it.")
    return p.as_posix()


def _write_all(out: Path, files: dict[str, bytes]) -> list[str]:
    """Write every file, retire the previous build's leftovers, keep the rest.

    `out` is a directory the user named, and a user names `.` sooner or later,
    so nothing here removes a tree.  Deletion is limited to paths this tool
    wrote last time and did not write this time; anything else found in the
    folder is left alone and reported, because a build is not entitled to an
    opinion about files it has never seen.
    """
    for rel, data in sorted(files.items()):
        p = out / rel
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Bytes, never text mode: the artifact must be reproducible, and
            # text mode rewrites newlines per platform.
            p.write_bytes(data)
        except OSError as e:
            raise SiteError(f"{p}: {e.strerror or e}") from None

    previous = _inventory(out)
    for rel in sorted(previous - set(files)):
        p = out / rel
        if p.is_file():
            p.unlink()
            _prune(out, p.parent)

    (out / INVENTORY).write_bytes(
        ("\n".join(sorted(files)) + "\n").encode("utf-8"))

    known = set(files) | previous | {INVENTORY}
    return sorted(rel for rel in _walk(out) if rel not in known)


def _inventory(out: Path) -> set[str]:
    """The previous build's file list, as far as it can be believed.

    This list is read back from the folder and then used to delete, so a line
    that names anything but a plain path inside the folder is dropped rather
    than acted on: a corrupted or hand-edited inventory must not be able to
    reach outside the artifact.
    """
    try:
        text = (out / INVENTORY).read_text(encoding="utf-8")
    except OSError:
        return set()
    kept = set()
    for line in text.splitlines():
        rel = line.strip()
        p = Path(rel)
        if rel and not p.is_absolute() and ".." not in p.parts:
            kept.add(p.as_posix())
    return kept


def _walk(out: Path) -> list[str]:
    return sorted(p.relative_to(out).as_posix()
                  for p in out.rglob("*") if p.is_file())


def _prune(out: Path, d: Path) -> None:
    """Remove directories a retired file left empty, never the folder itself."""
    while d != out and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


# --------------------------------------------------------------------------
# what the recipient reads first
# --------------------------------------------------------------------------

def _readme(cfg: Config, manifest: dict, *, inline: bool) -> str:
    proj = manifest.get("project") or {}
    tool = manifest.get("tool", "interproof")
    lean_root = manifest.get("lean_root", "lean")
    docs = manifest.get("docs") or []
    stats = manifest.get("stats") or {}

    lines = [
        f"# {cfg.title} — Interproof artifact",
        "",
        f"A paper and its formalization, read side by side.  Built by "
        f"`{tool}` from `{proj.get('root', cfg.root.name)}` on "
        f"{manifest.get('generated', 'an unrecorded date')}.",
        "",
        "## Reading it",
        "",
    ]
    if inline:
        lines += [
            "Open `index.html` in a browser.  Double-clicking the file is "
            "enough — there is nothing to install and no server to start.  "
            "The documents are embedded in the page, so the folder can be "
            "zipped, mailed, and read offline.",
        ]
    else:
        lines += [
            "**This variant needs an HTTP server.**  It was built without "
            "embedding the PDFs, so `index.html` fetches them from `pdf/`, and "
            "a browser refuses `fetch` across `file://`.  From this folder:",
            "",
            "    python3 -m http.server 8000",
            "",
            "then open <http://localhost:8000/>.  Rebuild without "
            "`--no-inline` for a folder that opens by double-click.",
        ]
    lines += [
        "",
        "## What is in here",
        "",
        "| path | |",
        "| --- | --- |",
        "| `index.html` | the reader: viewer, fonts, pdf.js and the "
        "correspondence, in one file |",
        "| `manifest.json` | the correspondence itself — every cited statement, "
        "where it sits in the PDF, and which declaration cites it |",
        "| `pdf/` | the compiled documents |",
        "| `sources/` | the LaTeX and Lean sources these were built from, "
        "figures included |",
        "| `interproof.toml` | the configuration that describes the pair |",
        "",
        "The documents appear twice on purpose: once embedded in `index.html`, "
        "which is what makes the page readable by double-click, and once as "
        "files under `pdf/`, which is what makes the folder archivable and "
        "re-buildable when this viewer is obsolete.  The cost is one extra "
        "copy of each PDF, inflated by a third by base64.",
        "",
        "## Documents",
        "",
    ]
    for d in docs:
        rev = d.get("rev", "")
        lines.append(f"- **{d.get('short') or d['id']}** — {d.get('title', '')}"
                     f"  (`{d.get('main', '')}`{', rev ' + rev if rev else ''})")
    lines += [
        "",
        f"The formalization is `sources/{lean_root}/`: "
        f"{stats.get('lean_files', len(manifest.get('lean') or []))} modules, "
        f"{stats.get('lean_decls', '?')} declarations.",
        "",
        "## Rebuilding",
        "",
        "`sources/` mirrors the project tree, so a document rebuilds where it "
        "sits:",
        "",
    ]
    for d in docs:
        main = Path(d.get("main", ""))
        where = main.parent.as_posix()
        # The document's own command, not a plausible one: a paper that needs
        # `-lualatex` or a `BIBINPUTS` is a paper whose README must say so, or
        # the sources it carries do not in fact rebuild.
        doc = cfg.document(d["id"])
        cmd = " ".join([*(doc.latexmk if doc else ["latexmk", "-pdf",
                                                   "-synctex=1"]), main.name])
        env = " ".join(f"{k}={v}" for k, v in (doc.env if doc else {}).items())
        lines.append(f"    cd sources{'/' + where if where != '.' else ''} && "
                     f"{env + ' ' if env else ''}{cmd}")
    lines += [
        "",
        "`-synctex=1` is not optional: the `.synctex.gz` is what lets a "
        "`\\label` be located as a rectangle on a page, and so what lets this "
        "reader show the typeset statement rather than a re-render of its "
        "source.",
        "",
        "To rebuild the whole artifact, put these sources back beside the "
        "formalization, keep `interproof.toml` next to them, and run "
        "`interproof build`.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# the summary
# --------------------------------------------------------------------------

def _report(out: Path, files: dict[str, bytes], n_src: int,
            *, inline: bool, kept: list[str], missing: list[str]) -> None:
    def mb(n: int) -> str:
        return f"{n / 1024 / 1024:7.2f} MB" if n >= 1024 * 1024 \
            else f"{n / 1024:7.0f} KB"

    page = len(files["index.html"])
    pdf_bytes = sum(len(v) for k, v in files.items() if k.startswith("pdf/"))
    src_bytes = sum(len(v) for k, v in files.items() if k.startswith("sources/"))
    total = sum(len(v) for v in files.values())

    print(f"site  {out}")
    print(f"   index.html   {mb(page)}"
          f"{'   (documents embedded)' if inline else '   (documents fetched from pdf/)'}")
    print(f"   manifest     {mb(len(files['manifest.json']))}")
    print(f"   pdf/         {mb(pdf_bytes)}   {sum(1 for k in files if k.startswith('pdf/'))} documents")
    print(f"   sources/     {mb(src_bytes)}   {n_src} files")
    print(f"   total        {mb(total)}")
    if inline:
        # Say the price out loud.  Someone comparing the folder size against
        # the PDFs deserves to know where the difference went.
        print(f"   the documents are held twice — embedded and under pdf/ — "
              f"costing {mb(int(pdf_bytes * 4 / 3))} of the page")
    else:
        print("   !! this variant does not open by double-click: serve the "
              "folder over HTTP (`python3 -m http.server`), or rebuild "
              "with the documents embedded")
    if missing:
        shown = ", ".join(missing[:4]) + ("…" if len(missing) > 4 else "")
        print(f"   !! {len(missing)} source(s) named by the manifest were not "
              f"on disk and are absent from sources/: {shown}")
    if kept:
        shown = ", ".join(kept[:4]) + ("…" if len(kept) > 4 else "")
        print(f"   kept {len(kept)} file(s) already in the folder and not "
              f"part of this build: {shown}")
