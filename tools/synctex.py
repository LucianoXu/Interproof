#!/usr/bin/env python3
"""SyncTeX forward search: a labelled LaTeX item -> its rectangle in the PDF.

`synctex view` answers "where did source line L end up?" with one box per
typeset fragment it can attribute to that line.  The attribution is coarse:
a source line that wraps over four typeset lines usually yields fewer than
four boxes, and `\\end{...}` is commonly credited with the boxes of the
*following* paragraph.

So the extent of an item is bracketed rather than measured.  The top comes
from the `\\begin` line, which is reliable — it is where the theorem head is
set.  The bottom comes from the first box of whatever follows the
environment, which brackets the block from below and includes the trailing
paragraph gap.  That reads better than a tight fit: the band hugs the block
the way a highlighter would.
"""

from __future__ import annotations

import gzip
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_FIELD = re.compile(r"^([xyhvWH]):(-?[\d.]+)$", re.M)


@dataclass(frozen=True)
class Box:
    page: int
    x: float          # left edge, PDF points from the left
    top: float        # top edge, PDF points from the top of the page
    w: float
    h: float

    @property
    def bottom(self) -> float:
        return self.top + self.h

    def before(self, other: "Box") -> bool:
        return (self.page, self.top) < (other.page, other.top)


def _run(pdf: Path, srcdir: Path, name: str, line: int) -> list[Box]:
    out = subprocess.run(
        ["synctex", "view", "-i", f"{line}:1:{name}", "-o", str(pdf), "-d", str(srcdir)],
        capture_output=True, text=True).stdout
    boxes = []
    for blk in out.split("Page:")[1:]:
        page = int(blk.split("\n", 1)[0])
        f = {k: float(v) for k, v in _FIELD.findall(blk)}
        if "v" not in f or "W" not in f:
            continue
        if f["W"] <= 0 or f.get("H", 0) <= 0:
            continue          # degenerate anchor (page origin, empty box)
        boxes.append(Box(page, f["h"], f["v"] - f["H"], f["W"], f["H"]))
    return boxes


class SyncTeX:
    """Forward search over one compiled document."""

    def __init__(self, pdf: Path, srcdir: Path):
        self.pdf = Path(pdf).resolve()
        self.srcdir = Path(srcdir).resolve()
        self.ok = self.pdf.with_suffix(".synctex.gz").exists()
        self._inputs = self._read_inputs()

    def _read_inputs(self) -> set[str]:
        """Source files the .synctex.gz actually carries tags for."""
        gz = self.pdf.with_suffix(".synctex.gz")
        if not gz.exists():
            return set()
        names = set()
        with gzip.open(gz, "rt", errors="replace") as fh:
            for ln in fh:
                # `\input` inside the body emits Input records after the page
                # records have started, so the whole file has to be scanned
                if not ln.startswith("Input:"):
                    continue
                p = ln.split(":", 2)[-1].strip()
                try:
                    names.add(str(Path(p).resolve().relative_to(self.srcdir)))
                except ValueError:
                    pass
        return names

    def knows(self, name: str) -> bool:
        return str(Path(name)) in self._inputs

    @lru_cache(maxsize=None)
    def _at(self, name: str, line: int) -> tuple[Box, ...]:
        if line < 1:
            return ()
        return tuple(_run(self.pdf, self.srcdir, name, line))

    def start(self, name: str, line: int) -> Box | None:
        """Topmost box of a source line — where the item begins."""
        boxes = self._at(name, line)
        return min(boxes, key=lambda b: (b.page, b.top)) if boxes else None

    def rect(self, name: str, begin: int, end: int, lookahead: int = 4) -> dict | None:
        """Rectangle spanning the environment at source lines [begin, end]."""
        top = self.start(name, begin)
        if top is None:
            return None

        # Two independent readings of where the block stops, both needed.
        #
        # The body lines under-report: a wrapped source line yields fewer boxes
        # than typeset lines, so their lowest box often sits above the real end.
        # The first box typeset *after* the environment over-reports by the
        # paragraph gap, and sometimes under-reports instead, because a trailing
        # `\end{itemize}` can hand the last bullet to a line past `\end`.
        #
        # Whichever reaches lower is the one that saw the whole block.  Boxes
        # more than one page past the start are stray attributions, not content.
        limit = top.page + 1
        body = [b for ln in range(begin, end + 1) for b in self._at(name, ln)
                if not b.before(top) and b.page <= limit]
        floors = [Box(b.page, b.x, b.bottom, b.w, 0.0) for b in body]

        for ln in range(end + 1, end + lookahead + 2):
            after = [b for b in self._at(name, ln)
                     if top.before(b) and b.page <= limit]
            if after:
                floors.append(min(after, key=lambda b: (b.page, b.top)))
                break

        floor = (max(floors, key=lambda b: (b.page, b.top)) if floors
                 else Box(top.page, top.x, top.bottom, top.w, 0.0))

        return self.tighten({
            "page": top.page, "top": round(top.top, 2),
            "x": round(min(top.x, floor.x), 2),
            "w": round(max(top.w, floor.w), 2),
            "end_page": floor.page, "bottom": round(floor.top, 2),
        })

    # ---- tightening ------------------------------------------------------

    def _text(self):
        """Lazily opened text layout of the PDF, if PyMuPDF is installed."""
        if not hasattr(self, "_doc"):
            try:
                import fitz
                self._doc = fitz.open(self.pdf)
            except Exception:
                self._doc = None
        return self._doc

    def tighten(self, rect: dict) -> dict:
        """Pull the edges in to the text actually inside the band.

        SyncTeX brackets the block, it does not measure it: the bottom sits
        wherever the next paragraph starts, one blank line too low.  The
        typeset page knows better, so the bracket is only used to decide which
        lines belong, and their own extent sets the edge.
        """
        doc = self._text()
        if doc is None:
            return rect
        page = doc[rect["end_page"] - 1]
        ceiling = rect["top"] if rect["end_page"] == rect["page"] else 0.0
        x0, x1 = rect["x"], rect["x"] + rect["w"]

        # A line counts as inside when its middle is: synctex reports a box
        # without its ascender, so the head line starts a hair above `top`, and
        # the next paragraph's first line starts a hair above the bracket.
        # Testing the midpoint keeps the first and rejects the second.
        lines = []
        for blk in page.get_text("dict").get("blocks", []):
            for ln in blk.get("lines", []):
                b = ln["bbox"]
                if b[2] < x0 - 24 or b[0] > x1 + 24:      # a different column
                    continue
                mid = (b[1] + b[3]) / 2
                if ceiling <= mid <= rect["bottom"]:
                    lines.append(b)
        if lines:   # only ever pull the edge in, never push it past the bracket
            rect["bottom"] = round(min(rect["bottom"], max(b[3] for b in lines)), 2)
        return rect
