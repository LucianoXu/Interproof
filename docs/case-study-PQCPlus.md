# Case study: PQCPlus

Interproof's first real pair, and the one every rule in the parsers was learned
from: the PQCPlus papers and their Lean formalization. This document is the
record of that run — what was tried, what the numbers came back as, and which
mistakes are now rules in the code. For what the tool *is*, see the
[README](../README.md).

It began as a feasibility experiment with the material hard-coded, and the
generalisation came afterwards, in that order deliberately: a framework built
before there was one working pair would have generalised the wrong things.

This repository tracks the framework and never the material being read.
`sandbox/` holds read-only copies of the PQCPlus sources and is untracked;
**a fresh clone of the case study starts with `make sync`**, then `make`.

## What this was testing

The Interproof premise: *does a synchronized informal ↔ formal view actually make
an unfamiliar Lean proof faster to read?* If it does not, the project's motivation
does not hold, and this experiment costs days instead of weeks to find out.

## Tool decision

Surveyed: leanblueprint, Verso Blueprint, LeanArchitect, Alectryon/LeanInk,
SubVerso, span, Lean Atlas, doc-gen4.

**Adopted: `span`'s data model** — a checked `label ↔ declaration` manifest — and
nothing else. The viewer is ~900 lines of local code over pdf.js.

The deciding facts, all specific to this project:

- The correspondence **already exists, pointing Lean → LaTeX**. PQCPlus's Lean
  docstrings carry ~120 `P3:<label>` / `note, <label>` citations. leanblueprint
  wants the opposite direction (`\lean{}` markers inside the LaTeX), which means
  discarding that asset and annotating an actively-edited paper instead.
- leanblueprint's output links a theorem to its **doc-gen4 API page**; it never
  shows the proof body. Reading proof bodies is the thing under test.
- doc-gen4 would mean a full mathlib documentation build on top of an already
  7.3 GB `.lake`. Disproportionate for an experiment.
- Verso Blueprint requires the prose to live inside Lean. P3 is a real LaTeX
  paper with a 113-macro preamble and `mathpartir` rule displays; porting it is
  a rewrite, not an experiment.
- LeanArchitect generates LaTeX from Lean. We already have better LaTeX.
- **SubVerso** (not LeanInk, which is stalled) is the correct upgrade for
  per-tactic goal states — deliberately deferred: it is a build-time,
  version-coupled dependency, and the MVP needs no Lean build at all.

The paper side was first re-rendered from LaTeX source with KaTeX. That was
wrong, and replacing it is the one structural change since: a 113-macro
preamble, `mathpartir` rule displays and `\inferrule` do not survive
re-rendering, and every approximation is a place where the reader cannot trust
what they are looking at. **The paper pane now shows the compiled PDF itself**,
scrolled to the item and banded, with `synctex` supplying `label → page,
rectangle`. Fidelity is exact by construction, and the macro table, the
LaTeX→HTML translator and 644 KB of KaTeX all left with it.

## Pipeline

```
make sync       # refresh sandbox/ from the live PQCPlus project
make            # interproof build: pdf + manifest + folder, ~25 s cold, ~3 s warm
make serve      # the same, live, rebuilt as the sources are edited
make check      # the correspondence as a report, with an exit code
```

The configuration for this pair is the repository's own untracked
`interproof.toml`, which points at `sandbox/`. It is the whole of what ties the
build to these two papers.

`interproof/tex.py` and `interproof/lean.py` parse both sides as **source
text**:

- *LaTeX*: every labelled `theorem/lemma/definition/…` environment with its
  statement, its following `proof`, its section path, its source line span, and
  the labels it cites — from the proof as much as the statement, since a proof
  citing a lemma is what a dependency *is*. What cites an item is nowhere in
  the source, only in the sum of every other item's `\Cref`s, so it is
  inverted here.
