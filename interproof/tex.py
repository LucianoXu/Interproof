"""The informal side, parsed as source text.

Every labelled `theorem`/`lemma`/`definition`/… environment with its statement,
the `proof` that follows it, its place in the section tree, its span in the
source, and the labels it cites — from the proof as much as from the statement,
since a proof citing a lemma is what a dependency *is*.

What cites an item is nowhere in the source.  It exists only in the sum of
every other item's `\\Cref`s, so it is inverted here rather than read.

Nothing in this module knows which documents exist: the environments to look
for and the shape of a label come from `Grammar`, and the document a file
belongs to is passed in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, Document, Grammar


@dataclass
class TexItem:
    label: str
    doc: str                 # the Document id this belongs to
    kind: str                # theorem / lemma / section / ...
    title: str = ""
    body: str = ""
    proof: str = ""
    file: str = ""           # relative to the document root — what synctex indexes
    line: int = 0
    end_line: int = 0        # line of the matching \end{...}
    proof_end: int = 0       # line of \end{proof}, when a proof follows
    section: str = ""        # enclosing \section title
    subsection: str = ""
    order: int = 0
    refs: list[str] = field(default_factory=list)       # labels this item cites
    cited_by: list[str] = field(default_factory=list)   # item keys citing it
    rect: dict | None = None                            # synctex box in the PDF
    proof_rect: dict | None = None
    parent: str = ""         # for an anchor, the statement it is a part of
    # A span measured by the marked build: the exact regions it covers, which
    # for a wrapped span is more than one.  `rect` stays the bounding box, so
    # everything that only needs somewhere to scroll keeps working.
    rects: list[dict] | None = None
    tint: int = -1           # which colour distinguishes this part from its siblings


def read_braced(s: str, open_idx: int) -> tuple[str, int]:
    """Read a balanced {...} group starting at s[open_idx] == '{'.
    Returns (inner, index just past the closing brace)."""
    assert s[open_idx] == "{"
    depth, i = 0, open_idx
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1:i], i + 1
        i += 1
    return s[open_idx + 1:], len(s)


def read_bracketed(s: str, open_idx: int) -> tuple[str, int]:
    depth, i = 0, open_idx
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1:i], i + 1
        i += 1
    return s[open_idx + 1:], len(s)


def strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


def clean_title(t: str) -> str:
    """An environment's optional title, as a reader would say it aloud.

    The title is what the viewer's index calls the item, so the markup it
    carries in the source has to come off first — a row reading
    `\\emph{frame} lifting` is a row nobody can scan.
    """
    t = re.sub(r"\\rn\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\(emph|textit|textbf|texttt|textsf|kw|mathsf)\{([^}]*)\}", r"\2", t)
    return t.strip()


ANCHOR_RE = re.compile(
    r"^[ \t]*%+[ \t]*@interproof[ \t]+anchor[ \t]+(?P<path>[A-Za-z0-9][\w\-.:]*)"
    r"(?:[ \t]*=[ \t]*\"(?P<text>[^\"]*)\")?[ \t]*$", re.M)


def anchors_in(text: str) -> list[tuple[int, str, str]]:
    """The `% @interproof anchor <path>` directives, as (line, path, text).

    Read from the source *before* comments are stripped, and stripping keeps
    the newline, so the line numbers these carry are the ones SyncTeX answers
    to.  A directive is a comment: the file compiles for someone who has never
    heard of this tool, which is the whole reason the annotation is not a
    macro.
    """
    return [(text.count("\n", 0, m.start()) + 1, m.group("path"),
             m.group("text") or "")
            for m in ANCHOR_RE.finditer(text)]


def span_pattern(want: str) -> "re.Pattern[str]":
    """A quoted span, matched across source lines.

    Whitespace in the quote matches any whitespace in the source, newlines
    included, because the thing worth naming is often written across lines:
    `\\frac{premises}{conclusion}` puts its two arguments on two of them, and a
    quote that had to fit on one could only ever name half a rule.
    """
    return re.compile(r"\s+".join(re.escape(w) for w in want.split()))


def target_line(lines: list[str], ln: int, want: str) -> int:
    """The source line a directive is about.

    The next line carrying content, or — when the directive quotes text — the
    next line that contains it.  Shared with the marked build, because the two
    must agree on which line a span is on or the marker goes somewhere the
    reader is not looking.  `lines` is the comment-stripped source, so a
    directive never claims another directive.
    """
    if not want:
        for k in range(ln, len(lines)):
            if lines[k].strip():
                return k + 1
        return ln
    text = "\n".join(lines)
    m = span_pattern(want).search(text, sum(len(l) + 1 for l in lines[:ln]))
    return text.count("\n", 0, m.start()) + 1 if m else ln


def parse_file(path: Path, doc: str, rel: str, start_order: int,
               grammar: Grammar) -> list[TexItem]:
    """One LaTeX file's labelled items, in source order."""
    source = path.read_text(encoding="utf-8", errors="replace")
    directives = anchors_in(source)
    raw = strip_comments(source)
    label_re = grammar.label_re
    items: list[TexItem] = []
    cur_sec, cur_sub = "", ""
    order = start_order

    def line_of(idx: int) -> int:
        return raw.count("\n", 0, idx) + 1

    # single pass over section commands and theorem-like environments
    scanner = re.compile(
        r"\\(?P<sec>sub)?section\*?\{|"
        r"\\begin\{(?P<env>" + grammar.env_re + r")\}"
    )
    i = 0
    while True:
        m = scanner.search(raw, i)
        if not m:
            break
        if m.group("env") is None:
            title, end = read_braced(raw, m.end() - 1)
            lbl = ""
            tail = raw[end:end + 200]
            lm = re.match(r"\s*\\label\{([^}]*)\}", tail)
            if lm:
                lbl = lm.group(1)
            title = clean_title(title)
            if m.group("sec"):
                cur_sub = title
            else:
                cur_sec, cur_sub = title, ""
            if lbl:
                order += 1
                items.append(TexItem(
                    label=lbl, doc=doc,
                    kind="subsection" if m.group("sec") else "section",
                    title=title, file=rel, line=line_of(m.start()),
                    # a section command is one line, and its own line is the
                    # honest span: a consumer reading `line`–`end_line` should
                    # not be handed a zero it has to know to special-case
                    end_line=line_of(m.start()),
                    section=cur_sec, subsection="" if not m.group("sec") else "",
                    order=order))
            i = end
            continue

        env = m.group("env")
        close = raw.find("\\end{%s}" % env, m.end())
        if close == -1:
            i = m.end()
            continue
        inner = raw[m.end():close]
        after = close + len("\\end{%s}" % env)

        title = ""
        rest = inner
        om = re.match(r"\s*\[", inner)
        if om:
            title, endb = read_bracketed(inner, inner.index("["))
            rest = inner[endb:]
        lm = re.search(r"\\label\{([^}]*)\}", rest[:300])
        label = lm.group(1) if lm else ""
        if lm:
            rest = rest[:lm.start()] + rest[lm.end():]

        # an immediately following proof environment belongs to this item
        proof, proof_end = "", 0
        pm = re.match(r"\s*\\begin\{%s\}" % re.escape(grammar.proof_environment),
                      raw[after:])
        if pm:
            pstart = after + pm.end()
            pend = raw.find("\\end{%s}" % grammar.proof_environment, pstart)
            if pend != -1:
                proof = raw[pstart:pend]
                proof_end = line_of(pend)

        if label:
            order += 1
            items.append(TexItem(
                label=label, doc=doc, kind=env, title=clean_title(title),
                body=rest.strip(), proof=proof.strip(), file=rel,
                line=line_of(m.start()), end_line=line_of(close),
                proof_end=proof_end, section=cur_sec, subsection=cur_sub,
                order=order,
                refs=sorted({f"{a}:{b}" for a, b in label_re.findall(rest + proof)}),
            ))
        i = after

    items.extend(_anchors(directives, items, doc, rel, raw.split("\n"), order))
    return items


