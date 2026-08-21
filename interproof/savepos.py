"""Where a marked span of LaTeX lands on the page, to the point.

SyncTeX answers per typeset line.  That is enough for a statement, and enough
for a part of one that occupies its own line — a row of an `align`, an
`\\item` — which is what `tex.anchors_in` and the ordinary `rect` path handle.
It is not enough for three equations separated by `\\qquad` inside one `\\[…\\]`:
they share a typeset line, and SyncTeX returns *the same full box* for every
source line of the display.  Measured, on the tracked example: seven source
lines, one identical rectangle.

So the position is asked of TeX itself.  `\\pdfsavepos` records where a point
ended up on the page, and a deferred `\\write` puts it in the `.aux` at shipout,
when the coordinate is known.  Bracketing a span with two of them gives its
start and its end exactly — inside math, inside an `align` cell, inside an
`\\inferrule` premise.

**The source on disk is never touched.**  A directive is a LaTeX comment, so
the paper compiles for a co-author who has never heard of this tool, on arXiv,
in Overleaf, with no package to install.  The markers go into a *private mirror*
of the project under the build directory, and that copy is compiled for its
coordinates alone; the PDF the reader is shown is still the clean one.  The two
are the same document — checked, on the tracked example, at 99 words in
identical positions — which is the property that makes this honest rather than
merely clever.

What this costs, stated rather than hidden: a second full LaTeX run whenever a
document carries a quoted anchor.  It buys the only sub-line geometry there is,
and when it fails the build says so and falls back to the line.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import Config, Document
from .tex import anchors_in, span_pattern, strip_comments, target_line

# One `\pdfsavepos` and one *deferred* `\write`.  Deferred is the whole trick:
# a non-immediate write is a whatsit executed at shipout, by which time
# `\pdflastxpos` has been set by the savepos whatsit beside it.  `\ipposition`
# is a no-op so that reading the .aux back on the next run is harmless.
MACROS = (
    r"\makeatletter"
    r"\providecommand\ipposition[4]{}"
    # no `%` anywhere in here: the whole thing is appended to the
    # `\documentclass` line, so a comment character would swallow the rest of
    # the definition and the run dies in `\@argdef` with nothing to point at
    r"\newcommand\ipmark[1]{\pdfsavepos\write\@auxout{"
    r"\string\ipposition{#1}{\the\pdflastxpos}{\the\pdflastypos}{\the\count0}}}"
    r"\makeatother"
)

POS_RE = re.compile(r"\\ipposition\s*\{([^}]*)\}\{(-?\d+)\}\{(-?\d+)\}\{(\d+)\}")
DOCCLASS_RE = re.compile(r"(\\documentclass\s*(?:\[[^\]]*\])?\s*\{[^}]*\})")
SP = 65536.0                      # scaled points in a point


def balanced(s: str) -> bool:
    """Whether a quoted span opens exactly the groups it closes.

    A span is wrapped in `\\ipmark{…}` on both sides, so it has to be a thing
    TeX can see as one: `\\frac{a}{b}` can be marked, and the `\\frac{a}` half
    of it cannot.  An unescaped brace is what counts; `\\{` is a character.
    """
    depth, i = 0, 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


class SaveposError(Exception):
    """The marked build could not be made or read.  Never fatal."""


def quoted_anchors(doc: Document) -> list[tuple[Path, int, str, str]]:
    """Every `% @interproof anchor <path> = "text"` of one document.

    Only the quoted ones: an anchor with no text claims a whole source line,
    which SyncTeX already locates, and marking it would buy nothing.
    """
    out: list[tuple[Path, int, str, str]] = []
    for f in {doc.main_path, *doc.source_files()}:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = strip_comments(source).split("\n")
        for ln, path, want in anchors_in(source):
            if not want:
                continue
            at = target_line(lines, ln, want)
            out.append((f, at, path, want))
    return sorted(out, key=lambda r: (str(r[0]), r[1]))


def _mirror(cfg: Config, doc: Document) -> tuple[Path, Path]:
    """A private copy of the project, and where this document sits in it.

    The whole project rather than the document's own root: a shared preamble
    reached by `../common` is a normal way to lay a paper out, and a mirror
    that broke it would fail on exactly the projects that need this most.
    """
    mirror = doc.build_dir / "_savepos"
    skip = {".git", ".interproof", "_savepos", "__pycache__",
            cfg.build_dir.name, cfg.out_dir.name}
    if mirror.exists():
        shutil.rmtree(mirror, ignore_errors=True)
    shutil.copytree(cfg.root, mirror / "src",
                    ignore=lambda d, names: [n for n in names if n in skip],
                    dirs_exist_ok=True)
    return mirror, (mirror / "src" / os.path.relpath(doc.root, cfg.root)).resolve()


def _patch(root: Path, doc_root: Path, main: Path,
           marks: list[tuple[Path, int, str, str]], cfg_root: Path) -> int:
    """Wrap each quoted span in `\\ipmark`, in the mirror only.

    Line counts are preserved throughout — the replacement is inside the line
    it was found on, and the preamble goes on the `\\documentclass` line — so
    the mirror stays line-for-line the original.  Nothing here depends on that
    today, since the mirror is read for coordinates and never for SyncTeX, but
    a mirror that silently renumbered would be a trap for whoever wires the two
    together later.
    """
    done = 0
    unbalanced: list[str] = []
    by_file: dict[Path, list[tuple[int, str, str]]] = {}
    for f, at, path, want in marks:
        by_file.setdefault(f, []).append((at, path, want))

    for f, items in by_file.items():
        target = root / "src" / os.path.relpath(f, cfg_root)
        if not target.exists():
            continue
        source = target.read_text(encoding="utf-8", errors="replace")
        bad: list[str] = []
        # Offsets are taken against the *unpatched* text and spliced from the
        # right.  Patching left to right would let a later quote match inside a
        # marker already inserted — `\ipmark{def:aexp:lit(}` contains an `x`,
        # and a production quoted as `x` would be found there instead of in the
        # grammar.  Matching is over the whole file rather than a line, because
        # a `\frac{premises}{conclusion}` puts its two arguments on two lines
        # and half a rule is not the thing anybody wanted to name.
        spans: list[tuple[int, int, str]] = []
        for at, path, want in items:
            if not balanced(want):
                # A quote that opens a group it does not close cannot be
                # wrapped: the marker lands between `\frac`'s arguments and TeX
                # stops on an extra `}`.  One bad quote fails the whole run and
                # takes every other span with it, so it is refused here rather
                # than discovered in a log.
                bad.append(path)
                continue
            frm = sum(len(l) + 1 for l in source.split("\n")[:max(at - 1, 0)])
            hits = list(span_pattern(want).finditer(source, frm))
            if not hits:
                continue
            spans.append((hits[0].start(), hits[0].end(), path))

        for start, end, path in sorted(spans, reverse=True):
            # A span that opens a paragraph puts the opening whatsit in
            # vertical mode, where the point it records sits on no typeset
            # line and the span is lost.  Entering horizontal mode first fixes
            # exactly that case, and the guard keeps it out of math and of
            # paragraphs already begun, where \leavevmode is not always legal.
            source = (source[:start] + r"\ifvmode\leavevmode\fi\ipmark{%s(}" % path
                      + source[start:end] + r"\ipmark{%s)}" % path
                      + source[end:])
            done += 1
        target.write_text(source, encoding="utf-8")
        if bad:
            unbalanced.extend(bad)

    head = main.read_text(encoding="utf-8", errors="replace")
    # The sentinel is the *definition*, not any use of it: a single-file
    # document carries its freshly wrapped spans in this very file, and asking
    # for `\ipmark` would find them and skip the injection they need.
    if r"\providecommand\ipposition" not in head:
        patched, n = DOCCLASS_RE.subn(lambda m: m.group(1) + MACROS, head, count=1)
        if not n:
            raise SaveposError(f"no \\documentclass in {main.name}")
        main.write_text(patched, encoding="utf-8")
    if unbalanced:
        raise SaveposError(
            "unbalanced quoted span(s): " + ", ".join(unbalanced)
            + " — a span must open exactly the braces it closes")
    return done


def _compile(doc: Document, mirror_root: Path, main_rel: str) -> Path:
    outdir = mirror_root.parent / "out"
    outdir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **doc.env}
    cmd = [*doc.latexmk, "-outdir=" + os.path.relpath(outdir, mirror_root), main_rel]
    # stdin closed for the same reason as the main compile: a TeX prompt read
    # from a live terminal is a build hung forever, not a failed one
    r = subprocess.run(cmd, cwd=mirror_root, env=env, capture_output=True,
                       stdin=subprocess.DEVNULL)
    aux = outdir / (Path(main_rel).stem + ".aux")
    if not aux.exists():
        raise SaveposError(
            f"the marked copy did not compile\n"
            + r.stdout.decode("utf-8", "replace")[-1200:])
    return aux


def _points(aux: Path) -> dict[str, tuple[float, float, int]]:
    """`name -> (x, y-from-the-bottom, page)`, in points."""
    text = aux.read_text(encoding="utf-8", errors="replace")
    return {m.group(1): (int(m.group(2)) / SP, int(m.group(3)) / SP,
                         int(m.group(4)))
            for m in POS_RE.finditer(text)}


def _lines_of(pdf, page: int) -> list[tuple[float, float, float, float]]:
    """Every typeset line's bbox on a page, top-origin, in reading order."""
    out = []
    for b in pdf[page - 1].get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            out.append(tuple(l["bbox"]))
    return sorted(out, key=lambda b: (b[1], b[0]))


