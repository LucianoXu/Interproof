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
_FOLIO = re.compile(r"[ivxlcdm\d]+", re.I)      # a page number, arabic or roman


def _text_module():
    """PyMuPDF, under whichever name this version answers to.

    `pymupdf` is the current import name and `fitz` the historical one; both
    are in the field, so both are tried.
    """
    for name in ("pymupdf", "fitz"):
        try:
            return __import__(name)
        except ImportError:
            continue
    return None


def have_text_layout() -> bool:
    """Whether bands can be measured rather than only bracketed."""
    return _text_module() is not None


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
        capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
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


# Slack when comparing with a floor, so a box that starts exactly where the
# previous clause ended is not excluded by a rounding difference.
_EPS = 0.5

# How far outside the coarse band a word may sit and still be part of the
# clause: a line's leading, since the band's edges are baselines.
_SLACK = 6.0
# How many page words a source word may skip over before the alignment is
# considered lost: enough for a formula between two words, not enough to walk
# into the next sentence.
_DRIFT = 8

_MACRO = re.compile(r"\\[A-Za-z@]+|%.*")
_ENV = re.compile(r"\\(?:begin|end)\{[^}]*\}")


def _detex(text: str) -> str:
    """Enough of the source stripped to leave the words a reader would see.

    Environment names go too: `\\begin{itemize}` puts "itemize" in the source
    and nothing on the page, and a word that cannot be found is a word that
    breaks a match.
    """
    return _MACRO.sub(" ", _ENV.sub(" ", text))


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

    def start(self, name: str, line: int,
              after: tuple[int, float] | None = None) -> Box | None:
        """Topmost box of a source line — where the item begins.

        With `after`, boxes at or above that point are left out: they are
        material the previous clause already accounted for.  If that empties
        the set the unfiltered one is used, so a floor can never lose an item.
        """
        boxes = self._at(name, line)
        if after is not None:
            below = [b for b in boxes
                     if (b.page, b.top) > (after[0], after[1] - _EPS)]
            boxes = below or boxes
        return min(boxes, key=lambda b: (b.page, b.top)) if boxes else None


    def anchor_rects(self, name: str,
                     spans: list[tuple[int, int]]) -> list[dict | None]:
        """Rectangles for the anchors of one statement, in document order.

        `rect` reads an environment, whose first source line is a
        `\\begin{...}` and therefore unambiguous.  An anchor claims lines in
        the middle of a paragraph, and there `synctex view` is not exact: the
        set it answers with holds the clause's own typeset lines *and* strays
        from the clause before it, because TeX breaks a paragraph while the
        input pointer already stands on the line that triggered the break.
        Taking `min` of that set opens the band on the previous clause.
        Measured on a real definition: the second `\\item` banded from the
        first, and the third from the second.

        The fix uses the one thing a single clause cannot know and its
        siblings can — clauses are typeset in the order they are written and
        do not overlap — so each anchor's top is taken from the boxes below
        where the previous clause ended.  It is a bound, not a guess, and it
        cannot invent a placement: an anchor with nothing below the floor
        keeps the boxes it had.

        What this does *not* recover is a clause whose own last lines were
        attributed to the next clause's line, which leaves the band short at
        the bottom.  `verify` is what makes that visible rather than silent.
        """
        out: list[dict | None] = []
        floor: tuple[int, float] | None = None
        for begin, end in spans:
            r = self.rect(name, begin, end, after=floor)
            out.append(r)
            if r:
                floor = (r["end_page"], r["bottom"])
        return out


    def prose_rects(self, rect: dict, want: str) -> list[dict] | None:
        """The band a *prose* clause really occupies, word by word.

        SyncTeX's unit is the typeset line, and a line box is the full
        measure.  A clause that begins mid-line therefore bands its
        neighbour's words as well as its own — the band is not wrong
        vertically, it is simply as wide as the page every time.  A quoted
        anchor escapes that because `\\pdfsavepos` marks two points; this does
        the same without asking the author to quote anything, by reading the
        page's own words and keeping the ones the clause actually claims.

        The coarse band says which lines to look at, so the same sentence
        occurring twice on a page is not a hazard.  Prose only: the maths comes
        back in an alphabet the source does not use, and a clause whose head or
        tail is a formula keeps its line band rather than being guessed at.
        """
        page = self._text()
        if page is None:
            return None
        target = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", _detex(want))]
        if len(target) < 4:
            return None
        words = []
        for pno in range(rect["page"], rect.get("end_page", rect["page"]) + 1):
            mid = lambda w: (w[1] + w[3]) / 2
            lo = rect["top"] - _SLACK if pno == rect["page"] else -1e9
            hi = rect["bottom"] + _SLACK if pno == rect.get(
                "end_page", rect["page"]) else 1e9
            words += [(pno, *w) for w in page[pno - 1].get_text("words")
                      if lo <= (w[1] + w[3]) / 2 <= hi]
        if not words:
            return None
        flat = [re.sub(r"[^a-z]", "", w[5].lower()) for w in words]

        def same(page_word: str, source_word: str) -> bool:
            # a page word can carry maths on either side -- `S2)-local.` for
            # the source's `local` -- and can be hyphenated across a line, so
            # containment either way is the honest test at this granularity
            if not page_word:
                # a page token with no letters is maths or a number: it can
                # sit between two words of the clause, but it can never *be*
                # one, and letting it match consumed the theorem's own number
                return False
            return (page_word.startswith(source_word)
                    or source_word.startswith(page_word)
                    or source_word in page_word)

        # The source's words and the page's are not a word-for-word
        # correspondence: maths lands between them (`map is (W1 ∪W2,
        # S1 ∪S2)-local`), so an n-gram of the source is rarely three
        # consecutive words of the page.  Walking both in order and consuming
        # what matches is what survives that; a run is accepted only when it
        # accounts for most of the clause, which is what keeps a stray
        # `the` from claiming half a page.
        hits: list[int] = []
        at = 0
        for word in target:
            probe = at
            while probe < len(flat) and probe - at <= _DRIFT:
                if same(flat[probe], word):
                    hits.append(probe)
                    at = probe + 1
                    break
                probe += 1
        if len(hits) < max(4, int(len(target) * 0.5)):
            return None
        span = sorted(words[hits[0]:hits[-1] + 1],
                      key=lambda w: (w[0], w[2], w[1]))
        # one rectangle per typeset line: the first and the last are partial,
        # which is the whole point of doing this
        out: list[dict] = []
        for pno, x0, y0, x1, y1, *_ in span:
            last = out[-1] if out else None
            if last and last["page"] == pno and abs(last["top"] - y0) < 3:
                last["x"] = min(last["x"], round(x0, 2))
                last["w"] = round(max(last["x"] + last["w"], x1) - last["x"], 2)
                last["bottom"] = max(last["bottom"], round(y1, 2))
            else:
                out.append({"page": pno, "end_page": pno, "top": round(y0, 2),
                            "bottom": round(y1, 2), "x": round(x0, 2),
                            "w": round(x1 - x0, 2), "precise": True})
        return out or None

    def verify(self, rect: dict, want: str) -> bool:
        """Does the band actually cover the words it claims?

        The band is read back off the page and compared with the source it was
        derived from — the same check a reader performs by looking.  Words
        only: the maths comes back in a different alphabet (`\\sigma` against
        `\u03c3`) and would fail a comparison it has no business failing, so a
        clause with too little prose to judge is passed rather than guessed at.
        """
        words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", _detex(want))}
        if len(words) < 4 or not self._text():
            return True
        page = self._text()[rect["page"] - 1]
        got = page.get_text("text", clip=(rect["x"], rect["top"],
                                          rect["x"] + rect["w"],
                                          rect["bottom"]))
        seen = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", got)}
        return len(words & seen) / len(words) >= 0.34

    def rect(self, name: str, begin: int, end: int, lookahead: int = 4,
             after: tuple[int, float] | None = None) -> dict | None:
        """Rectangle spanning the environment at source lines [begin, end].

        `after` is a (page, y) floor for the top edge: boxes at or above it are
        strays from earlier material, not this block's own.  Only anchors pass
        it — a statement begins at a `\\begin{...}`, which is never ambiguous.
        """
        top = self.start(name, begin, after)
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
        #
        # The `\end{...}` line is not a body line: TeX credits it with whatever
        # follows the environment as readily as with what precedes it, so
        # counting it would drag the band over the next paragraph.
        limit = top.page + 1
        body = [b for ln in range(begin, end) for b in self._at(name, ln)
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

        # `floor` settles the bottom edge and nothing else.  It is a box from
        # *outside* the environment — the first thing typeset after it — so its
        # horizontal extent describes a different block, and folding it in put
        # that block's indentation into this one's band.
        #
        # The visible symptom was a band that looked type-dependent.  What
        # follows a `theorem`/`lemma`/`proposition`/`corollary` is a `proof`,
        # and amsthm sets that as a trivlist whose `\item[… Proof.]` hangs into
        # the left margin (h:73.75 against the text block's 79.20).  A
        # `definition` is followed by an ordinary paragraph and kept 79.20.  So
        # statements banded 5.45pt further left according to whether they had a
        # proof under them, which reads as a design decision and is not one.
        #
        # The two were also taken independently, `min` of the lefts against
        # `max` of the widths, which is not a union of anything: a block whose
        # floor was further left *and* narrower came out short on the right, so
        # one band in the tracked example missed the right edge every other
        # band lined up on.
        #
        # A band belongs to the statement, so it takes the statement's own
        # measure.
        return self.tighten({
            "page": top.page, "top": round(top.top, 2),
            "x": round(top.x, 2),
            "w": round(top.w, 2),
            "end_page": floor.page, "bottom": round(floor.top, 2),
        })

    # ---- tightening ------------------------------------------------------

    def _text(self):
        """The typeset page's own text layout, which is what sets the band.

        SyncTeX brackets a block; only the page knows where the block's last
        line actually ends.  Without this the bracket is used raw and every
        band runs one line long -- which is why the reader carries a hard
        dependency on PyMuPDF rather than treating it as a nicety.  It stays a
        soft import all the same, because a manifest with approximate geometry
        is worth more than no manifest, and `have_text_layout` is what makes
        the difference visible instead of silent.
        """
        if not hasattr(self, "_doc"):
            mod = _text_module()
            self._doc = mod.open(self.pdf) if mod else None
        return self._doc

    def _lines(self, page_no: int, x0: float, x1: float,
               ceiling: float, floor: float) -> list[tuple]:
        """Text lines of a page whose middle falls inside [ceiling, floor].

        The midpoint is the test because SyncTeX reports a box without its
        ascender, so the head line starts a hair above `ceiling`, while the
        next paragraph's first line starts a hair above `floor`.  One is kept
        and the other rejected, which testing an edge would not manage.
        """
        out = []
        for blk in self._text()[page_no - 1].get_text("dict").get("blocks", []):
            solo = len(blk.get("lines", [])) == 1
            for ln in blk.get("lines", []):
                b = ln["bbox"]
                if b[2] < x0 - 24 or b[0] > x1 + 24:      # a different column
                    continue
                # the folio: a block of one line holding nothing but a number.
                # It sits close enough under the last line of a block ending
                # near the foot of the page to be mistaken for part of it.
                if solo and _FOLIO.fullmatch(
                        "".join(s["text"] for s in ln.get("spans", [])).strip()):
                    continue
                mid = (b[1] + b[3]) / 2
                if ceiling <= mid <= floor:
                    out.append(b)
        return sorted(out, key=lambda b: b[1])

    def tighten(self, rect: dict) -> dict:
        """Pull the edges in to the text actually inside the band.

        SyncTeX brackets the block, it does not measure it: the bottom sits
        wherever the next paragraph starts, one blank line too low.  The
        typeset page knows better, so the bracket is only used to decide which
        lines belong, and their own extent sets the edge.
        """
        if self._text() is None:
            return rect
        x0, x1 = rect["x"], rect["x"] + rect["w"]

        # A bottom taken from the next page does not prove the block reached it:
        # a block ending near the foot of one page is bracketed by the first
        # line of the following one.  If that page holds nothing of ours, the
        # block ended earlier, and drawing it to the page edge would swallow the
        # margin and the folio.
        if rect["end_page"] != rect["page"]:
            if not self._lines(rect["end_page"], x0, x1, 0.0, rect["bottom"]):
                rect["end_page"] = rect["page"]
                page = self._text()[rect["page"] - 1]
                run = self._lines(rect["page"], x0, x1, rect["top"], page.rect.height)
                # with no bracket below, follow the block only while the lines
                # keep coming: the next gap of any size is the end of it
                pitch = max((run[i][1] - run[i - 1][1] for i in range(1, len(run))),
                            default=0)
                pitch = min(pitch, 26.0) or 14.0
                bottom = rect["top"]
                for b in run:
                    if b[1] > bottom + pitch * 1.9:
                        break
                    bottom = max(bottom, b[3])
                rect["bottom"] = round(bottom, 2)
                return rect

        ceiling = rect["top"] if rect["end_page"] == rect["page"] else 0.0
        lines = self._lines(rect["end_page"], x0, x1, ceiling, rect["bottom"])
        if lines:
            # The last member line sets the edge even when its box reaches past
            # the bracket: a display sets a box taller than its neighbours, and
            # a line whose middle is inside the block belongs to it whole.
            rect["bottom"] = round(max(b[3] for b in lines), 2)
        return rect
