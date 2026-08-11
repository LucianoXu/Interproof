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
    code: str = ""
    section: str = ""
    refs: list[dict] = field(default_factory=list)
    has_sorry: bool = False


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
    titles: dict[str, list[tuple[str, str, str]]] | None = None,
) -> tuple[list[LeanDecl], str, list[dict]]:
    """Parse one Lean module.  `titles` maps an item title to the
    `(kind, doc, label)` triples that carry it, for title-form citations."""
    titles = titles or {}
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    name = path.stem

    # line -> True if inside a comment (for reference harvesting)
    spans = comment_spans(text)
    in_comment = [False] * (len(text) + 1)
    for a, b in spans:
        for k in range(a, min(b, len(text))):
            in_comment[k] = True

    def line_of(idx: int) -> int:
        return text.count("\n", 0, idx) + 1

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
        # preceding docstring
        doc, doc_line = "", 0
        j = ln_no - 2
        while j >= 0 and (lines[j].strip().startswith("@[") or not lines[j].strip()):
            j -= 1
        if j >= 0 and lines[j].rstrip().endswith("-/"):
            k = j
            while k >= 0 and "/--" not in lines[k]:
                k -= 1
            if k >= 0:
                doc_line = k + 1
                doc = "\n".join(lines[k:j + 1])
                doc = re.sub(r"^\s*/--", "", doc).strip()
                doc = re.sub(r"-/\s*$", "", doc).strip()
        sec = ""
        for sl, st in sections:
            if sl < ln_no:
                sec = st
        code = "\n".join(lines[ln_no - 1:end])
        decls.append(LeanDecl(
            name=dname, kind=kind, file=name, line=ln_no, end_line=end,
            doc_line=doc_line, doc=doc, code=code, section=sec,
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
        return {"label": label, "line": lno, "doc_hint": doc_hint, "decl": owner,
                "via": via, "file": name,
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

    # title -> the items carrying it, for citations that name an item in prose
    titles: dict[str, list[tuple[str, str, str]]] = {}
    for it in tex_items.values():
        if it.title and it.kind in ENV_KINDS:
            titles.setdefault(it.title, []).append((it.kind, it.doc, it.label))

    lean_files, all_refs = [], []
    for f in sorted(LEAN_DIR.glob("*.lean")):
        if f.stem.startswith("_root_"):
            continue
        decls, mdoc, refs = parse_lean_file(f, titles)
        lean_files.append({
            "name": f.stem,
            "module_doc": mdoc,
            "lines": len(f.read_text(encoding="utf-8").split("\n")),
            "decls": [asdict(d) for d in decls],
        })
        all_refs.extend(refs)

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
        "docs": [{"id": d["id"], "title": d["title"], "short": d["short"]}
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
