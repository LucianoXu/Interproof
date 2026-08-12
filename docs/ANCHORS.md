# Anchors: correspondence below the statement

[CITING.md](CITING.md) is the protocol as it stands: a declaration cites a
paper's statement by its `\label`. This document is the design for the layer
under that — a citation that names **one clause of a definition, one production
of a grammar, one premise of a rule** — and the reasoning that settled each
choice, including the parts not built yet.

It is written down because the decisions are the expensive part. The code that
follows from them is not.

---

## What the layer is for

A paper's definition has conditions and a grammar has productions, and a
formalization matches them one by one. Today the finest thing either side can
name is a whole statement against a whole declaration, so that structure — the
part a reader most wants checked — is exactly the part the reader cannot see.

Two ends have to meet:

- **The paper side** must be able to name a part of a statement, and that part
  must be locatable in the compiled PDF.
- **The formal side** must be able to name a part of a declaration.

They turn out to be very different problems, and the asymmetry is the whole
design.

---

## The formal side: use the names Lean already gives

**Decision: identifiers, not marked-up spans.**

Lean names almost everything below a declaration — constructors, structure
fields, binders, and, written in structured style, proof cases. Where a name
exists, using it beats quoting the text around it:

- a name survives reformatting, and a quoted source string does not, which
  matters because Lean sources churn hard during an active formalization;
- a name cannot match the wrong occurrence;
- and it needs **no new syntax at all**. Members are read off the source, and
  the existing rule — *a citation in the docstring above X belongs to X* —
  takes it from there.

```lean
inductive Cmd where
  | skip : Cmd
  /-- The loop: paper:def:cmd:while. -/
  | whileDo : BExp → Cmd → Cmd
```

`Cmd.whileDo` is a declaration in the manifest, with its own line span, its own
signature, and its own citations. The band in the reader covers that
constructor, not the datatype.

**Built** (`interproof/lean.py`): `inductive` constructors and `structure` /
`class` fields, each with the docstring above it, keyed `Parent.member` and
carrying `parent`. Citation ownership is **innermost-wins**, because a member's
span sits inside its parent's and first-match would hand every citation to the
parent.

**Not built, and deliberately**: a directive that marks an arbitrary span of
Lean source by quoting it —

```lean
-- @interproof span def:wf:dom = "∀ x ∈ W, s x = t x"
```

This is the escape hatch for what identifiers cannot reach: an unnamed conjunct
in `def P : Prop := A ∧ B ∧ C`, an unstructured `· simp [...]` step. It is kept
in reserve rather than built, because building it first would make it the path
of least resistance and fill the sources with brittle quoted strings where a
name belonged. If it is ever built it reuses the paper side's text matching and
adds one hard rule: **the quoted text must occur exactly once** in the
enclosing declaration, or it is an error rather than a guess.

The pressure the restriction creates is the right pressure. A clause worth
citing is a clause worth naming — the same argument that removed citation by
title.

---

## The paper side: comments only, and a compiled copy

**Decision: annotations are LaTeX comments. Never macros.**

The source on disk must compile anywhere, for a co-author who has never heard
of Interproof, on arXiv, in Overleaf, with no package to install. A macro fails
all of that, and a macro misbehaving inside `mathpartir` or `align` — precisely
where fine correspondence is wanted — is the worst place to debug.

```latex
% @interproof span def:wf:dom = "\dom(\sigma) = W"   general form: quote the source
% @interproof span def:cmd:while                      shorthand: claim the next line
```

The general form quotes the source text and Interproof finds it; the shorthand
claims the following source line. A quoted span that is not found is a dangling
anchor and is reported — it fails loudly, which is the property that matters.

Ordinal addressing — *"the 2nd `\item`"*, *"premise 3"* — is **rejected**. It
re-points silently when an author inserts a condition, which is the same
failure mode that removed citation by title.

### Where the marked text lands in the PDF

This is the hard half, and it was settled by measurement rather than argument.

**SyncTeX cannot do it.** Its unit is the typeset line. Two conditions written
on separate source lines that share a typeset line come back as the *identical
full-width box*:

```
source line 11  ->  h:133.77  v:194.94  W:343.71
source line 12  ->  h:133.77  v:194.94  W:343.71
```

No amount of post-processing recovers a sub-line position that is not in the
data. (Display math is better: `align` rows come back tight.)

**The PDF text layer is not a general fallback.** Extracted math reads `σ |= P`,
`⟨c, σ⟩⇓τ`; matching that from `\sigma \models P` is a different alphabet.
Usable for prose, not for conditions, and conditions are mostly math.

**The answer is to compile a marked private copy.** Interproof already builds
into `.interproof/build/`. The comment directives are expanded *there* into
`\pdfsavepos` plus a deferred `\write`, and the coordinates land in the `.aux`.
The file on disk keeps not one macro.

Measured on a real compile:

```
wf.dom      x 196.0 -> 253.9pt, same baseline     [ dom(σ) = W,]
wf.finite   x 463.4 -> 371.7, y 190.2 -> 202.2    [wraps; both ends exact]
cmd.while   x 293.0 -> 343.7pt                    [align row]
r.p2        x 311.3 -> 351.1pt                    [premise inside \inferrule]
```