- *Lean*: declarations with docstrings, module docstrings, `/-! ## … -/` section
  headers, and every citation occurring **in a comment**, resolved against the
  two label universes. Ambiguous labels are disambiguated by the nearest `P3` /
  `note` marker; unresolvable ones are reported as dangling — that report is the
  `span`-style consistency check. A module is keyed by its path under the
  formal root rather than by its file name, so a source tree with
  subdirectories survives into the index instead of being flattened.

  The declarations' own reference structure is read the same way: the names a
  declaration writes **in its code** that resolve to another declaration. This
  is a name match, not elaboration — it cannot see a lemma that a `simp` set
  applied for you, and a local binder sharing a declaration's name reads as a
  use. Comments are excluded: a name discussed in a docstring is prose, and the
  citations that matter there are already harvested as paper links.

  Modules are then put in **import order** — each after everything it imports,
  ties by depth — and every list in the viewer uses it. Alphabetical order is
  the file system's and says nothing about the development: it opens on
  `Ambient` only by luck of the letter A, and interleaves the layers, so
  scrolling the index tells you nothing about what is built on what. In import
  order the index reads as the development does, from the ambient state to the
  interaction theorem. Which imports are internal is not assumed: the
  root prefix (`PQCPlus.`) is whatever prefix the imports that resolve agree
  on, so nothing here knows the package's name either.

  A citation takes three forms in these sources, and all three count: the
  canonical `note, def:proc-decl`, and the two that name the item by **title** —
  `note, Def. procedure declaration` and `Definition (frame lifting)`. Title
  matches must agree on the environment kind, so `Lemma (locality)` does not
  resolve to `def:local`. A citation in the `/-- … -/` docstring above a
  declaration belongs to that declaration, not to the module.

  Which is also the citation's **extent**, and the right pane bands it. Two
  rules, both learned by looking at bands that were wrong. Whether a
  declaration has a docstring is asked of the comment spans, not guessed from a
  line ending in `-/`: a `/-! ## … -/` section header ends that way too, and
  taking one for a docstring sends the search back to the previous
  declaration's `/--`, so the band starts forty lines early with a whole
  declaration inside it. And a citation in module prose, which no declaration
  owns, extends over the **comment block that does the citing** — one band per
  block, never the hull of several. `lem:one-sided` is named in `StepLemmas`'
  header and again at a section break six hundred lines down; those are two
  places, and the file between them cites nothing.

`interproof/synctex.py` then places each item in its PDF. SyncTeX brackets a block
rather than measuring it: the `\begin` line is a reliable top, but `\end` is
credited with boxes inside the block as readily as with the paragraph after it,
so it is not a body line and cannot be trusted as a bottom either. The bracket
therefore only decides which typeset lines belong, and those lines' own extent
sets the band. Three rules make that hold up on real pages:

- a line counts when its **midpoint** is inside — which keeps the head line,
  whose ascender rises above SyncTeX's box, and rejects the next paragraph's
  first line, which starts above the bracket;
- a bottom on the **next page does not prove the block reached it**: a block
  ending near the foot of a page is bracketed by the first line of the
  following one. If that page holds none of the block's lines, the span
  collapses — otherwise the band would run to the page edge;
- the **folio is not content**. A one-line block holding nothing but a number
  sits close enough under a block ending low on the page to be mistaken for
  part of it.

All 46 items land within 1pt of the last line of their block.

## Retargeting

Nothing outside the configuration knows which documents exist. The viewer, the
geometry, the Lean parser and the site build all ask rather than assume — a
property this run had before there was a configuration file, because the
document set was already one table, and that is what made generalising it an
afternoon rather than a rewrite.

- **`interproof.toml`** — the document set: id, title, source root, files, what
  latexmk compiles, and the markers a Lean comment uses to name the document
  (`P3`, `note`, `EasyPQC`). The PDF build, both parsers, the manifest's `docs`
  section and the viewer's captions all derive from it.
- **`make sync`** — where the raw material is fetched from, which is a fact
  about the PQCPlus layout rather than about the documents, and the one step
  peculiar to a case study whose sources live in another project.

A third document is another `[[document]]`; there is no "the other document"
anywhere. What no design can supply is the correspondence itself: point it at a
Lean codebase whose docstrings never cite a paper and the manifest comes back
empty. `span`'s data model is general; having something to populate it is the
precondition.

## Reading the page

- **Paper → Lean** (default): pick a statement; the right page opens the module
  that cites it, scrolled to the declaration and banded. Other declarations
  citing the same statement are banded dimly, and named in the strip above; a
  name from another module switches the file.
- **Lean → Paper**: pick a declaration; the left page marks every paper item it
  cites at once, focused one first.
- **Files**: the third index, and the only one that does not go through the
  correspondence — the sources as they sit on disk. The papers as a flat list,
  the Lean modules in their directory tree. Picking a document opens it whole
  on the left, picking a module opens it whole on the right, nothing banded,
  each side set independently. Two directional modes drive both pages from one
  selection; this one lets the reader put an arbitrary paper beside an
  arbitrary module, which is the one pairing the citations cannot arrange.
  The modules are in import order, and what a module imports is named above
  the pane and followable.