def _anchors(directives: list[tuple[int, str, str]], items: list[TexItem],
             doc: str, rel: str, lines: list[str], order: int) -> list[TexItem]:
    """Turn `% @interproof anchor` directives into items of their own.

    A directive claims **source lines**, which is all this step can honestly
    locate: SyncTeX answers per typeset line, so a part of a statement that
    occupies its own line — a row of an `align`, an `\\item`, a rule in a
    `mathpar` — can be found exactly, and one sharing a line with its
    neighbour cannot.  A directive on the second kind is not wrong, it is
    simply banded as coarsely as the line it sits on.

    The extent runs to the next anchor of the same statement, so an `\\item`
    anchor covers its whole clause rather than the clause's first typeset line.
    """
    out: list[TexItem] = []
    if not directives:
        return out
    owners = [it for it in items if it.end_line > it.line]

    placed = [(target_line(lines, ln, want), path)
              for ln, path, want in directives]
    placed.sort()
    for k, (at, path) in enumerate(placed):
        # The parent is read off the *path*: `def:aeval:arith:lit` is a part of
        # `def:aeval:arith`, which is itself a part of `def:aeval`.  Taking the
        # enclosing environment instead would make every depth a sibling of
        # every other, and the colours that tell three spans of one line apart
        # would be shared out across a whole definition.
        parent = path.rsplit(":", 1)[0]
        # The next anchor that is not *inside* this one.  A part of a part —
        # `def:aeval:arith:lit` under `def:aeval:arith` — must not cut its
        # parent short, or a clause with sub-parts is banded only down to the
        # first of them.
        nxt = next((a for a, q in placed[k + 1:] if not q.startswith(path + ":")), 0)
        stop = nxt - 1 if nxt else 0
        # An anchor also stops at the `\end{...}` that closes something it did
        # not open.  Without this the last part of a list runs to the end of
        # the whole statement and swallows the sentence after `\end{enumerate}`
        # — the band then reaches visibly below the clause it names.
        depth = 0
        for j in range(at, len(lines)):
            body = lines[j].strip()
            if body.startswith("\\begin{"):
                depth += 1
            elif body.startswith("\\end{"):
                if depth == 0:
                    stop = min(stop or j, j)
                    break
                depth -= 1
        # the statement it is inside, innermost first — for its extent and its
        # place in the index, which are facts about where it sits, not about
        # what it is a part of
        own, best = None, None
        for it in owners:
            if it.line <= at <= it.end_line and (best is None
                                                 or it.end_line - it.line < best):
                own, best = it, it.end_line - it.line
        if own is not None:
            stop = min(stop or own.end_line - 1, own.end_line - 1)
        order += 1
        out.append(TexItem(
            label=path, doc=doc, kind="anchor", file=rel,
            line=at, end_line=max(stop, at), parent=parent,
            # an anchor reads as a part of its statement, so it sorts with it
            # rather than after everything else the file happens to hold
            order=own.order if own is not None else order,
            section=own.section if own is not None else "",
            subsection=own.subsection if own is not None else "",
            title=path.rsplit(":", 1)[-1]))
    return out


