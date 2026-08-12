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


def parse_file(path: Path, doc: str, rel: str, start_order: int,
               grammar: Grammar) -> list[TexItem]:
    """One LaTeX file's labelled items, in source order."""
    raw = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
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
    return items


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
