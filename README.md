# Interproof — feasibility experiment

A **sandboxed** dual-view reader for one informal/formal pair: the PQCPlus papers
and their Lean formalization. Nothing here writes back into
`assets/1-projects/PQCPlus/`; `sandbox/` holds read-only source copies.

This repository tracks the framework — the reader, the extractor, the build —
and never the material being read. `sandbox/` and the PDFs compiled from it are
untracked; **a fresh clone starts with `make sync`**, which populates them from
the live PQCPlus project, and then `make`.

Open `site/index.html` in a browser. It is one self-contained file — no server,
no network, no Lean toolchain. Rebuilding it needs a LaTeX installation, because
the paper side *is* the compiled PDF.

## What this is testing

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
make            # pdf + extract + build, ~25 s cold, ~3 s warm
make pdf        # sandbox/tex/  ->  stignore-build/{P3,note}/main.pdf + .synctex.gz
make extract    # sandbox/ + the PDFs  ->  site/manifest.json
make site       # manifest + PDFs + assets -> site/index.html (single file)
make sync       # refresh sandbox/ from the live PQCPlus project
make distclean  # also drop the compiled PDFs
```

`tools/extract.py` parses both sides as **source text**:

- *LaTeX*: every labelled `theorem/lemma/definition/…` environment with its
  statement, its following `proof`, its section path, and its source line span.
- *Lean*: declarations with docstrings, module docstrings, `/-! ## … -/` section
  headers, and every citation occurring **in a comment**, resolved against the
  two label universes. Ambiguous labels are disambiguated by the nearest `P3` /
  `note` marker; unresolvable ones are reported as dangling — that report is the
  `span`-style consistency check.

  A citation takes three forms in these sources, and all three count: the
  canonical `note, def:proc-decl`, and the two that name the item by **title** —
  `note, Def. procedure declaration` and `Definition (frame lifting)`. Title
  matches must agree on the environment kind, so `Lemma (locality)` does not
  resolve to `def:local`. A citation in the `/-- … -/` docstring above a
  declaration belongs to that declaration, not to the module.

`tools/synctex.py` then places each item in its PDF. SyncTeX brackets a block
rather than measuring it — the `\begin` line is a reliable top, but `\end` is
credited with boxes both inside the block and in the paragraph after it — so the
bracket only decides which typeset lines belong, and those lines' own extent
sets the band. A line counts when its midpoint is inside, which keeps the head
line (whose ascender rises above the box) and rejects the next paragraph's
first.

## Reading the page

- **Paper → Lean** (default): pick a statement; the right page shows every Lean
  declaration that cites it, docstring first, source folded.
- **Lean → Paper**: pick a declaration; the left page marks every paper item it
  cites at once, focused one first.
- **Coverage** (`g`): every labelled item × every Lean module. Also lists the
  items with no Lean counterpart at all.
- The left page is the compiled document, scrolled continuously. `+` `−` `fit`
  zoom; **with proof** extends the band over the proof that follows.
- `/` filter · `j`/`k` move · citations are clickable in both directions, and so
  are the `\Cref` links inside the PDF itself · the URL hash deep-links an item.

## What the run says about PQCPlus

134 citations (14 of them by title), 0 dangling, 906 Lean declarations over
18,413 lines in 14 modules; all 46 labelled statements located in the PDFs.
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
- No goal states (needs SubVerso).
- Citations are trusted, not verified: nothing checks that a Lean declaration
  really states what the cited paper item says.
- The band is only as good as SyncTeX's line attribution. It is checked against
  the page text, but an item whose `\begin` is inside a macro would drift.
- `\Cref`s are clickable inside the P3 PDF only: the note is built without
  `hyperref`, so its cross-references carry no link annotations to follow. The
  `cites` strip above the page works for both.
- Under `file://` pdf.js runs in the main thread: a blob-URL worker inherits the
  opaque origin and is refused, and pdf.js hangs rather than falling back. Served
  over http it takes the real worker.
