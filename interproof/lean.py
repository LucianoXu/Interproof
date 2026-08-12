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
    signature: str = ""      # the declaration as written, body cut off
    parent: str = ""         # the declaration this is a member of, if any


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

    @classmethod
    def of(cls, cfg: Config) -> "Citations":
        markers = [d for d in cfg.documents if d.markers]
        return cls(
            label_re=cfg.grammar.label_re,
            marker_re=cfg.marker_re if markers else None,
            marker_of=cfg.marker_of,
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


OPEN, CLOSE = "([{⟨⦃⟮⁅", ")]}⟩⦄⟯⁆"
BODY_WORD = ("where", "by")

# The members of a declaration that has them: a constructor of an `inductive`,
# a field of a `structure`.  These are what a paper's *clauses* correspond to —
# one production of a grammar, one condition of a definition — and Lean has
# already named every one of them, which is why they can be read rather than
# annotated.
HAS_MEMBERS = ("inductive", "structure", "class")
CTOR_RE = re.compile(r"^\s*\|\s*([A-Za-z_][A-Za-z0-9_'!?]*)")
FIELD_RE = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_'!?]*)\s*:(?!=)")
# `deriving` ends a body; so does a line that has come back out to column zero
MEMBERS_END_RE = re.compile(r"^\s*deriving\b|^\S")


def _idch(c: str) -> bool:
    """A character Lean will accept inside an identifier.

    `isalnum` rather than a range: a formalization writes `σ`, `Γ₀` and `xₐ`,
    and a signature that stopped at the first non-ASCII letter would cut most
    real statements in half.
    """
    return c.isalnum() or c in "_'!?"


def signature_of(code: str) -> str:
    """A declaration with its body cut off — what it *states*.

    The hover text on the path where nothing was elaborated, so it is the
    source and says only what the source says: the binders and the type as
    they are written, up to the `:=`, `where` or `by` that starts proving, or
    the first `|` of a match on a line of its own.

    Nesting is what makes this more than a `split`.  `(n : Nat := 0)` is a
    default argument, `fun _ => by simp` inside a binder is part of the
    statement, and a `--` in a comment above the body is not a body.  So this
    is a scanner, and it only stops at depth zero.
    """
    out, i, n, depth, fresh = [], 0, len(code), 0, True
    while i < n:
        c = code[i]
        if code.startswith("/-", i):
            d, j = 0, i
            while j < n:
                if code.startswith("/-", j):
                    d += 1
                    j += 2
                elif code.startswith("-/", j):
                    d -= 1
                    j += 2
                    if not d:
                        break
                else:
                    j += 1
            out.append(code[i:j]); i = j; fresh = False; continue
        if code.startswith("--", i):
            j = code.find("\n", i)
            j = n if j < 0 else j
            out.append(code[i:j]); i = j; continue
        if c == '"':
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(code[i:j]); i = j; fresh = False; continue
        if _idch(c) and not c.isdigit():
            j = i
            while j < n and (_idch(code[j]) or code[j] == "."):
                j += 1
            if depth == 0 and code[i:j] in BODY_WORD:
                break
            out.append(code[i:j]); i = j; fresh = False; continue
        if c in OPEN:
            depth += 1
        elif c in CLOSE:
            # clamped: a stray closer from some notation must not put the
            # scanner below zero and make the next `:=` look top-level
            depth = max(0, depth - 1)
        elif depth == 0:
            if code.startswith(":=", i):
                break
            if fresh and c == "|":
                break
        if c == "\n":
            fresh = True
        elif not c.isspace():
            fresh = False
        out.append(c)
        i += 1

    text = "".join(out).rstrip()
    # a signature is read in a hover card, so its own indentation is what makes
    # a multi-line binder list legible; only the block indent is dropped
    lines = text.split("\n")
    pad = [len(l) - len(l.lstrip()) for l in lines[1:] if l.strip()]
    cut = min(pad) if pad else 0
    return "\n".join([lines[0]] + [l[cut:] for l in lines[1:]]).rstrip()


def parse_file(
    path: Path,
    name: str,
    cites: Citations,
) -> tuple[list[LeanDecl], str, list[dict]]:
    """Parse one Lean module.

    `name` is how the module is referred to everywhere downstream — its path
    under the formal root, extension dropped, so two subdirectories may hold
    the same file name.
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

    def doc_above(ln_no: int) -> tuple[str, int]:
        """The `/-- ... -/` docstring introducing the line, if there is one.

        Asked of the comment spans rather than of the line text: a line ending
        in `-/` says only that *some* comment ends there, and a `/-! ## ... -/`
        section header ends that way too.  Reading it as a docstring and then
        searching back for the `/--` that must have opened it walks into the
        previous declaration's docstring, and the band starts forty lines early
        with a whole declaration inside it.
        """
        j = ln_no - 2
        while j >= 0 and (lines[j].strip().startswith("@[") or not lines[j].strip()):
            j -= 1
        above = block_end.get(j + 1)
        if not (above and above[1]):
            return "", 0
        doc = "\n".join(lines[above[0] - 1:j + 1])
        doc = re.sub(r"^\s*/--", "", doc).strip()
        doc = re.sub(r"-/\s*$", "", doc).strip()
        return doc, above[0]

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
        # only a docstring in column zero: an indented `/-- ... -/` introduces a
        # constructor or a field, and breaking on it would end the `inductive`
        # in the middle of its own body and lose every member below it
        [line_of(a) for a, _ in spans
         if text.startswith("/--", a) and (a == 0 or text[a - 1] == "\n")] +
        [len(lines) + 1]
    )

    decls: list[LeanDecl] = []
    for (ln_no, kind, dname) in starts:
        nxt = next((b for b in boundaries if b > ln_no), len(lines) + 1)
        end = nxt - 1
        while end > ln_no and not lines[end - 1].strip():
            end -= 1
        doc, doc_line = doc_above(ln_no)
        sec = ""
        for sl, st in sections:
            if sl < ln_no:
                sec = st
        code = "\n".join(lines[ln_no - 1:end])
        decls.append(LeanDecl(
            name=dname, kind=kind, file=name, line=ln_no, end_line=end,
            doc_line=doc_line, doc=doc, section=sec,
            has_sorry=bool(re.search(r"\bsorry\b", code)),
            signature=signature_of(code),
        ))

    # The members of the declarations that have them.  A paper's definition has
    # clauses and its grammar has productions, and the counterpart of one of
    # those is not a whole `inductive` — it is one constructor of it.  Lean has
    # already named every one, so this is read off the source rather than
    # annotated, and a citation in the docstring above a constructor lands on
    # the constructor: the band covers that line, not the fifteen around it.
    for d in list(decls):
        if d.kind not in HAS_MEMBERS:
            continue
        hits: list[tuple[int, str]] = []
        body_end = d.end_line
        for ln in range(d.line + 1, d.end_line + 1):
            body = lines[ln - 1]
            if MEMBERS_END_RE.match(body):
                # `deriving Repr` closes the body and belongs to none of them;
                # without this the last member's band runs a line long
                body_end = ln - 1
                break
            if in_comment[min(line_start_off[ln - 1], len(text))]:
                continue
            m = CTOR_RE.match(body) or (FIELD_RE.match(body)
                                        if d.kind != "inductive" else None)
            if m:
                hits.append((ln, m.group(1)))
        # docstrings first, because where one member stops depends on whether
        # the *next* one has a docstring: the prose introducing a constructor
        # belongs to it, and left to the member above it lands in the wrong band
        docs = []
        for ln, mname in hits:
            mdoc, mdoc_line = doc_above(ln)
            # a docstring above the first member could be the parent's own; the
            # parent already claimed it, and two owners for one comment would
            # band the same prose twice
            if mdoc_line and mdoc_line <= d.line:
                mdoc, mdoc_line = "", 0
            docs.append((mdoc, mdoc_line))

        for k, (ln, mname) in enumerate(hits):
            stop = (min(hits[k + 1][0], docs[k + 1][1] or hits[k + 1][0]) - 1
                    if k + 1 < len(hits) else body_end)
            mdoc, mdoc_line = docs[k]
            while stop > ln and not lines[stop - 1].strip():
                stop -= 1
            # the leading `|` comes off before the signature is read: it is how
            # a constructor is written, and `signature_of` stops at a
            # line-initial `|` because that is where a match arm begins
            chunk = re.sub(r"^\s*\|\s*", "", "\n".join(lines[ln - 1:stop])).lstrip()
            decls.append(LeanDecl(
                name=f"{d.name}.{mname}", kind="constructor" if d.kind == "inductive"
                else "field", file=name, line=ln, end_line=stop,
                doc_line=mdoc_line, doc=mdoc, section=d.section, parent=d.name,
                signature=signature_of(chunk),
            ))

    # harvest references from comment text only
    def mkref(start: int, stop: int, label: str) -> dict:
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
        # Innermost wins.  A constructor's span sits inside its `inductive`'s,
        # so first-match would hand every citation to the parent and band the
        # whole datatype for a claim about one production.
        owner, tightest = None, None
        for d in decls:
            top = d.doc_line or d.line
            if top <= lno <= d.end_line and (tightest is None
                                             or d.end_line - top < tightest):
                owner, tightest = d.name, d.end_line - top
        # A citation owned by a declaration claims that the declaration *is*
        # the statement — a correspondence.  `cf.` in the clause before the
        # label withdraws the claim: the declaration is *about* the statement,
        # a mention.  Module prose owns nothing, so it can only mention.  The
        # 40-character window is the same idea as the marker's 90: the same
        # clause, not the same file.
        corr = owner is not None and not re.search(
            r"\bcf\.", text[max(0, start - 40):start])
        blk = block_of(start)
        return {"label": label, "line": lno, "doc_hint": doc_hint, "decl": owner,
                "corr": corr,
                "file": name,
                # the prose block doing the citing, for when no declaration owns it
                "block_from": blk[0], "block_to": blk[1],
                "context": text[max(0, start - 220):stop + 220].replace("\n", " ").strip()}

    # The label is the only citation form, and deliberately so.  Naming an item
    # by its title instead — `Definition (frame lifting)` — was read here once,
    # and it was a mistake: a title is prose, it recurs in prose that is not
    # citing anything, and the extent it produced was wrong often enough that
    # the reader could not be trusted.  A label is an identifier the author
    # chose to be one, which is the whole reason it can carry this.
    refs: list[dict] = []
    for m in cites.label_re.finditer(text):
        if not in_comment[m.start()]:
            continue
        refs.append(mkref(m.start(), m.end(), f"{m.group(1)}:{m.group(2)}"))
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
                # a constructor names its own datatype in its type, and a field
                # its own structure; that is not a dependency, it is what being
                # a member is
                if not cands or m.group(0) in (d["name"], d.get("parent")):
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


def import_prefix(files: list[dict]) -> str:
    """The dotted prefix this formalization's own modules are imported under.

    A module is keyed here by its path under the formal root, and Lean names it
    by its path under the *package* root; the two differ by a prefix nothing in
    the configuration has to state.  It is read off the imports instead: the
    prefix is whichever one the imports that resolve to a module of this build
    agree on.  So neither the import order below nor the module names handed to
    a Lean tool knows the package's name.
    """
    dotted = {f["name"].replace("/", "."): f["name"] for f in files}
    prefixes: dict[str, int] = {}
    for f in files:
        for t in IMPORT_RE.findall(f["text"]):
            for m in dotted:
                if t == m or t.endswith("." + m):
                    prefixes[t[:len(t) - len(m)]] = prefixes.get(t[:len(t) - len(m)], 0) + 1
    return min(prefixes, key=lambda p: (-prefixes[p], len(p))) if prefixes else ""


def import_order(files: list[dict]) -> list[dict]:
    """Modules in dependency order: each one follows everything it imports.

    This is the formalization's own order, and the order the modules are meant
    to be read in.  The file system's alphabetical order is an accident: it
    opens the index on whatever module starts with an early letter, and
    interleaves the layers, so scrolling the index tells the reader nothing
    about what is built on what.
    """
    dotted = {f["name"].replace("/", "."): f["name"] for f in files}
    raw = {f["name"]: IMPORT_RE.findall(f["text"]) for f in files}
    root = import_prefix(files)

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