def _bars(pdf, page: int) -> list[tuple[float, float, float]]:
    """The horizontal rules on a page, as (y, x0, x1).

    A fraction bar is drawn, not typeset, so it is in the drawings rather than
    in the text — and it is the one thing on the page that says two rows are
    the two halves of one rule.
    """
    out = []
    for d in pdf[page - 1].get_drawings():
        r = d["rect"]
        if r.height < 2.5 and r.width > 8:
            out.append((r.y0, r.x0, r.x1))
    return out


def _grow(lines, bars, band: tuple[float, float], x0: float, x1: float
          ) -> tuple[float, float]:
    """Take in the rows a two-dimensional span also covers.

    `\\pdfsavepos` marks a point on one baseline, and an inference rule is not
    on one baseline: `\\frac` sets its premises above its conclusion, so a band
    measured from the baseline alone covers the half below the line and stops.

    A row is absorbed when it lies *within* the span horizontally and a
    **fraction bar** separates it from what is already banded.  The bar is the
    exact criterion and a gap is not: on the tracked example a rule's own two
    rows are 3.8pt apart and two neighbouring displays are 5.7pt apart, which
    no threshold separates safely — tuned to take the first it also took the
    second, and `whileTrue` grew upwards through the `ite` rule above it.
    Containment is still required, so a paragraph, whose lines run the width of
    the text block, is never inside a span and never absorbed.
    """
    top, bot = band
    changed = True
    while changed:
        changed = False
        for (lx0, ly0, lx1, ly1) in lines:
            if lx0 < x0 - 2 or lx1 > x1 + 2:
                continue                       # not inside the span
            def barred(a: float, b: float) -> bool:
                lo, hi = min(a, b) - 2.5, max(a, b) + 2.5
                return any(lo <= by <= hi and bx1 > x0 and bx0 < x1
                           for by, bx0, bx1 in bars)
            # adjacent *and* barred.  The bar alone is not enough: asked over
            # a wide window it finds some other rule's bar and the band walks
            # up the page.  Adjacency alone is not enough either — that is the
            # 3.8-against-5.7 no threshold separates.  Together they are exact.
            h = max(ly1 - ly0, 1.0)
            if ly1 > bot and 0 <= ly0 - bot < h * 1.5 and barred(bot, ly0):
                bot = ly1; changed = True
            if ly0 < top and 0 <= top - ly1 < h * 1.5 and barred(top, ly1):
                top = ly0; changed = True
    return top, bot


