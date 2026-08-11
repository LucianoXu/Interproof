"""`interproof init` — write a configuration by looking at what is here.

A first configuration is mostly clerical: which `.tex` file is a document, what
it `\\input`s, where the `.lean` tree is.  All of that is visible from the
directory, so it is guessed and written out as a filled-in file with the
reasoning attached, rather than as a skeleton of `TODO`s.  A guess that is
wrong is easy to fix, and a guess that is right saves the first user of a new
project from reading a reference manual before their first build.

What init cannot supply is the correspondence itself: point this at a
formalization whose comments never cite a paper and the manifest comes back
empty.  That is why it also drops `CITING.md` — the protocol is the real
interface of this tool, and it is addressed to whoever writes the Lean.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import CONFIG_NAME

SKIP_DIRS = {".git", ".lake", ".venv", "venv", "node_modules", "__pycache__",
             ".interproof", "site", "build", "_build", "out", "dist", ".cache"}


def init_project(where: Path, *, force: bool = False) -> int:
    root = where.resolve()
    if not root.is_dir():
        print(f"interproof: {root} is not a directory")
        return 2
    target = root / CONFIG_NAME
    if target.exists() and not force:
        print(f"interproof: {target} already exists (use --force to overwrite)")
        return 2

    docs = find_documents(root)
    lean_root = find_lean_root(root)
    target.write_text(render(root, docs, lean_root), encoding="utf-8")

    print(f"wrote {target.relative_to(Path.cwd()) if _under_cwd(target) else target}")
    for d in docs:
        print(f"   document  {d['id']:12s} {d['root']}/{d['main']}"
              + (f"  (+{len(d['files']) - 1} more source files)"
                 if len(d["files"]) > 1 else ""))
    if not docs:
        print("   no .tex file with a \\documentclass was found — "
              "fill in [[document]] by hand")
    print(f"   formal    {lean_root or 'not found — fill in [formal] root by hand'}")

    citing = root / "CITING.md"
    if not citing.exists():
        text = protocol_text()
        if text:
            citing.write_text(text, encoding="utf-8")
            print(f"wrote {citing.name} — the citation protocol, for whoever "
                  f"writes the formal sources")

    print()
    print(f"Next:  interproof check     # does anything resolve yet?")
    print(f"       interproof serve     # read it, rebuilt as you edit")
    print(f"       interproof build     # a folder you can archive or publish")
    return 0


def _under_cwd(p: Path) -> bool:
    try:
        p.relative_to(Path.cwd())
        return True
    except ValueError:
        return False


def walk(root: Path, suffix: str) -> list[Path]:
    out = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_dir():
                if e.name not in SKIP_DIRS and not e.name.startswith("."):
                    stack.append(e)
            elif e.suffix == suffix:
                out.append(e)
    return sorted(out)


def find_documents(root: Path) -> list[dict]:
    """Every `.tex` file that starts a document, with what it reads.

    A `\\documentclass` is what distinguishes a document from the files it is
    made of, which is the same rule latexmk uses.
    """
    docs = []
    for f in walk(root, ".tex"):
        try:
            head = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not re.search(r"^\s*\\documentclass", head, re.M):
            continue
        droot = f.parent
        # What it reads, as a glob where a whole directory is read and by name
        # otherwise.  Only what stays inside the document root: `files` is
        # resolved against that root, and a shared preamble one directory up is
        # an input to the *build*, which latexmk finds on its own — listing it
        # here would only make the viewer offer a preamble as a document.
        inputs = [i for i in re.findall(r"\\(?:input|include)\{([^}]+)\}", head)
                  if not i.startswith("/") and ".." not in Path(i).parts]
        files = [f.name]
        for d in sorted({str(Path(i).parent) for i in inputs if "/" in i}):
            if (droot / d).is_dir():
                files.append(f"{d}/*.tex")
        for i in inputs:
            if "/" in i:
                continue
            name = i if i.endswith(".tex") else i + ".tex"
            if (droot / name).is_file() and name not in files:
                files.append(name)
        docs.append({
            "id": doc_id(f),
            "title": guess_title(head) or doc_id(f),
            "root": rel(droot, root),
            "main": f.name,
            "files": files,
            "texinputs": texinputs(f, head, droot, root),
        })
    return docs


def texinputs(main: Path, head: str, droot: Path, root: Path) -> str:
    """Where LaTeX has to look for a file this document reads but does not hold.

    A shared preamble in a sibling directory, reached as `\\input{preamble}`,
    is the commonest layout in a project with two papers — and the one thing
    that makes a generated configuration fail on its first build, with an error
    about a file the reader can see perfectly well sitting on disk.  Guessing
    the search path is worth it: the alternative is that `interproof init`
    produces something that does not compile, which is worse than producing
    nothing.
    """
    want = []
    for i in re.findall(r"\\(?:input|include)\{([^}]+)\}", head):
        if "/" in i or i.startswith(".."):
            continue                                   # a path resolves itself
        name = i if i.endswith(".tex") else i + ".tex"
        if (droot / name).is_file():
            continue                                   # found where it is read
        hits = [p for p in walk(root, ".tex") if p.name == name]
        if len(hits) == 1:                             # a genuine ambiguity is
            want.append(hits[0].parent)                # not worth a wrong guess
    dirs = []
    for d in want:
        r = os.path.relpath(d, droot)
        if r not in dirs:
            dirs.append(r)
    # the trailing empty entry is what keeps the TeX distribution on the path;
    # dropping it replaces the search path rather than extending it
    return ":".join(dirs) + ":" if dirs else ""


def doc_id(f: Path) -> str:
    """A short identifier, which is also how a citation will name the document.

    The directory name where it is informative, the file stem where it is not:
    `paper/main.tex` is the paper, and calling it `main` would make every
    citation in the formal sources say `main`.
    """
    stem = f.parent.name if f.stem in ("main", "paper", "article") else f.stem
    return re.sub(r"[^A-Za-z0-9]+", "", stem.title()) or "Doc"


def guess_title(text: str) -> str:
    """`\\title{…}`, reduced to the part of it that is a title.

    A real title carries typesetting: a `\\\\[2mm]` break with a subtitle after
    it, a `\\large`, an `\\emph`.  The break is where the title ends — what
    follows it is a subtitle set smaller — and the rest is markup a name should
    not keep.
    """
    m = re.search(r"\\title\{(.+?)\}\s*$", text, re.M | re.S)
    if not m:
        return ""
    t = re.split(r"\\\\", m.group(1))[0]
    t = re.sub(r"\\\w+\{([^}]*)\}", r"\1", t)          # \emph{x} -> x
    t = re.sub(r"\\[a-zA-Z]+\s*", "", t)               # \large, \bf, ...
    t = t.replace("{", "").replace("}", "")
    return " ".join(t.split())[:120]


def q(s: str) -> str:
    """A string as TOML, without inventing an escape.

    A LaTeX title is full of backslashes, and a basic string would have to
    escape every one of them — get that wrong and the configuration this
    command just wrote does not parse.  A literal string takes the text as it
    stands, which is what is wanted; only a quote inside the value forces the
    other kind.
    """
    if "'" not in s and "\n" not in s:
        return "'" + s + "'"
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def find_lean_root(root: Path) -> str:
    """The shallowest directory that holds `.lean` files.

    Shallowest rather than the one with the most files: a module is keyed by
    its path under this root, so choosing a directory too deep flattens the
    tree the index is supposed to show.
    """
    files = walk(root, ".lean")
    if not files:
        return ""
    dirs = sorted({f.parent for f in files},
                  key=lambda d: (len(d.relative_to(root).parts), str(d)))
    top = dirs[0]
    # a lakefile's package directory is a better root than its parent, but a
    # single stray .lean at the top level should not drag the root up with it
    if len(files) > 3 and sum(1 for f in files if f.parent == top) == 1:
        top = dirs[1] if len(dirs) > 1 else top
    return rel(top, root)


def rel(p: Path, root: Path) -> str:
    try:
        return p.relative_to(root).as_posix() or "."
    except ValueError:
        return p.as_posix()


def protocol_text() -> str:
    """`CITING.md`, from wherever this installation keeps it."""
    for cand in (Path(__file__).with_name("data") / "CITING.md",
                 Path(__file__).resolve().parent.parent / "docs" / "CITING.md"):
        if cand.is_file():
            return cand.read_text(encoding="utf-8")
    return ""


# --------------------------------------------------------------------------

def render(root: Path, docs: list[dict], lean_root: str) -> str:
    """The configuration, written as the thing a person will read first."""
    out = [
        "# Interproof — what this project is, in the terms the reader needs.",
        "#",
        "# Every path is relative to this file.  The tool is never configured by",
        "# editing the tool: pointing it at a different paper is an edit here.",
        "",
        "[project]",
        f"title = {q(root.name)}",
        '# out = "site"              # where `interproof build` writes the folder',
        '# build_dir = ".interproof/build"   # PDFs and SyncTeX data land here',
        "",
    ]
    if not docs:
        docs = [{"id": "Paper", "title": "TODO", "root": "paper",
                 "main": "main.tex", "files": ["main.tex"]}]
        out += ["# No .tex file with a \\documentclass was found; this is a "
                "skeleton.", ""]

    for i, d in enumerate(docs):
        out += [
            "[[document]]",
            f"id      = {q(d['id'])}".ljust(30)
            + "# key prefix, and how a citation in the formal sources names it",
            f"title   = {q(d['title'])}",
            f"short   = {q(d['id'].lower())}",
            f"root    = {q(d['root'])}".ljust(30) + "# what SyncTeX resolves against",
            f"main    = {q(d['main'])}".ljust(30) + "# what latexmk compiles",
            "files   = [" + ", ".join(q(f) for f in d["files"]) + "]"
            + "   # in reading order; the index inherits it",
        ]
        if d.get("texinputs"):
            out += [
                "# This document reads a file it does not hold — a shared",
                "# preamble — so LaTeX is told where to look for it.",
                "env     = { TEXINPUTS = " + q(d["texinputs"]) + " }",
            ]
        if i == 0:
            out += [
                "# How a comment in the formal sources names this document.  The",
                "# default is the id itself, which is what people write anyway; a",
                "# marker only has to be spelled out when two documents hold the",
                "# same label and a citation has to be told apart.",
                f'# markers = [\'\\b{d["id"]}\\b\', \'SomeOtherName\']',
                "# Extra environment for the LaTeX run — a shared bibliography one",
                "# directory up is the usual reason.",
                '# env = { BIBINPUTS = "../common:" }',
                "# The compiler, if it is not latexmk.  -synctex=1 is not optional:",
                "# without it no statement can be placed on a page.",
                '# latexmk = ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode"]',
            ]
        out += [""]

    out += [
        "[formal]",
        "kind = 'lean'".ljust(30) + "# Lean 4 is what this version reads",
        f"root = {q(lean_root or 'TODO')}".ljust(30)
        + "# a module is keyed by its path under here",
        '# exclude = ["**/Test/*.lean"]',
        "",
        "# The conventions of *this* project's LaTeX.  The defaults below are",
        "# spelled out so they can be seen and changed; delete the section to keep",
        "# them.  A project that writes `t:foo` instead of `thm:foo`, or that has a",
        "# \\begin{observation}, says so here rather than going unread.",
        "#",
        "# [grammar]",
        '# environments   = ["theorem", "lemma", "definition", "proposition",',
        '#                   "corollary", "remark", "example", "conjecture",',
        '#                   "fact", "assumption"]',
        '# label_prefixes = ["thm", "lem", "def", "prop", "cor", "rem", "sec",',
        '#                   "sub", "app", "fig", "tab", "eq"]',
        "#",
        "# How a citation that names an item by title spells its kind.  A title",
        "# citation has to agree on the kind, so `Lemma (locality)` never resolves",
        "# to `def:local`.",
        "# [grammar.kind_words]",
        '# definition = ["Definition", "Def."]',
        '# lemma      = ["Lemma", "Lem."]',
        '# theorem    = ["Theorem", "Thm."]',
        "",
    ]
    return "\n".join(out)