- **References**, above each page and on both sides: what the thing you are
  reading rests on, and what rests on it — `cites` / `cited by` for a paper
  item, `uses` / `used by` for a declaration. The two directions are separate
  rows, because they answer different questions and one undifferentiated list
  of neighbours answers neither. Every name is followable, so a proof can be
  walked backwards to its hypotheses on either side.

  On the Lean side the rows are **restricted to declarations that carry a
  citation of their own** — 62 of the 906. A proof rests on a hundred names and
  nearly all of them are plumbing: `CqState` alone is used by 152 declarations,
  which is a fact about the semantic domain, not about the correspondence the
  reader came for. Filtered, the longest `used by` is 21. What is left out is
  counted (`+137 uncited`) and one click away, never silently dropped — the
  same click opens a row cut for length. A reference to a *section* is named
  but not offered, since only labelled statements are placed in the PDF.
- **Formalized** (`a`): a standing overlay that marks *every* item with a Lean
  counterpart, in green, at once — under the selection band and independent of
  it. The reading modes answer "where is this one item"; this answers the
  question asked before that one, and answers it on the page itself: how much
  of this paper has been mechanized, and which parts. A gap reads as a gap —
  an unmarked block between two marked ones — rather than as an absence from a
  list. This replaced a coverage table of every item × every module, which
  answered the same question a page away from the thing it was about, and in a
  grid whose cells the reader had to translate back into statements. The count
  each rail row already carries says the rest. The marks are the only
  clickable ones: a click opens that item's
  declaration on the right, so the paper becomes an index into the Lean
  sources. `\Cref` links stay on top of the overlay and still follow.
- **Clean** (`c`): the index, both header bars and the reference rows put away,
  leaving the two documents and the marks on them. Apparatus is what you want
  while deciding what to read and what is in the way once you are reading it.
  The rail is hidden rather than removed, so `j`/`k` still walk the selection
  with it off screen; `/` brings it back, since asking to filter is asking for
  the index.
- Both pages are whole documents scrolled, not extracts: the left is the
  compiled PDF (`+` `−` `fit` zoom, **with proof** extends the band over the
  proof that follows), the right is the `.lean` file with its line numbers. A
  declaration read without what surrounds it is a declaration read without its
  place in the module.
- `/` filter · `j`/`k` move · `a` formalized · `c` clean · citations are
  clickable in both directions, and so are the `\Cref` links inside the PDF
  itself · the URL hash deep-links an item.

## What the run says about PQCPlus

134 citations (14 of them by title), 0 dangling, 906 Lean declarations over
18,413 lines in 14 modules; all 46 labelled statements located in the PDFs.
Within the sides: 54 cross-references between paper items, 4,472 name edges
between declarations.
20 of 28 P3 statements and 14 of 18 note statements have a Lean counterpart.

Reading only canonical `kind:label` citations had put the note at 8 of 18. The
six recovered — `def:proc-decl → ProcDef`, `def:cq-statements → Stmt`,
`def:adv-decl`, `def:instantiation`, `def:adv-call`, `def:local` — are the core
syntax and semantics definitions, and they were never uncited; they were cited
in a form nothing was reading.

What is left uncovered is not noise. On the note side `def:cq-semantics` and
`def:proc-call` are *described* in `Semantics.lean`'s module docstring, formula
and all, but never named — a citation genuinely missing from the Lean source,
not a reader gap. `lem:comb` is explicitly out of scope. On the P3 side
`prop:swap`, `cor:yaeasypqc`, `lem:fundamental` are precisely the open items in
`LeanOracleAdvSpec.md` §4.

## Known limits

- Statement-level granularity. Proof-body ↔ tactic-block alignment — the actual
  research contribution Interproof would make — is **not** here yet.
- No goal states and no hover types. Both need elaboration, so both are the
  same threshold — a Lean build in the pipeline — and SubVerso crosses it once
  for both. Everything here is source text; the syntax colouring is a
  tokenizer, not Lean's grammar.
- Citations are trusted, not verified: nothing checks that a Lean declaration
  really states what the cited paper item says. The same holds one level down:
  the `uses` graph is what the source *names*, which is a good approximation of
  what a proof depends on and not the same thing.
- The band is only as good as SyncTeX's line attribution. It is checked against
  the page text, but an item whose `\begin` is inside a macro would drift.
- `\Cref`s are clickable inside the P3 PDF only: the note is built without
  `hyperref`, so its cross-references carry no link annotations to follow. The
  `cites` strip above the page works for both.
- Under `file://` pdf.js runs in the main thread: a blob-URL worker inherits the
  opaque origin and is refused, and pdf.js hangs rather than falling back. Served
  over http it takes the real worker.