and, comparing the marked build against the clean one, **99 words at identical
positions, zero difference**. The reader's PDF is the author's PDF.

Three constraints that fall out and must be honoured by any implementation:

1. **Line numbers must be preserved.** A directive occupies its own comment
   line, and the private copy *replaces* that line rather than deleting it.
   Every existing item's SyncTeX geometry is line-based and would shift
   otherwise.
2. **Failure falls back and says so.** If the marked copy does not compile, use
   the clean build and coarse geometry, and print the reason. Elaboration set
   this precedent; anchors follow it.
3. **`\pdfsavepos` gives a point on the baseline, not a box.** Height comes
   from the enclosing typeset line and a wrapped span's middle rows need the
   text block's edges — both already available from the PyMuPDF layout that
   `synctex.tighten` uses.

---

## Paths

**Decision: colon-separated, free-form.**

`def:wf:dom` is a part of `def:wf`. A segment must start alphanumeric, so
ordinary sentence punctuation — `def:wf: it holds` — never looks like one.

**No built-in taxonomy.** Not `def:wf:cond:dom`, not `def:rules:premise:2`. The
vocabulary for *condition* / *premise* / *constructor* differs by field and by
paper, and any fixed word list is wrong for somebody. What the reader actually
needs is the parent-child relation, and a path is that. A role, if it is ever
worth recording, becomes an optional attribute of the anchor — never part of
its name.

The relation is what pays:

- **roll-up** — citing `def:wf:dom` also marks `def:wf`, at a coarser band;
- **two-level coverage** — *"`def:cmd`: 4 of 5 constructors formalized"*;
- **dangling detection for children** — `def:cmd:whlie` is caught because the
  parent exists and the child does not.

**Built now: peeling.** A path whose tail names nothing yet resolves to the
longest prefix that does, and the tail is recorded as `sub` on the link. So a
formalization can write `paper:def:cmd:while` today: it links to `def:cmd`, and
it sharpens by itself the day the paper carries the anchor — with no edit to
the Lean. Peeling from the right is also what keeps a sentence out of a label.

---

## The reader

**The paper side needs no work.** The reader shows the compiled PDF, and
`sources` is only used to build the download archive — there is no LaTeX source
pane. A `%` directive is never in front of a reader. That falls out of showing
the PDF instead of re-rendering it.

**The formal side shows the file verbatim, so it does.** Citations are already
rendered as clickable chips (`cite()`, `leanview.js`). Two fixes went with this
work:

- the prefix list was hard-coded in the page while `label_prefixes` is
  configurable, so a project writing `t:foo` was linked by the build and shown
  as plain text by the reader. The page now takes the list from the manifest
  (`grammar.label_prefixes`).
- on the elaborated path, text *between* tokens never reached `cite()`, so a
  citation in a region Lean emitted as unparsed text was a link with the
  tokenizer and dead text with the overlay. Both paths now cite.

A future `-- @interproof …` directive line collapses to a one-line chip, under
one hard constraint: **the rendered output must keep one line per source line.**
`leanview.js` bands by arithmetic — `top = (from - 1) × lineHeight` — against a
separate gutter of one row per line. Any inserted newline, hidden line, wrapped
line, or per-line height change desynchronizes every band below it. So: a
one-line directive renders as a one-line chip, an inline citation as an inline
chip, and the raw text stays retrievable (Clean mode is the natural home).

---

## Order of work

Each step ships on its own, and the heaviest machinery comes last, when the
steps before it have shown it is needed.

1. **Lean-side members** — done. No geometry, purely additive.
2. **Anchors on line-addressable things** — done. `% @interproof anchor <path>`
   claims source lines, and SyncTeX locates them with the call it already had.
3. **`\pdfsavepos` injection** — true inline spans. Not built.

### What step 2 measured

It was supposed to answer whether the correspondence people want at this
granularity is one that is line-addressable. On the tracked example the answer
came back **both ways**, which is the useful outcome:

- `def:aeval` is an `enumerate` of two `\item`s, and they are cleanly
  addressable — one lands on page 1, the other on page 2. Anchored, they band
  5.0% and 10.5% of a page against the statement's 18.4% + 20.3% across a page
  break. That is the whole feature working.
- `def:cmd` is a BNF grammar written `\[ c ::= \skipk \mid x := a \mid … \]`.
  Its five productions sit on five *source* lines and one *typeset* line, and
  SyncTeX returns **the identical box for all seven lines of the display**.
  Step 2 cannot touch it.

So the demo now carries one of each, on purpose: `paper:def:aeval:arith`
resolves to a real anchor with a tight rectangle, and `paper:def:cmd:while`
peels to `def:cmd` because the paper has nowhere finer to point. The second is
not a failure — it is the graceful degradation the peeling rule exists for, and
it is what step 3 would upgrade.

The cheap fix for a grammar like `def:cmd` is not always step 3, either:
rewriting the display as an `align` with one production per row makes it
line-addressable, at the cost of a taller display. Whether that is worth doing
is the author's call, and it is worth knowing it is available before paying for
`\pdfsavepos`.
