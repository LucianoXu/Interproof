"""The formal side, parsed as source text.

Declarations with their docstrings, module docstrings, `/-! ## … -/` section
headers, the citations occurring **in comments**, and the names a declaration
writes in its own code.  No Lean build: everything here is what the file says,
which is what makes the whole pipeline runnable against a formalization whose
toolchain you do not have.

The cost of that choice is stated rather than hidden.  A name match is not
elaboration: it cannot see a lemma that a `simp` set applied for you, and a
local binder sharing a declaration's name reads as a use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

DECL_RE = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?"
    r"(?:private\s+|protected\s+|noncomputable\s+|partial\s+|unsafe\s+|scoped\s+)*"
    r"(theorem|lemma|def|abbrev|structure|inductive|instance|class|opaque|example)"
    r"\s+([^\s:({\[]+)")
BREAK_RE = re.compile(r"^(namespace|end|section|variable|open|universe|import|"
                      r"attribute|set_option|local\s|macro|notation|syntax|"
                      r"declare_syntax_cat|deriving)\b")

# a dotted Lean identifier, as it is written in code
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*")

IMPORT_RE = re.compile(r"^import\s+([A-Za-z0-9_.]+)", re.M)


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


@dataclass(frozen=True)
class Citations:
    """How this project writes a citation, compiled once.

    Built from the configuration so that no pattern in this module is a fact
    about any particular pair of documents; held as one object because the
    patterns are consulted per file and recompiling them per file is the kind
    of waste that only shows up on a large formalization.
    """

    label_re: re.Pattern[str]
    marker_re: re.Pattern[str] | None
    marker_of: dict[str, str]
    title_cite: str                      # a %s-template taking the escaped title
    env_of_word: dict[str, str]
    environments: tuple[str, ...]

    @classmethod
    def of(cls, cfg: Config) -> "Citations":
        g = cfg.grammar
        markers = [d for d in cfg.documents if d.markers]
        return cls(
            label_re=g.label_re,
            marker_re=cfg.marker_re if markers else None,
            marker_of=cfg.marker_of,
            title_cite=r"\b(" + g.kind_word_re + r")\s*\(?\s*(%s)\s*\)?",
            env_of_word=g.env_of_word,
            environments=tuple(g.environments),
        )


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


def parse_file(
    path: Path,
    name: str,
    titles: dict[str, list[tuple[str, str, str]]],
    cites: Citations,
) -> tuple[list[LeanDecl], str, list[dict]]:
    """Parse one Lean module.

    `name` is how the module is referred to everywhere downstream — its path
    under the formal root, extension dropped, so two subdirectories may hold
    the same file name.  `titles` maps an item title to the `(kind, doc, label)`
    triples that carry it, for citations that name an item by title.
    """
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
        if cites.marker_re is not None:
            for mm in cites.marker_re.finditer(text[max(0, start - 90):start]):
                doc_hint = cites.marker_of[mm.lastgroup]
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
    for m in cites.label_re.finditer(text):
        if not in_comment[m.start()]:
            continue
        r = mkref(m.start(), m.end(), f"{m.group(1)}:{m.group(2)}", "label")
        seen.add((r["line"], r["label"]))
        refs.append(r)

    # A citation may name its item by *title* — "Def. procedure declaration",
    # "Definition (frame lifting)" — and that is just as much a citation.
    # Reading only the canonical form leaves declarations that plainly state
    # their counterpart looking uncovered.
    for title, cands in titles.items():
        for m in re.finditer(cites.title_cite % re.escape(title), text, re.I):
            if not in_comment[m.start()]:
                continue
            kind = cites.env_of_word.get(m.group(1).lower().rstrip("."))
            hit = [c for c in cands if c[0] == kind]   # "Lemma (locality)" is not def:local
            if not hit:
                continue
            r = mkref(m.start(), m.end(), "", "title")
            if len(hit) > 1 and r["doc_hint"]:        # same title in two documents
                hit = [c for c in hit if c[1] == r["doc_hint"]] or hit
            for _, doc, label in hit:
                if (r["line"], label) in seen:
                    continue
                seen.add((r["line"], label))
                refs.append({**r, "label": label, "doc_hint": doc})
    return decls, module_doc, refs


def declaration_uses(files: list[dict]) -> int:
    """Which declarations each declaration names in its own code.

    The other half of the reference structure: the paper's items cite each
    other by `\\Cref`, and the formal declarations cite each other by *using*
    each other.  Both are read here, and the viewer shows each in both
    directions — what a thing rests on, and what rests on it.

    This is a name match over source text, in the same spirit as the rest of
    this module.  It cannot see a lemma a `simp` set applies for you, and a
    local binder that happens to share a declaration's name reads as a use.
    Comments are excluded — a name discussed in a docstring is prose, and the
    citations that matter there are already harvested as paper links.
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


def import_order(files: list[dict]) -> list[dict]:
    """Modules in dependency order: each one follows everything it imports.

    This is the formalization's own order, and the order the modules are meant
    to be read in.  The file system's alphabetical order is an accident: it
    opens the index on whatever module starts with an early letter, and
    interleaves the layers, so scrolling the index tells the reader nothing
    about what is built on what.

    Which imports are internal is not assumed: an import names a module by its
    dotted path, and the root prefix is whatever prefix the imports that do
    resolve agree on — so nothing here knows the package's name either.
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