def parse_document(doc: Document, grammar: Grammar,
                   start_order: int = 0) -> tuple[dict[str, TexItem], int]:
    """Every labelled item of one document, keyed `<doc id>::<label>`."""
    items: dict[str, TexItem] = {}
    order = start_order
    for f in doc.source_files():
        rel = str(f.relative_to(doc.root))          # what synctex indexes it as
        got = parse_file(f, doc.id, rel, order, grammar)
        order = got[-1].order if got else order
        for it in got:
            items[f"{doc.id}::{it.label}"] = it
    return items, order


def parse_all(cfg: Config) -> dict[str, TexItem]:
    items: dict[str, TexItem] = {}
    order = 0
    for d in cfg.documents:
        got, order = parse_document(d, cfg.grammar, order)
        items.update(got)
    return items


def attach_cited_by(items: dict[str, TexItem], docs: list[Document]) -> int:
    """Invert the papers' cross-references.

    An item already knows what it cites; what cites *it* is the direction a
    reader coming from the formal side asks for first, and it exists nowhere in
    the source — only in the sum of every other item's `\\Cref`s.
    """
    edges = 0
    for key, it in items.items():
        for lbl in it.refs:
            hit = next((f"{d}::{lbl}" for d in (it.doc, *(x.id for x in docs))
                        if f"{d}::{lbl}" in items), None)
            if hit and hit != key and key not in items[hit].cited_by:
                items[hit].cited_by.append(key)
                edges += 1
    return edges
