# The Interproof demo

A complete, tiny Interproof project that a fresh clone can build with nothing
but a LaTeX installation. Two short LaTeX documents, a small Lean 4
formalization of them, and the `interproof.toml` that ties the two together.

It is also the **regression test for the parsing rules**. Every rule in the
citation protocol was learned from real sources that are not in this
repository; this example is where those rules stay checked. The checklist
below says, rule by rule, what each piece of the demo is there to catch.

```
cd examples/demo
interproof build          # -> site/index.html, a self-contained folder
interproof serve          # the same, live, rebuilt as you edit
interproof check          # just the correspondence report; fails on dangling
```

`make demo` from the repository root does the same thing into a scratch
directory. Nothing here needs a Lean toolchain: both sides are parsed as
source text.

The Lean is nonetheless real Lean — it type-checks under Lean 4.33 with no
`import` beyond the core library, and the one `sorry` is deliberate and marked
in the reader. An example whose formal half only *looks* like Lean would be a
poor advertisement for a tool about reading formalizations.

## The material

A toy imperative language — assignment, sequencing, a conditional, a loop —
with a big-step semantics and a Hoare logic of partial correctness, proved
sound. Standard and deliberately small, and it is a miniature of the real case
study: definitions, lemmas about them, one theorem that rests on all of it, and
a companion note that the paper's notation quietly depends on.

```
examples/demo/
├── interproof.toml              the configuration, written as a tutorial
├── README.md                    this file
├── .gitignore
├── tex/
│   ├── common/preamble.tex      shared by both documents, outside either root
│   ├── paper/
│   │   ├── main.tex             preamble + \input list; holds no \label
│   │   └── sections/
│   │       ├── 10-syntax.tex
│   │       ├── 20-semantics.tex
│   │       ├── 30-hoare.tex
│   │       └── 40-soundness.tex
│   └── note/main.tex            one file
└── lean/
    └── Demo/
        ├── Store.lean           stores, updates, frames      (imports nothing)
        ├── Syntax.lean          AExp, BExp, Cmd, Proc
        ├── Semantics.lean       evaluation, big-step relation
        └── Logic/
            ├── Rules.lean       the Hoare rules
            └── Soundness.lean   the proof system and its soundness
```

Compiled: **paper 3 pages, note 2 pages**, both with zero LaTeX errors and zero
warnings on a stock TeX Live, both producing a `.synctex.gz`.

## What it deliberately covers

### Configuration and build

| # | The rule | Where it is exercised |
|---|---|---|
| 1 | A document is **several source files in a reading order**, not one file | `paper` has `files = ["sections/*.tex"]`; `main.tex` carries no `\label` at all, so nothing would be found without the glob |
| 2 | A document may be **a single file** | `note` has `files = ["main.tex"]` |
| 3 | A source file **outside the document root** still compiles and is simply not indexed | `../common/preamble.tex` is read by both documents; SyncTeX records it, Interproof drops it (no labels, no page of its own) |
| 4 | `env` reaches the LaTeX run | `tex/paper/main.tex` says `\input{preamble}` with no path, and only `env = { TEXINPUTS = "../common:" }` makes that resolve. Delete the line and the paper fails with `File 'preamble.tex' not found`. The note reaches the same file by a plain `../common/preamble` and needs no `env`; one of each is on purpose |
| 5 | Paths are relative to `interproof.toml`, not to the shell | every path in the configuration is; `interproof` walks up to find the file, so any subdirectory works as a working directory |
| 6 | `[grammar]` is data, not code | the whole section is written out with its defaults, so the demo doubles as the reference for what each key does |

### The LaTeX side

