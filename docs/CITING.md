# Citing a paper from a formalization

This is the interface of Interproof. Everything else — the reader, the page
geometry, the two indexes — is machinery over one fact: **a declaration in your
formal sources says which statement of the paper it is.**

Nothing has to be annotated twice, and nothing has to be annotated in the
paper. Point Interproof at a formalization whose comments never name a paper
and the correspondence comes back empty; that is not a failure of the tool, it
is the precondition. This document is what you hand to whoever writes the Lean.

The rule in one line: **name the paper's statement, in a comment, next to the
declaration that is it.**

---

## The three forms of a citation

All three are read, and all three count. Use whichever reads best in the
sentence you were going to write anyway — that is the point of having three.

### 1. By label — the canonical form

```lean
/-- The one-sided step lemma.  See P3:lem:one-sided. -/
theorem step_one_sided : … := …
```

`P3` names the document; `lem:one-sided` is the `\label{}` in its LaTeX. The
document marker and the label do not have to be adjacent, and the punctuation
around them is free:

```lean
/-- P3, Lemma lem:one-sided -/
/-- (see `note, def:proc-decl`) -/
/-- Formalizes def:cq-semantics of the note. -/
```

A label is recognised by its prefix (`thm:`, `lem:`, `def:`, …). Which prefixes
exist is `[grammar] label_prefixes` in `interproof.toml` — a project that
writes `t:foo` says so there.

A citation may name a *clause* of a numbered statement: `def:wf.3` is clause 3
of `def:wf`, and resolves to `def:wf` with the clause recorded. A trailing dot
that is really sentence punctuation is not mistaken for one.

### 2. By kind and title

```lean
/-- note, Def. procedure declaration -/
/-- This is Definition (frame lifting). -/
```

These name the item by the title in its optional argument —
`\begin{definition}[frame lifting]` — rather than by its label. They are just
as much a citation, and a formalization written by someone reading the paper
tends to produce them naturally.

**A title citation must agree on the kind.** `Lemma (locality)` will not
resolve to `def:local`, even though the title matches. This is deliberate: the
kind is the only redundancy available to catch a title that means something
else, and a citation that silently attaches a lemma to a definition is worse
than one that does not resolve.

Which words spell which kind is `[grammar.kind_words]`; the default covers
`Definition`/`Def.`, `Lemma`/`Lem.`, `Theorem`/`Thm.`, `Proposition`/`Prop.`,
`Corollary`/`Cor.`, `Remark`/`Rem.`

---

## Which document a citation names

When two documents hold the same label — two papers both with a `def:state` —
the citation is settled by the **nearest document marker before it**:

```lean
/-- note, def:state — the note's version, not the paper's. -/
```

A marker is a regular expression in the document's `markers`, and the default
is the document's `id`. Spelling out `markers = ['\bP3\b', 'EasyPQC']` is worth
it when the sources call a document by more than one name.

**"Nearest" means within the 90 characters before the citation.** Roughly a
sentence: `note, def:state` and `See def:state in the note` both work,
`The note develops … three sentences … def:state` does not. If you want a
citation attributed to a particular document, put the name in the same clause.

With no marker in range, the first document in configuration order wins. That
is a guess, and the only place in this pipeline that guesses — if it matters to
you, write the marker.

Two things worth knowing about the default:

- An `id` that is an ordinary English word (`note`, `paper`) will match prose
  that was not naming the document at all. It costs nothing when the label is
  held by one document, which is the usual case; it only decides ambiguous
  ones. If your documents share labels, give them markers that cannot occur by
  accident.
- Markers are **only** consulted for ambiguity. A label that exactly one
  document holds resolves without any marker at all, which is why most
  citations need no ceremony.

---

## Where a citation may sit, and what it means there

Only **comments** are read. A name occurring in code is a use of a declaration,
not a citation of a paper; those are harvested separately and shown as the
`uses` / `used by` rows.

### In the docstring above a declaration

```lean
/-- Frame lifting.  note, Definition (frame lifting). -/
def lift (f : Frame) : … := …
```

The citation belongs to `lift`. The docstring counts as part of the
declaration, so the reader's band covers the prose and the code together —
which is right, because the prose is where you said what it formalizes.

An `@[simp]` attribute between the docstring and the declaration changes
nothing.

### In module prose

```lean
/-!
## Step lemmas

Everything in this section is P3, Section 4: lem:one-sided and lem:two-sided
are proved here, cor:adv-local follows.
-/
```

No declaration owns these, so they are module-level citations, and their extent
is **the comment block that does the citing** — one band per block, never the
hull of several. If `lem:one-sided` is named in the module header and again at
a section break six hundred lines down, those are two places, and the file
between them cites nothing.

### What this means for you

Put the citation where the correspondence actually is. A citation in the module
header claims the whole header, not the whole module; a citation on the
declaration claims the declaration. Both are useful, and they say different
things.

---

## What is checked, and what is not

`interproof check` reports:

- **dangling** — a citation naming a statement no document holds. This is an
  error and fails the command, which is what makes it worth putting in CI: a
  dangling citation means one side was renamed and the other was not, and the
  cheapest moment to learn that is the commit that did it.
- **unlocated** — a statement whose place in the PDF SyncTeX could not find.
  The reader still works; that item cannot be scrolled to.
- **uncovered** — a statement with no counterpart at all. Not an error: this is
  the state of the mechanization, and showing it is half of what the reader is
  for. `--strict` turns it into one, for a project that has decided otherwise.

What is **not** checked: that a declaration really states what the statement it
cites says. Citations are trusted. Interproof puts the two texts side by side
so that a reader can check it in a second, which is a different and more honest
thing than claiming to have checked it.

There is also **no way to mention a label without citing it.** A comment that
discusses `def:triple` — "unlike `def:triple`, this version is total" — is read
as a citation of it, because nothing distinguishes the two. Usually that is
what you wanted: the declaration really is *about* that statement. When it is
not, name the statement in words rather than by label.

---

## Conventions that make the reading better

None of these are required; all of them cost one line.

- **Cite on the declaration, not only in the header.** The header tells the
  reader what the module is about; the declaration tells them what *this* is.
- **Cite the definition too, not just the theorems.** Definitions are where a
  reader loses the thread, and they are the cheapest to match.
- **When a statement is deliberately out of scope, say so in prose** near where
  it would have gone. `interproof check` will still count it uncovered — that
  is correct — but the next reader will know it was a decision.
- **Keep the `\label` stable.** It is the join key. Renaming a label is a
  breaking change to the correspondence, and `interproof check` is what tells
  you how much broke.
- **One citation per declaration is normal; several are fine.** A declaration
  that formalizes two statements at once cites both, and the reader marks both
  on the page at once.
