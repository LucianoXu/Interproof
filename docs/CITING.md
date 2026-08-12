# Citing a paper from a formalization

This is the interface of Interproof. Everything else — the reader, the page
geometry, the two indexes — is machinery over one fact: **a declaration in your
formal sources says which statement of the paper it is.**

Nothing has to be annotated twice, and nothing has to be annotated in the
paper. Point Interproof at a formalization whose comments never name a paper
and the correspondence comes back empty; that is not a failure of the tool, it
is the precondition. This document is what you hand to whoever writes the Lean.

The rule in one line: **name the paper's statement, by its `\label`, in a
comment, next to the declaration that is it.**

---

## What a citation is

A citation is a `\label` written in a comment. That is the whole form, and it
is the only one.

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

A citation may also name a **part** of a statement by path — `def:wf:dom`,
`def:cmd:while`. If the paper carries an anchor by that name the citation
resolves to it and the reader bands that part alone; if it does not, the tail
is peeled and the citation resolves to the statement, with the part recorded.
So a path is always safe to write, and it sharpens by itself the day the paper
is annotated. Anchors are **[docs/ANCHORS.md](ANCHORS.md)**.

### Why only the label

An earlier version also read a statement named by its **kind and title** —
`Def. procedure declaration`, `Definition (frame lifting)` — matched against
the optional argument of the environment. It read well, and it was removed.

A title is prose. It recurs in sentences that are discussing the subject rather
than citing the statement, it collides across documents, and a one-word title
(`[soundness]`, `[locality]`) matches almost anything. The failure was not that
it missed citations; it was that it *found* them, in the wrong places, and gave
them the wrong extent — so the band in the reader covered text that had nothing
to do with the declaration. A correspondence that is wrong in a way the reader
cannot see is worse than one that is merely incomplete.

A `\label` does not have that problem, because it is an identifier the author
deliberately made one. If a statement is worth citing from the formalization,
it is worth giving a label.

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
/-- Frame lifting.  note, def:frame. -/
def lift (f : Frame) : … := …
```

The citation belongs to `lift`. The docstring counts as part of the
declaration, so the reader's band covers the prose and the code together —
which is right, because the prose is where you said what it formalizes.

An `@[simp]` attribute between the docstring and the declaration changes
nothing.

### In the code

```lean
theorem update_comm … := by
  -- Extensionality in `z`: note, lem:update-comm:ext.
  funext z
```

A comment inside a declaration's code belongs to that declaration, exactly as
the docstring does.  Where this earns its keep is a proof: the paper's proof
carries anchors on its sentences ([ANCHORS.md](ANCHORS.md)), the Lean proof
cites them on the tactic steps that are those sentences, and the reader
crosses between the two mid-proof — the chip sits on the step, and the band
in the paper is the sentence.

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
- **duplicate** — a statement claimed as a correspondence by two declarations.
  Also an error: a correspondence is one to one, and the claims that are
  really commentary should say `cf.`.
- **unlocated** — a statement whose place in the PDF SyncTeX could not find.
  The reader still works; that item cannot be scrolled to.
- **uncovered** — a statement nothing corresponds to. Mentions do not cover:
  talking about a statement is not formalizing it. Not an error: this is
  the state of the mechanization, and showing it is half of what the reader is
  for. `--strict` turns it into one, for a project that has decided otherwise.

What is **not** checked: that a declaration really states what the statement it
cites says. Citations are trusted. Interproof puts the two texts side by side
so that a reader can check it in a second, which is a different and more honest
thing than claiming to have checked it.

## Correspondence and mention

A citation owned by a declaration is a **correspondence**: it claims the
declaration *is* the statement it names.  A comment that merely discusses one
— "unlike `def:triple`, this version is total" — is making a different claim,
and says so by writing `cf.` in the clause before the label:

```lean
/-- Substitution into an assertion: paper:def:subst.  Composition with an
update (cf. note, def:update), because assertions here are semantic. -/
```

A `cf.` citation is a **mention**.  It still links, in both directions, and
the reader still follows it; it does not claim the declaration formalizes the
statement, does not count toward coverage, and the viewer dims it and says
`cf.` on the chip.  Module prose can only mention — no declaration owns it.

**A correspondence is one to one.**  Two declarations claiming the same
statement contradict each other — at most one of them is it, and the other is
talking about it — so `interproof check` fails on the pair and names both
claims with their files and lines; demoting one to `cf.` is the fix.  Two
qualifications, both deliberate:

- a **path** claims the part it names: `Proc.params` citing `def:proc:params`
  never competes with `Proc` citing `def:proc`, anchor or no anchor;
- the **other direction is free**: one declaration may correspond to several
  statements — a definition that is three equations at once cites all three,
  and each equation still has exactly one formalization.

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
