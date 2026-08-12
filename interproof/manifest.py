#!/usr/bin/env python3
"""The correspondence, as one JSON document.

Data model borrowed from `span` — a checked `label <-> declaration` mapping —
but the mapping is *harvested from the formal side*, where a project that
formalizes a paper already records it: docstrings that say which statement a
declaration is.  Nothing has to be annotated twice, and nothing has to be
annotated in the paper, which is usually the actively edited half.

This module owns the assembly and the schema.  The two sides are parsed by
`tex` and `lean`; where an item sits on a page is `synctex`'s answer; which
documents exist at all is the configuration's.

The manifest is the contract between the build and the viewer, and it outlives
both — a published artifact carries a copy — so it is versioned (`schema`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA, __version__
from .config import Config, Document
from .lean import Citations, declaration_uses, import_order
from .lean import parse_file as parse_lean_file
from .tex import TexItem, attach_cited_by, parse_all as parse_tex_all, strip_comments

# What of a LaTeX source tree is text the artifact can carry verbatim.  Anything
# else that the build reads — figures, embedded PDFs — is an asset, carried as
# bytes and subject to a budget, because the manifest is inlined into a page.
TEXT_SUFFIXES = {".tex", ".bib", ".sty", ".cls", ".bst", ".clo", ".def",
                 ".ltx", ".txt", ".md"}
ASSET_BUDGET = 8 * 1024 * 1024


def build(cfg: Config, *, with_sources: bool = True, quiet: bool = False,
          elaborate: bool | None = None) -> dict:
    """Read both sides and return the manifest.

    `with_sources` embeds the LaTeX sources so that a published artifact can
    hand them back; the check command does not need them and says so.

    `elaborate` overrides `[formal] elaborate` for this run; `None` accepts
    whatever the project configured.  When it is on and it works, every module
    gains a `sem` overlay and the viewer reads types, definitions and Lean's
    own colouring off it.  When it is on and it does not work, the reason is
    printed and the manifest is exactly the one the text-only path produces —
    a reader that says less, never a build that fails.
    """
    say = (lambda *a: None) if quiet else (lambda *a: print(*a))

    tex_items = parse_tex_all(cfg)
    labels = {d.id: {it.label for it in tex_items.values() if it.doc == d.id}
              for d in cfg.documents}

    for line in configuration_warnings(cfg, tex_items, labels):
        say("!! " + line)

    located = attach_pdf_rects(cfg, tex_items, quiet=quiet)
    tex_refs = attach_cited_by(tex_items, cfg.documents)

    cites = Citations.of(cfg)
    lean_files, all_refs = [], []
    for f in cfg.lean_files():
        rel = f.relative_to(cfg.lean_root).as_posix()
        name = rel[:-len(".lean")]
        decls, mdoc, refs = parse_lean_file(f, name, cites)
        text = f.read_text(encoding="utf-8", errors="replace")
        lean_files.append({
            "name": name,
            "path": rel,               # where it sits under the formal root
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
    lean_strs, lean_defs, sem = semantics(cfg, lean_files, elaborate, say)

    links, unresolved = resolve(all_refs, labels, cfg.documents)
    if not links:
        for line in empty_correspondence(cfg, lean_files):
            say(line)

    by_item: dict[str, list[dict]] = {}
    for l in links:
        by_item.setdefault(l["key"], []).append(l)
    # the correspondence first, mentions after: whoever takes the first
    # citing declaration — the viewer does — gets the one that *is* the item
    for ls in by_item.values():
        ls.sort(key=lambda l: not l.get("corr"))
    covered = covered_items(tex_items, by_item)

    sources, assets, dropped = ([], [], []) if not with_sources else collect_sources(cfg)

    manifest = {
        "schema": SCHEMA,
        "tool": f"interproof {__version__}",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": {"title": cfg.title, "root": cfg.root.name},
        # the viewer takes its document set from here rather than knowing one
        "docs": [{"id": d.id, "title": d.title, "short": d.short,
                  "main": rel_to_root(cfg, d.main_path),
                  "files": [rel_to_root(cfg, f) for f in d.source_files()],
                  "pdf": f"pdf/{d.id}.pdf",
                  "rev": rev_of(d.pdf)}
                 for d in cfg.documents],
        "lean_root": rel_to_root(cfg, cfg.lean_root),
        # what a citation looks like in this project, so the viewer linkifies
        # exactly what the build read.  Hard-coding the prefixes in the page
        # meant a project writing `t:foo` was linked by the build and shown as
        # plain text by the reader.
        "grammar": {"label_prefixes": list(cfg.grammar.label_prefixes)},
        "tex": {k: asdict(v) for k, v in tex_items.items()},
        "lean": lean_files,
        # a fully qualified Lean name -> the declaration of this build that
        # defines it, which is what turns a token into a jump.  Empty, and the
        # viewer falls back to matching what the source wrote.
        "lean_defs": lean_defs,
        # every string the overlays refer to, once for the whole build: the
        # docstring of `simp` belongs to as many modules as mention it
        "lean_strs": lean_strs,
        "links": links,
        "by_item": by_item,
        # every item something *corresponds* to, anchors rolled up into their
        # statements: what "formalized" means, for the check and the overlay
        # alike, so the two can never drift apart
        "covered": covered,
        "unresolved": unresolved,
        "sources": sources,
        "assets": assets,
        "config": cfg.text,
        "stats": {
            "tex_items": len(tex_items),
            "doc_items": {k: len(v) for k, v in labels.items()},
            "lean_files": len(lean_files),
            "lean_decls": sum(len(f["decls"]) for f in lean_files),
            "lean_lines": sum(f["lines"] for f in lean_files),
            "tex_refs": tex_refs,          # \Cref edges between paper items
            "decl_refs": decl_refs,        # name edges between declarations
            "links": len(links),
            "corr_links": sum(1 for l in links if l.get("corr")),
            "linked_items": len(by_item),
            "unresolved": len(unresolved),
            "located": located,
            "sources": len(sources) + len(assets),
            "sem": sem,                    # what elaboration added, or why not
        },
    }
    for d in dropped:
        say(f"!! {d} not embedded (over the {ASSET_BUDGET // 1024 // 1024} MB "
            f"asset budget); it is still copied into the artifact folder")
    return manifest


# --------------------------------------------------------------------------
# elaboration
# --------------------------------------------------------------------------

def semantics(cfg: Config, files: list[dict], want: bool | None,
              say) -> tuple[list[str], dict[str, str], dict]:
    """Attach what Lean knows to each module, if this build was asked to.

    Returns the build's string table, the name index — `Nat.succ` -> the
    declaration of *this* build that defines it — and a summary for the stats.
    The overlay itself is hung on each module's record, because that is what
    the viewer already has in hand when it renders one.

    Nothing here raises.  Elaboration is an enrichment: a missing toolchain, a
    project that does not compile, a SubVerso this version cannot read — all of
    them mean a reader without hovers, and a reader without hovers is the one
    every build produced until now.  The reason is printed, because a silently
    plain build is exactly the failure mode `interproof` spends the rest of its
    output avoiding.
    """
    on = cfg.elaborate if want is None else want
    if not on:
        return [], {}, {"on": False}

    from .subverso import TEXT_FIELDS, SubVersoError, extract

    try:
        overlays, notes = extract(cfg, files, say=say)
    except SubVersoError as e:
        say(f"!! not elaborated: {e}")
        return [], {}, {"on": True, "failed": str(e).split("\n")[0]}
    except Exception as e:                             # noqa: BLE001 - reported
        say(f"!! not elaborated: {type(e).__name__}: {e}")
        return [], {}, {"on": True, "failed": f"{type(e).__name__}: {e}"}

    for line in notes:
        say(f"!! {line}")

    defs: dict[str, str] = {}
    tokens = states = 0

    # One string table for the build, not one per module.  What a module's
    # overlay spends on text is mostly Lean's own vocabulary — the docstring
    # of `simp`, the signature of `Nat.succ` — and that vocabulary is the same
    # in every module of the development, so a per-module table stores it once
    # per module.  The extraction cache stays module-local, because a module's
    # overlay has to survive its neighbours changing; the tables are merged
    # here instead, on the way into the manifest.
    strs: list[str] = []
    at: dict[str, int] = {}

    def sid(s: str) -> int:
        if s not in at:
            at[s] = len(strs)
            strs.append(s)
        return at[s]

    for f in files:
        ov = overlays.get(f["name"])
        if not ov:
            continue
        local = ov.get("strs") or []
        f["sem"] = {
            "attrs": [{k: (sid(local[v]) if k in TEXT_FIELDS else v)
                       for k, v in a.items()} for a in ov.get("attrs", [])],
            "toks": ov.get("toks", []),
            # the proof states, if this build carries them: a goal's text is
            # remapped into the shared table with everything else, because a
            # hypothesis `s t : Store` is the same string in every proof that
            # has one
            "tacs": ov.get("tacs", []),
            "goals": [{**({"n": sid(local[g["n"]])} if "n" in g else {}),
                       "h": [sid(local[x]) for x in g["h"]],
                       "c": sid(local[g["c"]])}
                      for g in ov.get("goals", [])],
            "states": ov.get("states", []),
        }
        tokens += len(ov.get("toks", [])) // 4
        states += len(ov.get("tacs", [])) // 4
        for full, line in ov.get("defs", []):
            key = _owner(f, full, line)
            if key:
                defs[full] = key

    # what this costs the artifact, measured rather than guessed: the overlay
    # is the one part of a manifest that scales with the size of the
    # formalization, and it is inlined into a page somebody downloads
    spent = sum(len(json.dumps(f["sem"], ensure_ascii=False,
                               separators=(",", ":")))
                for f in files if "sem" in f)
    spent += len(json.dumps(strs, ensure_ascii=False, separators=(",", ":")))

    return strs, defs, {"on": True, "modules": len(overlays), "of": len(files),
                        "tokens": tokens, "names": len(defs), "bytes": spent,
                        "strings": len(strs), "states": states,
                        **({"notes": len(notes)} if notes else {})}


def _owner(f: dict, full: str, line: int) -> str:
    """Which declaration of this module defines `full`.

    Two questions in one, and the order matters.  Where the name was defined is
    a line, and a declaration owns its docstring as well as its body, so
    containment answers most of it.  The rest are the names a command defines
    beside the one it was written for — `foo.eq_1`, `foo.match_1` — and those
    are tied back by their prefix, so following one lands on the declaration a
    reader was actually looking for rather than nowhere.
    """
    # A member first, by its dotted name.  Elaboration reports a constructor at
    # the line of the `inductive` that introduces it, so containment alone
    # cannot tell `Cmd.whileDo` from `Cmd` — but a member is named for its
    # parent, and that settles it.  Only members are looked up this way, so
    # every other resolution keeps the order it had.
    for d in f["decls"]:
        if d.get("parent") and (full == d["name"] or full.endswith("." + d["name"])):
            return f["name"] + "::" + d["name"]
    # innermost wins: a constructor's span sits inside its datatype's, and
    # following `Cmd.whileDo` should land on the constructor, not on `Cmd`
    best, span = "", None
    for d in f["decls"]:
        top = d.get("doc_line") or d["line"]
        if top <= line <= d["end_line"] and (span is None or d["end_line"] - top < span):
            best, span = f["name"] + "::" + d["name"], d["end_line"] - top
    if best:
        return best
    short = full.split(".")[-1]
    for d in f["decls"]:
        if d["name"] == short or full.endswith("." + d["name"]):
            return f["name"] + "::" + d["name"]
    return ""


# --------------------------------------------------------------------------
# the failures that look like success
# --------------------------------------------------------------------------

NEWTHEOREM_RE = re.compile(r"\\newtheorem\*?\s*\{([^}]+)\}")
LABEL_ANY_RE = re.compile(r"\\label\s*\{")
# anything shaped like a citation, whatever its prefix — for diagnosing a
# project whose labels this build was never told to look for
LABELISH_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9}):([A-Za-z0-9][A-Za-z0-9\-_.]*)")


def empty_correspondence(cfg: Config, lean_files: list[dict]) -> list[str]:
    """Nothing resolved at all — the one outcome that reads as success.

    Zero citations gives zero dangling ones, and a report that says "every
    citation resolves" over an empty set is true, useless, and the first thing
    a new user sees.  So this says what happened and, where the sources make it
    knowable, why.

    The interesting case is a project that *does* cite its paper in a notation
    this build was never told about: `t:main` where the configuration expects
    `thm:main`.  That is visible — the comments are full of label-shaped tokens
    with an unfamiliar prefix — and it is a one-line fix in `[grammar]`, so it
    is worth the scan.
    """
    from .lean import comment_spans

    known = set(cfg.grammar.label_prefixes)
    seen: dict[str, int] = {}
    for f in lean_files:
        text = f["text"]
        for a, b in comment_spans(text):
            for m in LABELISH_RE.finditer(text, a, min(b, len(text))):
                p = m.group(1)
                if p not in known:
                    seen[p] = seen.get(p, 0) + 1
    # A URL and a Lean namespace both look like this; only a prefix that recurs
    # is worth naming, and only the few that lead.
    candidates = [(p, n) for p, n in seen.items()
                  if n >= 3 and p not in ("http", "https", "file", "ftp")]
    candidates.sort(key=lambda kv: -kv[1])

    out = ["!! no citation resolved: the formal sources and the documents are "
           "not connected by anything this build can read."]
    if candidates:
        out.append("   The comments do carry label-shaped names with prefixes "
                   "this build ignores:")
        for p, n in candidates[:5]:
            out.append(f"       {p}:…  ({n} occurrences)")
        out.append("   If those are your labels, add the prefixes to "
                   "[grammar] label_prefixes in " + cfg.path.name + ":")
        out.append("       [grammar]")
        out.append("       label_prefixes = "
                   + str(sorted(known | {p for p, _ in candidates[:5]})).replace("'", '"'))
    else:
        out.append("   The comments carry no citations at all.  That is the "
                   "precondition, not a bug:")
        out.append("   Interproof reads a correspondence somebody wrote, it "
                   "does not invent one.")
        out.append("   The protocol is one page — see CITING.md, or "
                   "https://github.com/LucianoXu/Interproof/blob/main/docs/CITING.md")
    return out


def configuration_warnings(cfg: Config, items: dict[str, TexItem],
                           labels: dict[str, set[str]]) -> list[str]:
    """Configurations that produce a manifest, and the wrong one.

    Every check here is for a mistake whose symptom is *silence*: a build that
    succeeds, reports numbers, and is missing half the paper.  A run that
    crashes teaches you something; a run that quietly reads six of twelve
    statements teaches you nothing until much later.
    """
    out: list[str] = []

    # `kind_words` configured a citation form that no longer exists: naming an
    # item by kind and title rather than by label.  A configuration still
    # carrying it describes a build that will not happen, and the symptom is
    # the quiet one — those citations simply stop resolving.
    if re.search(r"^\s*(\[grammar\.kind_words\]|kind_words\s*=)", cfg.text, re.M):
        out.append("[grammar.kind_words] is no longer read: a citation names "
                   "its statement by label, and only by label.  Delete the "
                   "table, and give a \\label{} to anything that was cited by "
                   "title.")

    for d in cfg.documents:
        found = d.source_files()

        if not labels[d.id]:
            out.append(f"{d.id}: no labelled statements found in " + (
                f"{len(found)} source files.  Either they carry no \\label{{}}, "
                f"or [grammar] environments does not list the environments this "
                f"document uses." if found else
                f"no source files — `files = {d.files}` matched nothing under "
                f"{d.root}."))

        # `files = ["sections/*.tex"]` is the natural thing to write for a
        # split paper, and it silently drops every statement stated in the
        # main file.  Only worth saying when the main file actually has some.
        if d.main_path not in found:
            head = d.main_path.read_text(encoding="utf-8", errors="replace")
            n = len(LABEL_ANY_RE.findall(strip_comments(head)))
            if n:
                out.append(f"{d.id}: {d.main} carries {n} \\label{{}} but is not "
                           f"in `files`, so none of them is read.  Add "
                           f'"{d.main}" to files.')

        # The environments a document declares are in its preamble, and the
        # ones this build will read are in the configuration.  Nothing keeps
        # the two lists in step, and the symptom of a gap is items that simply
        # are not there.
        declared: set[str] = set()
        for p in {d.main_path, *found, *input_files(d)}:
            if p.suffix.lower() not in (".tex", ".sty"):
                continue
            if not is_under(p, cfg.root) and not is_under(p, d.root):
                continue
            try:
                declared |= set(NEWTHEOREM_RE.findall(
                    p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
        missed = set(declared) - set(cfg.grammar.environments)
        # `proof` is an environment in the same sense and is read as one, by a
        # different rule; naming it here would be noise on every project.
        missed.discard(cfg.grammar.proof_environment)
        # And a *declared* environment is not a used one.  Nearly every
        # preamble declares more theorem kinds than its paper uses, so warning
        # on the declaration would fire on almost every project and teach the
        # reader to skip these lines.  The warning has to mean "statements are
        # being dropped", so it waits until one is.
        hit: dict[str, int] = {}
        for p in {d.main_path, *found}:
            try:
                body = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            for e in missed:
                n = body.count("\\begin{%s}" % e)
                if n:
                    hit[e] = hit.get(e, 0) + n
        if hit:
            names = ", ".join(f"{e} ({n})" for e, n in sorted(hit.items()))
            out.append(f"{d.id}: {names} — used in the source and declared in "
                       f"the preamble, but not in [grammar] environments, so "
                       f"these statements are invisible to this build.")
    return out


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def resolve(refs: list[dict], labels: dict[str, set[str]],
            docs: list[Document]) -> tuple[list[dict], list[dict]]:
    """Turn harvested citations into links, or report them as dangling.

    Dangling is a finding, not an error: a citation that resolves to nothing is
    either a typo or a statement that was renamed on one side only, and both
    are exactly what a reader of the pair wants to be told.
    """
    known = lambda lbl: any(lbl in s for s in labels.values())
    links, unresolved = [], []
    for r in refs:
        # `def:wf.3` cites clause 3 of `def:wf`; a trailing `.` is sentence
        # punctuation that the citation swallowed
        clause = ""
        if not known(r["label"]):
            base = r["label"].rstrip(".")
            cm = re.match(r"^(.*)\.(\d+)$", base)
            if cm and known(cm.group(1)):
                clause, base = cm.group(2), cm.group(1)
            r = {**r, "label": base, "clause": clause}
        # `def:cmd:while` names a part of `def:cmd`.  Until the paper carries
        # an anchor by that name the citation is still a citation *of the
        # statement*, so the tail is peeled and kept rather than dangled: the
        # correspondence is coarser than the author wrote, never absent, and it
        # sharpens by itself the day the anchor exists.  Peeling from the right
        # is also what keeps a sentence out of the label — `def:wf:and` reduces
        # to `def:wf`, which is what was meant.
        sub = ""
        if not known(r["label"]):
            parts = r["label"].split(":")
            tail: list[str] = []
            while len(parts) > 2 and not known(":".join(parts)):
                tail.insert(0, parts.pop())
            if tail:
                sub = ":".join(tail)
                r = {**r, "label": ":".join(parts), "sub": sub}
        holders = [d.id for d in docs if r["label"] in labels[d.id]]
        if not holders:
            unresolved.append(r)
            continue
        # a label held by more than one document is settled by the nearest
        # marker, and failing that by document order
        doc = (r["doc_hint"] if r["doc_hint"] in holders else holders[0])
        links.append({**r, "doc": doc, "key": f"{doc}::{r['label']}"})
    return links, unresolved


def attach_pdf_rects(cfg: Config, items: dict[str, TexItem], *,
                     quiet: bool = False) -> int:
    """Locate every item in its compiled PDF via SyncTeX forward search.

    Only the rectangles are recorded.  Page count and page size come from
    pdf.js at read time, which is the authority on what it is drawing.
    """
    from .synctex import SyncTeX, have_text_layout

    # SyncTeX brackets a block rather than measuring it: its bottom is wherever
    # the *next* paragraph starts.  Reading the typeset page pulls that back to
    # the block's own last line, and without it every band on every item runs
    # one line long -- and a block that ends near the foot of a page runs onto
    # the next one.  It is a declared dependency for exactly that reason, so
    # this should be unreachable; when it is not, it has to be said, because
    # the manifest that comes out looks entirely healthy.
    if not have_text_layout():
        print("!! PyMuPDF is not installed, so the page geometry is the raw "
              "SyncTeX bracket:\n"
              "   every highlight will end roughly one line below its "
              "statement.  `pip install pymupdf`.", file=sys.stderr)

    found = 0
    for d in cfg.documents:
        if not d.pdf.exists():
            if not quiet:
                print(f"!! {d.pdf} missing — the paper side will have no page "
                      f"geometry; run `interproof build` (or `pdf`) first",
                      file=sys.stderr)
            continue
        st = SyncTeX(d.pdf, d.root)
        if not st.ok:
            if not quiet:
                print(f"!! no .synctex.gz beside {d.pdf.name} — is -synctex=1 "
                      f"still in this document's latexmk command?", file=sys.stderr)
            continue
        for it in items.values():
            # anchors are located the same way and by the same call: an anchor
            # is a range of source lines, which is what `rect` takes
            if it.doc != d.id or it.kind not in (*cfg.grammar.environments,
                                                 "anchor"):
                continue
            if not st.knows(it.file):
                continue
            it.rect = st.rect(it.file, it.line, it.end_line)
            it.proof_rect = (st.rect(it.file, it.line, it.proof_end)
                             if it.proof_end else None)
            found += bool(it.rect)

        found += attach_spans(cfg, d, items, quiet=quiet)

    tint_siblings(items)
    return found


def attach_spans(cfg: Config, d: Document, items: dict[str, TexItem], *,
                 quiet: bool = False) -> int:
    """Replace the line-granular box of a quoted anchor with its real one.

    Three equations separated by `\\qquad` inside one display share a typeset
    line, and SyncTeX has one box for all of them.  `savepos` asks TeX where
    each actually landed, by compiling a marked copy of the project that the
    reader never sees.  It is only run when a document carries a quoted anchor,
    because it costs a second full LaTeX pass.

    When it cannot answer, the anchor keeps the line it already had: coarser
    than it was written, which is the same bargain the rest of this makes.
    """
    from .savepos import locate

    wanted = [it for it in items.values()
              if it.doc == d.id and it.kind == "anchor"]
    if not any(it.label for it in wanted):
        return 0
    rects, note = locate(cfg, d, quiet=quiet)
    if note and not quiet:
        print(f"!! {d.id}: {note}; those spans keep their line", file=sys.stderr)
    gained = 0
    for it in wanted:
        got = rects.get(it.label)
        if not got:
            continue
        it.rects = [{**r, "end_page": r["page"], "precise": True} for r in got]
        # one box that contains them all, for anything that only needs
        # somewhere to scroll to
        it.rect = {"page": got[0]["page"], "end_page": got[-1]["page"],
                   "top": min(r["top"] for r in got),
                   "bottom": max(r["bottom"] for r in got),
                   "x": round(min(r["x"] for r in got), 2),
                   "w": round(max(r["x"] + r["w"] for r in got)
                              - min(r["x"] for r in got), 2)}
        gained += 1
    return gained


def tint_siblings(items: dict[str, TexItem]) -> None:
    """Give the parts of one statement different colours.

    Three spans of one line are only legible as three if they are told apart,
    and the colour is what carries the correspondence across the gutter: the
    part on the left and the declaration on the right are the same hue.  The
    index is the sibling's position, so it is stable between builds — a colour
    that moved when a part was added would be worse than no colour.
    """
    groups: dict[tuple[str, str], list[TexItem]] = {}
    for it in items.values():
        if it.kind == "anchor":
            groups.setdefault((it.doc, it.parent), []).append(it)
    for group in groups.values():
        for n, it in enumerate(sorted(group, key=lambda x: (x.line, x.label))):
            it.tint = n


# --------------------------------------------------------------------------
# the sources themselves
# --------------------------------------------------------------------------

def rel_to_root(cfg: Config, p: Path) -> str:
    """A path as the artifact will hold it: relative to the project root.

    A document whose root sits outside the project — a paper shared between
    repositories, reached by `../` — cannot keep its own layout inside a folder
    that must stay self-contained, so it is given one under `_outside/`.  The
    alternative is a path that escapes the artifact when unpacked, which is a
    thing an artifact must never do.
    """
    rel = os.path.relpath(p, cfg.root)
    if not rel.startswith(".."):
        return Path(rel).as_posix()
    return "_outside/" + Path(os.path.abspath(p)).as_posix().lstrip("/")


def input_files(doc: Document) -> list[Path]:
    """Every file this document's build actually read, from latexmk's records.

    Asked of the build rather than guessed at: `\\input`, `\\usepackage` of a
    local `.sty`, a preamble one directory up and a `.bib` reached only by
    bibtex are all inputs, and no amount of parsing the configuration finds
    them.  `.fls` is pdflatex's own list; `.fdb_latexmk` adds what the other
    tools in the chain read, which is where the bibliography is.
    """
    out: list[Path] = []
    fls = doc.pdf.with_suffix(".fls")
    if fls.exists():
        pwd = doc.root
        for line in fls.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PWD "):
                pwd = Path(line[4:].strip())
            elif line.startswith("INPUT "):
                out.append(Path(line[6:].strip()))
    fdb = doc.pdf.with_suffix(".fdb_latexmk")
    if fdb.exists():
        for line in fdb.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'^\s+"([^"]+)"', line)
            if m:
                out.append(Path(m.group(1)))
    resolved = []
    for p in out:
        q = p if p.is_absolute() else (doc.root / p)
        try:
            resolved.append(q.resolve())
        except OSError:
            continue
    return resolved


def collect_sources(cfg: Config) -> tuple[list[dict], list[dict], list[str]]:
    """The LaTeX side as the artifact will carry it.

    Text is carried verbatim; anything else is carried as bytes under a budget,
    because the manifest is inlined into a single HTML page and a paper with
    twenty megabytes of figures would make that page unopenable.  What the
    budget drops is named, never silently omitted — and the folder artifact
    still copies it from disk.

    The Lean sources are *not* here: the viewer already carries every module
    verbatim, and carrying them twice would double the artifact for nothing.
    """
    sources: list[dict] = []
    assets: list[dict] = []
    dropped: list[str] = []
    seen: set[Path] = set()
    spent = 0

    for d in cfg.documents:
        # the configured files first, so a document that was never compiled
        # still carries its own sources
        for p in [d.main_path, *d.source_files(), *input_files(d)]:
            try:
                q = p.resolve()
            except OSError:
                continue
            if q in seen or not q.is_file():
                continue
            # never carry the build's own droppings back in
            if is_under(q, cfg.build_dir) or is_under(q, cfg.out_dir):
                continue
            if not is_under(q, cfg.root) and not is_under(q, d.root):
                continue                       # a TeX distribution file, not ours
            seen.add(q)
            rel = rel_to_root(cfg, q)
            if q.suffix.lower() in TEXT_SUFFIXES:
                sources.append({"path": rel,
                                "text": q.read_text(encoding="utf-8", errors="replace")})
            else:
                size = q.stat().st_size
                if spent + size > ASSET_BUDGET:
                    dropped.append(rel)
                    assets.append({"path": rel, "bytes": size, "skipped": True})
                    continue
                spent += size
                import base64
                assets.append({"path": rel, "bytes": size,
                               "b64": base64.b64encode(q.read_bytes()).decode()})
    sources.sort(key=lambda s: s["path"])
    assets.sort(key=lambda s: s["path"])
    return sources, assets, dropped


def is_under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def rev_of(pdf: Path) -> str:
    """A short content hash, so a live reload knows whether the PDF moved.

    Content rather than mtime: latexmk rewrites the PDF on every run it decides
    to make, and a viewer that re-fetched and re-rendered on each of those
    would flicker for nothing.
    """
    if not pdf.exists():
        return ""
    return hashlib.sha1(pdf.read_bytes()).hexdigest()[:12]


# --------------------------------------------------------------------------
# writing, and the report
# --------------------------------------------------------------------------

def write(manifest: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def report(manifest: dict, *, out: Path | None = None) -> None:
    """What the run found, in the terms the reader will meet it in."""
    s = manifest["stats"]
    per = ", ".join(f"{k} {v}" for k, v in s["doc_items"].items())
    print(f"tex items      {s['tex_items']}  ({per})")
    print(f"lean           {s['lean_files']} files, {s['lean_decls']} decls, "
          f"{s['lean_lines']} lines")
    print(f"links          {s['links']} citations -> {s['linked_items']} "
          f"distinct items")
    print(f"references     {s['tex_refs']} between paper items, "
          f"{s['decl_refs']} between declarations")
    print(f"located        {s['located']} items placed in the PDFs by synctex")
    sem = s.get("sem") or {}
    if sem.get("on") and sem.get("failed"):
        # the whole of it was already printed, with what to do about it, when
        # the build gave up on elaborating; this line is the summary
        why = sem["failed"]
        print(f"elaborated     no — {why if len(why) <= 96 else why[:95] + '…'}")
    elif sem.get("on"):
        print(f"elaborated     {sem['modules']}/{sem['of']} modules, "
              f"{sem['tokens']:,} tokens, {sem.get('states', 0):,} proof states, "
              f"{sem['names']:,} names"
              f"  (+{sem.get('bytes', 0) / 1024:.0f} KB in the manifest)")
    print(f"unresolved     {s['unresolved']}")
    for lbl, where in dangling(manifest).items():
        print(f"   ! {lbl:28s} {', '.join(where[:4])}")
    if out is not None:
        print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")


def dangling(manifest: dict) -> dict[str, list[str]]:
    """Citations that resolve to nothing, grouped by what they name."""
    seen: dict[str, list[str]] = {}
    for u in manifest["unresolved"]:
        seen.setdefault(u["label"] or u.get("context", "")[:40],
                        []).append(f"{u['file']}:{u['line']}")
    return dict(sorted(seen.items()))


def duplicates(manifest: dict) -> dict[str, list[str]]:
    """Items claimed as a correspondence by more than one declaration.

    A correspondence says *this declaration is that statement*, and two
    declarations cannot both be it — one of them is talking about it, and the
    protocol's `cf.` is how a citation says so.  Mentions are unlimited; this
    reports only the competing claims, each with where it was made.

    A peeled path is a claim on the *part* it named, not on the statement it
    resolved to: `Proc.params` citing `def:proc:params` does not compete with
    `Proc` citing `def:proc`, but two declarations both citing
    `def:proc:params` compete with each other.
    """
    out: dict[str, list[str]] = {}
    claims: dict[str, dict[str, str]] = {}
    for key, ls in manifest["by_item"].items():
        for l in ls:
            if not (l.get("corr") and l.get("decl")):
                continue
            target = key + (":" + l["sub"] if l.get("sub") else "")
            claims.setdefault(target, {}).setdefault(
                l["decl"], f"{l['decl']} ({l['file']}.lean:{l['line']})")
    for target, who in claims.items():
        if len(who) > 1:
            out[target] = list(who.values())
    return dict(sorted(out.items()))


def covered_items(tex_items, by_item: dict[str, list[dict]]) -> list[str]:
    """Every key something corresponds to, rolled up through the anchors.

    A correspondence to `def:aeval:arith` is a correspondence to part of
    `def:aeval`, so the statement is formalized — partly, which the anchor's
    own band already shows — even when nothing cites the statement whole.
    Mentions do not count: talking about a statement is not formalizing it.
    """
    covered = {k for k, ls in by_item.items()
               if any(l.get("corr") for l in ls)}
    parent_of = {k: f"{it.doc}::{it.parent}" for k, it in tex_items.items()
                 if it.kind == "anchor" and it.parent}
    for k in list(covered):
        p = parent_of.get(k)
        while p and p not in covered:
            covered.add(p)
            p = parent_of.get(p)
    return sorted(covered)
