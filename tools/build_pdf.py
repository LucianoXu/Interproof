#!/usr/bin/env python3
"""Compile every document in the DOCS table, with SyncTeX enabled.

`-synctex=1` is the whole point: it is what lets a `\\label` be located as a
page and a rectangle, and so what lets the reader show the typeset page
instead of a re-render of its source.

Incrementality is latexmk's own — it consults its `.fdb_latexmk` and returns
in a fraction of a second when nothing changed — so this runs unconditionally
rather than duplicating dependency tracking in the Makefile.

Usage:  python3 tools/build_pdf.py [--force]
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import DOCS, ROOT                                    # noqa: E402

LATEXMK = ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode"]


def main(argv: list[str]) -> int:
    force = "--force" in argv
    for d in DOCS:
        out = d["pdf"].parent
        out.mkdir(parents=True, exist_ok=True)
        if not (d["root"] / d["main"]).exists():
            print(f"!! {d['root'].relative_to(ROOT)}/{d['main']} missing — "
                  f"run `make sync`", file=sys.stderr)
            return 1

        env = {**os.environ, **d.get("env", {})}
        cmd = LATEXMK + (["-g"] if force else []) + [
            "-outdir=" + os.path.relpath(out, d["root"]), d["main"]]
        # bytes, not text: a first run echoes the .log, which carries whatever
        # 8-bit bytes the fonts and packages put there and is not valid UTF-8
        r = subprocess.run(cmd, cwd=d["root"], env=env, capture_output=True)
        out = r.stdout.decode("utf-8", "replace")
        if r.returncode != 0 or not d["pdf"].exists():
            sys.stderr.write(out[-3000:] + r.stderr.decode("utf-8", "replace")[-2000:])
            print(f"!! {d['id']}: latexmk failed", file=sys.stderr)
            return 1
        fresh = "Nothing to do for" not in out            # latexmk's own verdict
        print(f"{d['id']:8s} {d['pdf'].relative_to(ROOT)}"
              f"  {d['pdf'].stat().st_size / 1024:.0f} KB"
              f"  {'rebuilt' if fresh else 'up to date'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
