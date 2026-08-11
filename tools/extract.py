#!/usr/bin/env python3
"""
Interproof extractor — build the informal <-> Lean correspondence manifest.

Data model borrowed from `span` (a checked label <-> declaration mapping),
but the mapping is *harvested from the Lean side*, where this project already
records it: docstrings carry `P3:<label>` and `note, <label>` citations.

No Lean build required: both sides are parsed as source text.

Usage:  python3 tools/extract.py           # writes site/manifest.json
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
OUT = ROOT / "site" / "manifest.json"

ENV_KINDS = [
    "theorem", "lemma", "definition", "proposition", "corollary",
    "remark", "example", "conjecture", "fact", "assumption",
]
LABEL_RE = re.compile(r"\b(thm|lem|def|prop|cor|rem|sec|sub|app|fig|tab|eq)"
                      r":([A-Za-z0-9][A-Za-z0-9\-_.]*)")

# a citation that names the item by title: "Def. procedure declaration",
# "Definition (frame lifting)", "Thm. footprint soundness"
TITLE_CITE = (r"\b(Def\.|Definition|Lem\.|Lemma|Thm\.|Theorem|Prop\.|Proposition"
              r"|Cor\.|Corollary|Rem\.|Remark)\s*\(?\s*(%s)\s*\)?")
ENV_OF_ABBREV = {
    "def": "definition", "definition": "definition",
    "lem": "lemma", "lemma": "lemma",
    "thm": "theorem", "theorem": "theorem",
    "prop": "proposition", "proposition": "proposition",
    "cor": "corollary", "corollary": "corollary",
    "rem": "remark", "remark": "remark",
}


# --------------------------------------------------------------------------
# LaTeX side
# --------------------------------------------------------------------------

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


def strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


@dataclass
class TexItem:
    label: str
    doc: str                 # "P3" | "note"
    kind: str                # theorem / lemma / section / ...
    title: str = ""
    body: str = ""
    proof: str = ""
    file: str = ""
    line: int = 0
    end_line: int = 0        # line of the matching \end{...}
    proof_end: int = 0       # line of \end{proof}, when a proof follows
    section: str = ""        # enclosing \section title
    subsection: str = ""
    order: int = 0
    refs: list[str] = field(default_factory=list)   # labels this item cites
    cited_by: list[str] = field(default_factory=list)   # item keys citing it
    rect: dict | None = None                        # synctex box in the PDF
    proof_rect: dict | None = None


def parse_tex_file(path: Path, doc: str, rel: str, start_order: int) -> list[TexItem]:
    raw = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    items: list[TexItem] = []
    cur_sec, cur_sub = "", ""
    order = start_order

    def line_of(idx: int) -> int:
        return raw.count("\n", 0, idx) + 1

    # single pass over section commands and theorem-like environments
    env_alt = "|".join(ENV_KINDS)
    scanner = re.compile(
        r"\\(?P<sec>sub)?section\*?\{|"
        r"\\begin\{(?P<env>" + env_alt + r")\}"
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
        pm = re.match(r"\s*\\begin\{proof\}", raw[after:])
        if pm:
            pstart = after + pm.end()
            pend = raw.find("\\end{proof}", pstart)
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
                refs=sorted({f"{a}:{b}" for a, b in LABEL_RE.findall(rest + proof)}),
            ))
        i = after
    return items


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


def clean_title(t: str) -> str:
    t = re.sub(r"\\rn\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\(emph|textit|textbf|texttt|textsf|kw|mathsf)\{([^}]*)\}", r"\2", t)
    return t.strip()


# --------------------------------------------------------------------------
# Lean side
# --------------------------------------------------------------------------

DECL_RE = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?"
    r"(?:private\s+|protected\s+|noncomputable\s+|partial\s+|unsafe\s+|scoped\s+)*"
    r"(theorem|lemma|def|abbrev|structure|inductive|instance|class|opaque|example)"
    r"\s+([^\s:({\[]+)")
BREAK_RE = re.compile(r"^(namespace|end|section|variable|open|universe|import|"
                      r"attribute|set_option|local\s|macro|notation|syntax|"
                      r"declare_syntax_cat|deriving)\b")


@dataclass
class LeanDecl:
    name: str
    kind: str
    file: str
    line: int
    end_line: int
    doc_line: int = 0        # first line of the `/-- ... -/` docstring, if any
    doc: str = ""
    section: str = ""
    refs: list[dict] = field(default_factory=list)
    has_sorry: bool = False
    uses: list[str] = field(default_factory=list)   # "File::name" it names in code


def comment_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of Lean comments (block and line)."""
    spans, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("/-", i):
            depth, j = 0, i
            while j < n:
                if text.startswith("/-", j):
                    depth += 1
                    j += 2
                elif text.startswith("-/", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                else:
                    j += 1
            spans.append((i, j))
            i = j
        elif text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            spans.append((i, j))
            i = j
        elif text[i] == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            i = j
        else:
            i += 1
    return spans


def parse_lean_file(
    path: Path,
    name: str,
    titles: dict[str, list[tuple[str, str, str]]] | None = None,
) -> tuple[list[LeanDecl], str, list[dict]]:
    """Parse one Lean module.  `name` is how the module is referred to
    everywhere downstream — its path under the Lean root, extension dropped, so
    two subdirectories may hold the same file name.  `titles` maps an item title
    to the `(kind, doc, label)` triples that carry it, for title-form citations."""
    titles = titles or {}
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    # line -> True if inside a comment (for reference harvesting)
    spans = comment_spans(text)
    in_comment = [False] * (len(text) + 1)
    for a, b in spans:
        for k in range(a, min(b, len(text))):
            in_comment[k] = True

    def line_of(idx: int) -> int:
        return text.count("\n", 0, idx) + 1

    # every comment block, by the line it ends on and the line it starts on,
    # with whether it is a `/-- ... -/` docstring.  Both the docstring above a
    # declaration and the extent of a citation in module prose are read off it.
    block_end: dict[int, tuple[int, bool]] = {}
    block_at: list[tuple[int, int, int]] = []      # (start char, first line, last line)
    for a, b in spans:
        last = line_of(max(a, min(b, len(text)) - 1))
        block_end[last] = (line_of(a), text.startswith("/--", a))
        block_at.append((a, line_of(a), last))

    def block_of(idx: int) -> tuple[int, int]:
        """The comment block a citation sits in — the paragraph of prose that
        does the citing, which is the whole extent of a module-level citation
        and the only honest one: the lines between two citing blocks cite
        nothing."""
        for a, first, last in block_at:
            if a <= idx and first <= line_of(idx) <= last:
                return first, last
        return line_of(idx), line_of(idx)

    # module docstring: first /-! ... -/
    module_doc = ""
    md = re.search(r"/-!(.*?)-/", text, re.S)
    if md:
        module_doc = md.group(1).strip()

    # section headers from /-! ## ... -/
    sections: list[tuple[int, str]] = []
    for m in re.finditer(r"/-!\s*#+\s*([^\n]*?)\s*-?/?\s*(?:\n|-/)", text):
        sections.append((line_of(m.start()), m.group(1).strip().rstrip("-/").strip()))

    # declaration starts — prose inside a docstring can begin a line with
    # "theorem ...", so a match only counts outside comment spans
    line_start_off = [0]
    for ln in lines:
        line_start_off.append(line_start_off[-1] + len(ln) + 1)
    starts: list[tuple[int, str, str]] = []      # (line_no, kind, name)
    for idx, ln in enumerate(lines, start=1):
        m = DECL_RE.match(ln)
        if m and not in_comment[min(line_start_off[idx - 1], len(text))]:
            starts.append((idx, m.group(1), m.group(2)))

    # boundaries: next declaration, or a top-level structural keyword, or /-! block,
    # or the `/-- ... -/` docstring that introduces the next declaration — without
    # that last one a slice runs on into the prose written about its successor
    boundaries = sorted(
        [s[0] for s in starts] +
        [idx for idx, ln in enumerate(lines, start=1) if BREAK_RE.match(ln)] +
        [ln_no for ln_no, _ in sections] +
        [line_of(a) for a, _ in spans if text.startswith("/--", a)] +
        [len(lines) + 1]
    )

    decls: list[LeanDecl] = []
    for (ln_no, kind, dname) in starts:
        nxt = next((b for b in boundaries if b > ln_no), len(lines) + 1)
        end = nxt - 1
        while end > ln_no and not lines[end - 1].strip():
            end -= 1
        # The preceding docstring, if the block above the declaration is one.
        # Asked of the comment spans rather than of the line text: a line
        # ending in `-/` says only that *some* comment ends there, and a
        # `/-! ## ... -/` section header ends that way too.  Reading it as a
        # docstring and then searching back for the `/--` that must have opened
        # it walks into the previous declaration's docstring, and the band
        # starts forty lines early with a whole declaration inside it.
        doc, doc_line = "", 0
        j = ln_no - 2
        while j >= 0 and (lines[j].strip().startswith("@[") or not lines[j].strip()):
            j -= 1
        above = block_end.get(j + 1)
        if above and above[1]:
            doc_line = above[0]
            doc = "\n".join(lines[doc_line - 1:j + 1])
            doc = re.sub(r"^\s*/--", "", doc).strip()
            doc = re.sub(r"-/\s*$", "", doc).strip()
        sec = ""
        for sl, st in sections:
            if sl < ln_no:
                sec = st
        code = "\n".join(lines[ln_no - 1:end])
        decls.append(LeanDecl(
            name=dname, kind=kind, file=name, line=ln_no, end_line=end,
            doc_line=doc_line, doc=doc, section=sec,
            has_sorry=bool(re.search(r"\bsorry\b", code)),
        ))

    # harvest references from comment text only
    def mkref(start: int, stop: int, label: str, via: str) -> dict:
        lno = line_of(start)
        # which document? nearest marker before the citation
        doc_hint = ""
        for mm in MARKER_RE.finditer(text[max(0, start - 90):start]):
            doc_hint = MARKER_OF[mm.lastgroup]
        # A citation almost always sits in the `/-- ... -/` docstring *above* the
        # declaration it is about, so the docstring counts as part of it.  Only
        # `/-! ... -/` module prose, which no declaration owns, stays at module
        # level.
        owner = None
        for d in decls:
            if (d.doc_line or d.line) <= lno <= d.end_line:
                owner = d.name
                break
        blk = block_of(start)
        return {"label": label, "line": lno, "doc_hint": doc_hint, "decl": owner,
                "via": via, "file": name,
                # the prose block doing the citing, for when no declaration owns it
                "block_from": blk[0], "block_to": blk[1],
                "context": text[max(0, start - 220):stop + 220].replace("\n", " ").strip()}

    refs: list[dict] = []
    seen: set[tuple[int, str]] = set()            # (line, label), first form wins
    for m in LABEL_RE.finditer(text):
        if not in_comment[m.start()]:
            continue
        r = mkref(m.start(), m.end(), f"{m.group(1)}:{m.group(2)}", "label")
        seen.add((r["line"], r["label"]))
        refs.append(r)

    # The Lean sources cite the papers three ways.  `def:proc-decl` is the
    # canonical one; the other two name the item by its *title* — "Def.
    # procedure declaration", "Definition (frame lifting)" — and are just as
    # much a citation.  Reading only the first form leaves declarations that
    # plainly state their counterpart looking uncovered.
    for title, cands in titles.items():
        for m in re.finditer(TITLE_CITE % re.escape(title), text, re.I):
            if not in_comment[m.start()]:
                continue
            kind = ENV_OF_ABBREV.get(m.group(1).lower().rstrip("."))
            hit = [c for c in cands if c[0] == kind]   # "Lemma (locality)" is not def:local
            if not hit:
                continue
            r = mkref(m.start(), m.end(), "", "title")
            if len(hit) > 1 and r["doc_hint"]:        # same title in both documents
                hit = [c for c in hit if c[1] == r["doc_hint"]] or hit
            for _, doc, label in hit:
                if (r["line"], label) in seen:
                    continue
                seen.add((r["line"], label))
                refs.append({**r, "label": label, "doc_hint": doc})
    return decls, module_doc, refs


# a dotted Lean identifier, as it is written in code
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*")


def declaration_uses(files: list[dict]) -> int:
    """Which declarations each declaration names in its own code.

    The other half of the reference structure: the paper's items cite each
    other by `\\Cref`, and the Lean declarations cite each other by *using*
    each other.  Both are read here, and the viewer shows each in both
    directions — what a thing rests on, and what rests on it.

    This is a name match over source text, in the same spirit as the rest of
    this file: it sees a declaration named in code and nothing else.  It cannot
    see a lemma a `simp` set applies for you, and a local binder that happens to
    share a declaration's name reads as a use.  Comments are excluded — a name
    discussed in a docstring is prose, and the citations that matter there are
    already harvested as paper links.
    """
    table: dict[str, list[tuple[str, str]]] = {}      # name -> [(file, key)]
    for f in files:
        for d in f["decls"]:
            table.setdefault(d["name"], []).append((f["name"], f["name"] + "::" + d["name"]))

    edges = 0
    for f in files:
        text = f["text"]
        lines = text.split("\n")
        inside = bytearray(len(text) + 1)
        for a, b in comment_spans(text):
            for k in range(a, min(b, len(text))):
                inside[k] = 1
        off = [0]
        for ln in lines:
            off.append(off[-1] + len(ln) + 1)

        for d in f["decls"]:
            a, b = off[d["line"] - 1], off[min(d["end_line"], len(lines))]
            hits: set[str] = set()
            for m in IDENT_RE.finditer(text, a, b):
                if inside[m.start()]:
                    continue
                cands = table.get(m.group(0))
                if not cands or m.group(0) == d["name"]:
                    continue
                # a name is almost always unique in the corpus; when it is not,
                # the one in this module wins and a genuine tie is dropped
                # rather than guessed at
                same = [c for c in cands if c[0] == f["name"]]
                if len(same) == 1:
                    hits.add(same[0][1])
                elif len(cands) == 1:
                    hits.add(cands[0][1])
            d["uses"] = sorted(hits)
            edges += len(hits)
    return edges


IMPORT_RE = re.compile(r"^import\s+([A-Za-z0-9_.]+)", re.M)


def import_order(files: list[dict]) -> list[dict]:
    """Modules in dependency order: each one follows everything it imports.

    This is the formalization's own order — what `PQCPlus.lean` lists, and the
    order the modules are meant to be read in.  The file system's alphabetical
    order is an accident, and it puts `Universality` fourteenth and `Ambient`,
    which everything rests on, first only by luck of the letter A.

    Which imports are internal is not assumed: an import names a module by its
    Lean path, and the root prefix (`PQCPlus.`) is whatever prefix the imports
    that do resolve agree on, so nothing here knows the package's name.
    """
    dotted = {f["name"].replace("/", "."): f["name"] for f in files}
    raw = {f["name"]: IMPORT_RE.findall(f["text"]) for f in files}

    prefixes: dict[str, int] = {}
    for targets in raw.values():
        for t in targets:
            for m in dotted:
                if t == m or t.endswith("." + m):
                    prefixes[t[:len(t) - len(m)]] = prefixes.get(t[:len(t) - len(m)], 0) + 1
    root = min(prefixes, key=lambda p: (-prefixes[p], len(p))) if prefixes else ""

    deps = {f["name"]: [dotted[t[len(root):]] for t in raw[f["name"]]
                        if t.startswith(root) and t[len(root):] in dotted]
            for f in files}
    for f in files:
        f["imports"] = deps[f["name"]]

    # depth = longest import chain reaching the module; an edge always raises
    # it, so ordering by depth is a topological order.  Cycles cannot occur in
    # Lean imports, but a guard keeps a malformed tree from recursing forever.
    depth: dict[str, int] = {}

    def d(name: str, seen: frozenset[str]) -> int:
        if name in depth:
            return depth[name]
        if name in seen:
            return 0
        got = max((d(p, seen | {name}) + 1 for p in deps[name]), default=0)
        depth[name] = got
        return got

    for f in files:
        d(f["name"], frozenset())
    return sorted(files, key=lambda f: (depth[f["name"]], f["name"]))


# --------------------------------------------------------------------------
# The document set
#
# Everything that ties this build to *these* papers lives here.  Pointing the
# reader at a different pair is an edit to this table: nothing downstream —
# not the Lean parser, not the geometry, not the viewer — names a document.
# --------------------------------------------------------------------------

BUILD = ROOT / "stignore-build"

DOCS: list[dict] = [
    {
        "id": "P3",                                   # key prefix and citation marker
        "title": "EasyPQC on a Concrete Semantics",
        "short": "easypqc",                           # coverage-table caption
        "root": SANDBOX / "tex/P3-easypqc",           # what synctex resolves against
        "files": ["sections/*.tex"],                  # globs, in document order
        "main": "main.tex",                           # what latexmk compiles
        "pdf": BUILD / "P3/main.pdf",
        "env": {"BIBINPUTS": "../common:"},           # \bibliography{refs} lives there
        # how a Lean comment names this document; first match before a citation wins
        "markers": [r"\bP3\b", r"EasyPQC"],
    },
    {
        "id": "note",
        "title": "Quantum Procedure Call Semantics",
        "short": "semantics",
        "root": SANDBOX / "tex/note",
        "files": ["main.tex", "appendix.tex"],
        "main": "main.tex",
        "pdf": BUILD / "note/main.pdf",
        "markers": [r"\bnotes?\b"],
    },
]
LEAN_DIR = SANDBOX / "lean"

# one alternation over every document's markers, each in its own capture group,
# so a match can be traced back to the document that claimed it
MARKER_RE = re.compile("|".join(
    "(?P<%s>%s)" % (d["id"].replace("-", "_"), "|".join(d["markers"])) for d in DOCS))
MARKER_OF = {d["id"].replace("-", "_"): d["id"] for d in DOCS}


def doc_files(d: dict) -> list[Path]:
    """The document's sources, globs expanded, in the order given."""
    out: list[Path] = []
    for pat in d["files"]:
        out.extend(sorted(d["root"].glob(pat)) if "*" in pat
                   else ([d["root"] / pat] if (d["root"] / pat).exists() else []))
    return out


def attach_cited_by(tex_items: dict[str, TexItem]) -> int:
    """Invert the papers' cross-references.

    An item already knows what it cites; what cites *it* is the direction a
    reader coming from the Lean side asks for first, and it exists nowhere in
    the source — only in the sum of every other item's `\\Cref`s.
    """
    edges = 0
    for key, it in tex_items.items():
        for lbl in it.refs:
            hit = next((f"{d}::{lbl}" for d in (it.doc, *(x["id"] for x in DOCS))
                        if f"{d}::{lbl}" in tex_items), None)
            if hit and hit != key and key not in tex_items[hit].cited_by:
                tex_items[hit].cited_by.append(key)
                edges += 1
    return edges


def attach_pdf_rects(tex_items: dict[str, TexItem]) -> int:
    """Locate every item in its compiled PDF via SyncTeX forward search.

    Only the rectangles are recorded.  Page count and page size come from
    pdf.js at read time, which is the authority on what it is drawing.
    """
    from synctex import SyncTeX

    found = 0
    for d in DOCS:
        pdf = d["pdf"]
        if not pdf.exists():
            print(f"!! {pdf.relative_to(ROOT)} missing — run `make pdf`", file=sys.stderr)
            continue
        st = SyncTeX(pdf, d["root"])
        if not st.ok:
            print(f"!! no .synctex.gz beside {pdf.name}", file=sys.stderr)
            continue
        for it in tex_items.values():
            if it.doc != d["id"] or it.kind not in ENV_KINDS:
                continue
            if not st.knows(it.file):
                continue
            it.rect = st.rect(it.file, it.line, it.end_line)
            it.proof_rect = (st.rect(it.file, it.line, it.proof_end)
                             if it.proof_end else None)
            found += bool(it.rect)
    return found


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    tex_items: dict[str, TexItem] = {}
    order = 0
    for d in DOCS:
        for f in doc_files(d):
            rel = str(f.relative_to(d["root"]))     # what synctex indexes it as
            got = parse_tex_file(f, d["id"], rel, order)
            order = got[-1].order if got else order
            for it in got:
                tex_items[f"{d['id']}::{it.label}"] = it

    labels = {d["id"]: {it.label for it in tex_items.values() if it.doc == d["id"]}
              for d in DOCS}

    located = attach_pdf_rects(tex_items)
    tex_refs = attach_cited_by(tex_items)

    # title -> the items carrying it, for citations that name an item in prose
    titles: dict[str, list[tuple[str, str, str]]] = {}
    for it in tex_items.values():
        if it.title and it.kind in ENV_KINDS:
            titles.setdefault(it.title, []).append((it.kind, it.doc, it.label))

    lean_files, all_refs = [], []
    # recursive: a formalization organises itself in directories, and the file
    # index in the viewer shows that structure rather than flattening it
    for f in sorted(LEAN_DIR.rglob("*.lean")):
        if f.stem.startswith("_root_"):
            continue
        rel = f.relative_to(LEAN_DIR).as_posix()
        name = rel[:-len(".lean")]
        decls, mdoc, refs = parse_lean_file(f, name, titles)
        text = f.read_text(encoding="utf-8")
        lean_files.append({
            "name": name,
            "path": rel,               # where it sits under the Lean root
            "module_doc": mdoc,
            "lines": len(text.split("\n")),
            # the module verbatim: the pane scrolls the file and bands the
            # declaration, so a slice would cost the reader the surroundings
            # that say where in the module they are
            "text": text,
            "decls": [asdict(d) for d in decls],
        })
        all_refs.extend(refs)
    lean_files = import_order(lean_files)
    decl_refs = declaration_uses(lean_files)

    known = lambda lbl: any(lbl in s for s in labels.values())
    links, unresolved = [], []
    for r in all_refs:
        # `def:wf.3` cites clause 3 of `def:wf`; a trailing `.` is sentence punctuation
        clause = ""
        if not known(r["label"]):
            base = r["label"].rstrip(".")
            cm = re.match(r"^(.*)\.(\d+)$", base)
            if cm and known(cm.group(1)):
                clause, base = cm.group(2), cm.group(1)
            r = {**r, "label": base, "clause": clause}
        holders = [d["id"] for d in DOCS if r["label"] in labels[d["id"]]]
        if not holders:
            unresolved.append(r)
            continue
        # a label in more than one document is settled by the nearest marker,
        # and failing that by document order
        doc = (r["doc_hint"] if r["doc_hint"] in holders else holders[0])
        links.append({**r, "doc": doc, "key": f"{doc}::{r['label']}"})

    # per-item aggregation
    by_item: dict[str, list[dict]] = {}
    for l in links:
        by_item.setdefault(l["key"], []).append(l)

    manifest = {
        "generated_from": "sandbox/ (source copies; no Lean build)",
        # the viewer takes its document set from here rather than knowing one
        "docs": [{"id": d["id"], "title": d["title"], "short": d["short"],
                  "main": (d["root"] / d["main"]).relative_to(SANDBOX).as_posix(),
                  "files": [f.relative_to(SANDBOX).as_posix() for f in doc_files(d)]}
                 for d in DOCS],
        "tex": {k: asdict(v) for k, v in tex_items.items()},
        "lean": lean_files,
        "links": links,
        "by_item": by_item,
        "unresolved": unresolved,
        "stats": {
            "tex_items": len(tex_items),
            "doc_items": {k: len(v) for k, v in labels.items()},
            "lean_files": len(lean_files),
            "lean_decls": sum(len(f["decls"]) for f in lean_files),
            "lean_lines": sum(f["lines"] for f in lean_files),
            "tex_refs": tex_refs,          # \Cref edges between paper items
            "decl_refs": decl_refs,        # name edges between Lean declarations
            "links": len(links),
            "links_by_title": sum(1 for l in links if l.get("via") == "title"),
            "linked_items": len(by_item),
            "unresolved": len(unresolved),
            "located": located,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    s = manifest["stats"]
    per = ", ".join(f"{k} {v}" for k, v in s["doc_items"].items())
    print(f"tex items      {s['tex_items']}  ({per})")
    print(f"lean           {s['lean_files']} files, {s['lean_decls']} decls, "
          f"{s['lean_lines']} lines")
    print(f"links          {s['links']} citations -> {s['linked_items']} distinct items"
          f"  ({s['links_by_title']} cited by title)")
    print(f"references     {s['tex_refs']} between paper items, "
          f"{s['decl_refs']} between Lean declarations")
    print(f"located        {s['located']} items placed in the PDFs by synctex")
    print(f"unresolved     {s['unresolved']}")
    if unresolved:
        seen = {}
        for u in unresolved:
            seen.setdefault(u["label"], []).append(f"{u['file']}:{u['line']}")
        for lbl, where in sorted(seen.items()):
            print(f"   ! {lbl:28s} {', '.join(where[:4])}")
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
