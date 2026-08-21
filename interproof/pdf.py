"""Compile every document, with SyncTeX enabled.

`-synctex=1` is the whole point.  It is what lets a `\\label` be located as a
page and a rectangle, and so what lets the reader show the typeset page instead
of a re-render of its source — which was the one structural mistake this
project made and undid.  A 113-macro preamble and `\\inferrule` displays do not
survive re-rendering, and every approximation is a place where the reader
cannot trust what they are looking at.

Incrementality is latexmk's own: it consults its `.fdb_latexmk` and returns in
a fraction of a second when nothing changed, so this runs unconditionally
rather than duplicating dependency tracking a level up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import Config, Document


class PdfBuildError(Exception):
    """A document that did not compile, with the end of the log attached."""


def have_latexmk(cfg: Config) -> str | None:
    """The first document's compiler, if it can be found at all."""
    prog = cfg.documents[0].latexmk[0] if cfg.documents else "latexmk"
    return shutil.which(prog)


def compile_docs(cfg: Config, *, docs: list[Document] | None = None,
                 force: bool = False, quiet: bool = False) -> list[Document]:
    """Compile the given documents (all of them by default).

    Returns the documents whose PDF latexmk actually rewrote, which is what a
    watching server needs in order to decide what to tell the browser.
    """
    say = (lambda *a: None) if quiet else (lambda *a: print(*a))
    todo = docs if docs is not None else cfg.documents
    rebuilt: list[Document] = []

    for d in todo:
        if not d.main_path.exists():
            raise PdfBuildError(
                f"{d.id}: {d.main} not found in {d.root}\n"
                f"    Check the [[document]] entry in {cfg.path.name}.")
        d.build_dir.mkdir(parents=True, exist_ok=True)

        env = {**os.environ, **d.env}
        cmd = [*d.latexmk, *(["-g"] if force else []),
               "-outdir=" + os.path.relpath(d.build_dir, d.root), d.main]
        # bytes, not text: a first run echoes the .log, which carries whatever
        # 8-bit bytes the fonts and packages put there and is not valid UTF-8
        # stdin closed: TeX answers a missing file with a *prompt*, and under
        # `serve` that prompt would read from whatever terminal the server was
        # left running on — a build hung forever, with the watcher inside it.
        # EOF turns it into the failed run it already was.
        r = subprocess.run(cmd, cwd=d.root, env=env, capture_output=True,
                           stdin=subprocess.DEVNULL)
        out = r.stdout.decode("utf-8", "replace")
        if r.returncode != 0 or not d.pdf.exists():
            raise PdfBuildError(
                f"{d.id}: {' '.join(cmd[:1])} failed in {d.root}\n\n"
                + tail(out) + tail(r.stderr.decode("utf-8", "replace"), 1500))
        fresh = "Nothing to do for" not in out            # latexmk's own verdict
        if fresh:
            rebuilt.append(d)
        say(f"{d.id:8s} {d.pdf}  {d.pdf.stat().st_size / 1024:.0f} KB"
            f"  {'rebuilt' if fresh else 'up to date'}")
    return rebuilt


def tail(s: str, n: int = 3000) -> str:
    s = s.strip()
    return s if len(s) <= n else "…\n" + s[-n:]


def documents_for(cfg: Config, changed: list[Path]) -> list[Document]:
    """Which documents a set of changed files can possibly affect.

    A shared preamble belongs to every document that reads it, so membership is
    decided by what the last build recorded reading — not by which document's
    directory the file happens to sit in.
    """
    from .manifest import input_files

    out = []
    want = {p.resolve() for p in changed}
    for d in cfg.documents:
        inputs = set(input_files(d)) | {p.resolve() for p in d.source_files()}
        inputs.add(d.main_path.resolve())
        if want & inputs or any(is_under(p, d.root) for p in want):
            out.append(d)
    return out


def is_under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False