| # | The rule | Where it is exercised |
|---|---|---|
| 7 | Every listed environment kind produces an item | `definition`, `lemma`, `theorem`, `proposition`, `corollary` and `remark` all occur, with `def:` `lem:` `thm:` `prop:` `cor:` `rem:` labels |
| 8 | An **optional title** is read, and is what the index calls the item | most environments carry one — `\begin{definition}[procedure declaration]` |
| 9 | An environment with **no** title still parses | `cor:derivable-holds`, `rem:no-calls` |
| 10 | A `proof` **immediately following** an environment belongs to it, as a second rectangle | 13 of the 28 statements have one |
| 11 | A proof's own `\Cref`s count as the item's dependencies | the proof of `thm:soundness` is where its five lemma dependencies come from — the statement names none of them |
| 12 | `\section` / `\subsection` with a label are items too | `sec:syntax`, `sec:semantics`, `sub:expr-sem`, `sub:cmd-sem`, `sec:hoare`, `sec:soundness`, `sec:note-stores`, `sec:note-frames` |
| 13 | A citation may name a **section** | `Demo/Logic/Rules` cites `paper:sec:hoare`, `Demo/Syntax` cites `paper:sec:syntax`; the viewer names them but offers no rectangle, since only statements are placed in the PDF |
| 14 | The **same label in two documents** must be disambiguated | `def:state` is defined in *both* the paper and the note. `Demo/Store.lean` cites both, on adjacent lines, and only the marker in front of each decides which is which |

### The Lean side

| # | The rule | Where it is exercised |
|---|---|---|
| 15 | A module is keyed by its **path**, not its file name | `Demo/Logic/Rules` and `Demo/Logic/Soundness` live in a subdirectory |
| 16 | **Import order is not alphabetical** | alphabetical: `Logic/Rules, Logic/Soundness, Semantics, Store, Syntax`. Import order: `Store, Syntax, Semantics, Logic/Rules, Logic/Soundness`. The bottom module sorts fourth and the top module sorts first; an implementation that fell back to alphabetical order would be caught by every entry |
| 17 | A citation is **a label in a comment**, optionally with a document marker | `paper:def:cmd`, `note, def:update`. Both spellings of the marker work, and all 44 citations take this form, because it is the only form there is |
| 18 | A **label is the only thing read** — a title is not a citation | the docstring of `AgreeOn` in `Demo/Store.lean` says *Agreement on a frame* and the note's `def:frame` is titled *frame lifting*; neither phrase links anything. Only the written `def:frame` does |
| 19 | An **anchor** names a part of a statement, and the paper still compiles | `20-semantics.tex` carries `% @interproof anchor def:aeval:arith` and `…:bool` above the two `\item`s of `def:aeval`. They are LaTeX comments: `latexmk` never sees them. `Demo/Semantics.lean` cites them for `AExp.eval` and `BExp.eval`, and a trailing dot is still sentence punctuation |
| 19a | An anchor **bands less than its statement** | `def:aeval` runs across a page break — two marks, 18.4% of page 1 and 20.3% of page 2. `def:aeval:arith` is one mark of 5.0%, `def:aeval:bool` one of 10.5%. If an anchor ever bands as much as its parent, the geometry has stopped saying anything |
| 20 | A citation in the `/-- … -/` docstring **above** a declaration belongs to that declaration | 31 of the 44 |
| 21 | A citation in `/-! … -/` module prose belongs to **no declaration**, but to the block that cites | 13 of the 44, in every module header and in the two closing notes of `Demo/Logic/Rules` and `Demo/Store` |
| 22 | One label cited from **two distant blocks** of one file is two places, not one region | `paper:def:triple` in `Demo/Logic/Rules.lean`: the module header at line 7, and again at line 98, ninety lines below. The lines in between cite nothing, and a band spanning both would be a lie |
| 23 | A `/-! ## … -/` section header **immediately after a declaration** is not a docstring | `Demo/Store.lean` puts one directly under `update_ne`, and `Demo/Logic/Rules.lean` one directly under `assign_rule`. Both close the way a docstring closes; reading either as one sends the search for the opening delimiter back into the previous declaration and starts its band a whole declaration early |
| 24 | Structural keywords break a declaration's extent | `namespace`, `end`, `section … end`, `variable`, `open … in`, and `import` all occur between declarations |
| 25 | An **attribute between the docstring and the declaration** must not detach them | `@[simp]` on `update_same` and on `update_shadow` in `Demo/Store.lean` |
| 26 | `sorry` is detected and reported | exactly one, `while_rule` in `Demo/Logic/Rules.lean` |
| 27 | Declarations reference each other **by use in code** | `soundness` uses all five rule lemmas; `derivable_holds` uses `soundness`; 161 use edges in all, members included |
| 28 | **Constructors and fields are declarations**, with their own spans | `Cmd` yields `Cmd.skip` … `Cmd.whileDo`, `Proc` yields `Proc.params` and `Proc.body`; 26 members in all. `deriving Repr` closes the body and belongs to no constructor, so the last member's band does not run a line long |
| 29 | A citation on a member belongs to the **member**, not to the parent | `Demo/Syntax.lean` cites `paper:def:cmd:while` in the docstring above `| whileDo`. Innermost wins: the band is that constructor, not the whole datatype. The docstring is *indented*, which is also what keeps it from ending the `inductive` — a column-zero `/--` is a boundary and an indented one is not |
| 30 | A **label path** peels to the statement it names | that same `paper:def:cmd:while` resolves to `def:cmd` with `while` recorded as `sub`, because the paper carries no anchor by that name yet. It links now and sharpens later, with no edit to the Lean |