def _band(lines, x: float, baseline: float) -> tuple[float, float] | None:
    """The typeset line a baseline sits on, as (top, bottom).

    `\\pdfsavepos` gives a point on the baseline and says nothing about height,
    so the height comes from the line the point is in — which is the only thing
    that knows how tall the material actually set.  The baseline sits above the
    line's bottom, so containment is asked with a little slack rather than
    exactly.
    """
    best, near, gap = None, None, 1e9
    for (x0, y0, x1, y1) in lines:
        if not (y0 - 1.5 <= baseline <= y1 + 1.5):
            continue
        h = y1 - y0
        if x0 - 3 <= x <= x1 + 3:
            if best is None or h < best[1] - best[0]:
                best = (y0, y1)
        # A mark at the left edge of a `\frac` lands in the white space beside
        # the conclusion, which is centred and narrower than the rule: no line
        # contains the point, and requiring containment dropped the span
        # entirely.  The row is what is wanted, so the nearest one on the
        # baseline answers when nothing holds the point.
        d = max(x0 - x, x - x1, 0.0)
        if d < gap:
            near, gap = (y0, y1), d
    return best or (near if gap < 90 else None)


def rects_for(pdf_path: Path, points: dict[str, tuple[float, float, int]],
              paths: list[str]) -> dict[str, list[dict]]:
    """Turn bracketing points into the rectangles a reader can be shown.

    A span that does not wrap is one rectangle from the opening mark to the
    closing one.  A span that wraps is three regions in the general case — the
    tail of its first line, whole lines between, the head of its last — and the
    edges of those come from the typeset lines themselves, because the text
    block's measure is a fact about the page and not about the span.
    """
    try:
        import pymupdf                                    # noqa: F401
    except ImportError:                                   # pragma: no cover
        try:
            import fitz as pymupdf                        # noqa: F401
        except ImportError:
            raise SaveposError("PyMuPDF is needed to measure a marked span")

    out: dict[str, list[dict]] = {}
    with pymupdf.open(pdf_path) as pdf:
        cache: dict[int, list] = {}
        barcache: dict[int, list] = {}
        heights = {n + 1: pdf[n].rect.height for n in range(pdf.page_count)}

        for path in paths:
            a, b = points.get(path + "("), points.get(path + ")")
            if not a or not b:
                continue
            (xa, ya, pa), (xb, yb, pb) = a, b
            if pa not in heights or pb not in heights:
                continue
            top_a = heights[pa] - ya
            top_b = heights[pb] - yb
            for p in (pa, pb):
                cache.setdefault(p, _lines_of(pdf, p))

            band_a = _band(cache[pa], xa, top_a)
            band_b = _band(cache[pb], xb, top_b)
            if band_a is None or band_b is None:
                continue

            if pa == pb and abs(top_a - top_b) < 0.75:     # one baseline
                lo, hi = min(xa, xb), max(xa, xb)
                grown = _grow(cache[pa], barcache.setdefault(pa, _bars(pdf, pa)), band_a, lo, hi)
                out[path] = [{"page": pa, "top": round(grown[0], 2),
                              "bottom": round(grown[1], 2),
                              "x": round(lo, 2), "w": round(hi - lo, 2)}]
                continue

            # wrapped: tail of the first line, the lines between, head of the last
            rs: list[dict] = []
            first = [l for l in cache[pa] if abs(l[1] - band_a[0]) < 0.75]
            right = max((l[2] for l in first), default=xa)
            rs.append({"page": pa, "top": round(band_a[0], 2),
                       "bottom": round(band_a[1], 2), "x": round(xa, 2),
                       "w": round(max(right - xa, 0), 2)})
            for p in range(pa, pb + 1):
                for (x0, y0, x1, y1) in cache.setdefault(p, _lines_of(pdf, p)):
                    after = (p > pa) or (y0 > band_a[0] + 0.75)
                    before = (p < pb) or (y0 < band_b[0] - 0.75)
                    if after and before:
                        rs.append({"page": p, "top": round(y0, 2),
                                   "bottom": round(y1, 2), "x": round(x0, 2),
                                   "w": round(x1 - x0, 2)})
            last = [l for l in cache[pb] if abs(l[1] - band_b[0]) < 0.75]
            left = min((l[0] for l in last), default=xb)
            rs.append({"page": pb, "top": round(band_b[0], 2),
                       "bottom": round(band_b[1], 2), "x": round(left, 2),
                       "w": round(max(xb - left, 0), 2)})
            out[path] = rs
    return out


def locate(cfg: Config, doc: Document, *, quiet: bool = False
           ) -> tuple[dict[str, list[dict]], str]:
    """Every quoted anchor of one document, as rectangles.

    Returns `(path -> rects, note)`.  The note is empty on success and says
    what went wrong otherwise; nothing here raises out, because a span that
    could not be measured is a coarser reader and never a failed build.
    """
    marks = quoted_anchors(doc)
    if not marks:
        return {}, ""
    try:
        mirror, doc_root = _mirror(cfg, doc)
        main = doc_root / doc.main
        n = _patch(mirror, doc_root, main, marks, cfg.root)
        if not n:
            return {}, "no quoted anchor matched its line in the source"
        aux = _compile(doc, doc_root, doc.main)
        pts = _points(aux)
        rects = rects_for(doc.pdf, pts, [m[2] for m in marks])
        missing = [m[2] for m in marks if m[2] not in rects]
        note = (f"{len(missing)} of {len(marks)} spans not located "
                f"({', '.join(missing[:3])})" if missing else "")
        return rects, note
    except SaveposError as e:
        return {}, str(e).split("\n")[0]
    except Exception as e:                                # pragma: no cover
        return {}, f"{type(e).__name__}: {e}"