## The gaps, which are also deliberate

Two statements of the paper have **no Lean counterpart**:

- `paper::lem:bigstep-det` — determinism of the big-step relation;
- `paper::prop:hoare-conseq` — the rule of consequence.

They are missing on purpose. An example in which every statement is green
demonstrates nothing about a tool whose subject is the distance between an
informal document and a formal one. Two unmarked blocks between marked ones is
what a reader is actually meant to learn to see, and `interproof check
--strict` is what a CI job would use to refuse new ones.

One declaration, `while_rule`, is `sorry`. The paper states the loop rule and
proves it; the formalization claims it and has not. That is a third kind of
gap, and the viewer marks it differently from the first two.

## The numbers

Produced by the repository's own parsers over these sources.

| | |
|---|---|
| LaTeX items | **38** — paper 27, note 11 |
| … statements (`definition`/`lemma`/…) | 28, plus 2 anchors naming parts of one |
| … sections and subsections | 8 |
| … with a `proof` environment | 13 |
| `\Cref` edges between items | 35 |
| **statements with a Lean counterpart** | **26 / 28** |
| items located in the PDF by SyncTeX | 30 / 30 — 28 statements and both anchors |
| Lean modules | 5 |
| Lean declarations | 57 — 31 written, 26 constructors and fields read out of them (1 with `sorry`) |
| Lean lines | 427 |
| **citations Lean → LaTeX** | **44**, every one of them by label |
| distinct items cited | 30 |
| use edges between declarations | 161 |
| **dangling citations** | **0** |

A dangling citation here would be worse than useless: a first-time user would
read the tool's own example failing its own check and conclude the tool is
broken. If you extend this example, keep `interproof check` at zero.

## Copying this for a project of your own

`interproof.toml` is the file to copy; the comments in it are written for
exactly that. Three things to get right, in the order they bite:

1. **`root` and `files`.** `root` is what latexmk runs in and what SyncTeX
   resolves against. `files` is a reading order, in globs relative to `root`.
2. **The environment list, twice.** `[grammar].environments` and the
   `\newtheorem` lines in your preamble are two copies of the same list. A
   statement missing from the index is almost always a kind that is in one but
   not the other.
3. **`markers`, if two documents share a label.** Until then the default — the
   document's `id` as a word — is enough. Watch out for an `id` that is also an
   ordinary word of your prose.

Then write one citation, run `interproof check`, and see it resolve before
writing the other hundred.
