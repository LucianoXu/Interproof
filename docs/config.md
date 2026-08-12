# `interproof.toml`

The one place that ties a build to a particular pair of documents. The parsers,
the geometry, the viewer and the site build all ask this file rather than
knowing anything about the material — retargeting Interproof is writing a
configuration, never an edit to the code.

It lives **with the material**, not with the tool: the paper and the
formalization are the thing that has a correspondence, so the description of
that correspondence belongs beside them and travels with them. Its directory is
the *project root*, and **every path is relative to that**, so a configuration
is portable between checkouts.

`interproof init` writes one by looking at the directory. Commands find it by
walking up from the working directory, the way `git` does; `-c PATH` overrides.

---

## `[project]`

| key | default | what it is |
|---|---|---|
| `title` | the project root's directory name | the page header, the browser tab, and the name of the archive the reader downloads — so a short name, not a description |
| `out` | `"site"` | where `interproof build` writes the folder |
| `build_dir` | `".interproof/build"` | where the PDFs and SyncTeX data land |

`build_dir` holds latexmk's output, including `.fls` and `.fdb_latexmk`, which
are read back to find out which files the build actually read — that is how a
shared preamble one directory up, or a `.bib` reached only by bibtex, ends up
in the artifact. Add it to `.gitignore`.

## `[[document]]` — one per informal document, in reading order

```toml
[[document]]
id      = "P3"
title   = "EasyPQC on a Concrete Semantics"
short   = "easypqc"
root    = "auto-research/P3-easypqc"
main    = "main.tex"
files   = ["sections/*.tex"]
markers = ['\bP3\b', 'EasyPQC']
env     = { BIBINPUTS = "../common:" }
```

| key | required | default | what it is |
|---|---|---|---|
| `id` | yes | — | the key prefix (`P3::lem:foo`), and how a citation in the formal sources names this document |
| `root` | yes | — | the directory `main` sits in; **what SyncTeX resolves paths against** |
| `title` | | the `id` | shown above the page |
| `short` | | the `id` | a compact caption |
| `main` | | `"main.tex"` | what latexmk compiles |
| `files` | | `[main]` | the sources to read, globs allowed, **in reading order** |
| `markers` | | `['\b<id>\b']` | regexes: how a comment in the formal sources names this document |
| `env` | | `{}` | extra environment for the LaTeX run |
| `latexmk` | | `["latexmk","-pdf","-synctex=1","-interaction=nonstopmode"]` | the compiler |

**`files` is a reading order, not a set.** The viewer's index inherits it, and
a glob expands in sorted order — which is why section files are conventionally
named `00-intro.tex`, `10-fragment.tex`. The list is what gets *parsed*; it is
not what gets *compiled*. Compilation is `main` plus whatever LaTeX pulls in on
its own, and a shared preamble outside `root` needs no entry here.

**`markers` only matter for ambiguity.** A label held by exactly one document
resolves without help. When two documents both hold `def:state`, the citation
is settled by the nearest marker before it, and failing that by the order these
entries appear. Spell out markers when the sources call a document by more than
one name.

**`latexmk` may be replaced** — tectonic, xelatex, a wrapper script — but
whatever you put there must produce a `.synctex.gz`. Without it no statement
can be placed on a page, and the reader degrades to a PDF nobody can scroll to
the right place.

## `[formal]`

| key | required | default | what it is |
|---|---|---|---|
| `kind` | | `"lean"` | Lean 4 is what this version reads |
| `root` | yes | — | the directory holding the `.lean` sources |
| `exclude` | | `[]` | globs to skip, e.g. `["**/Test/*.lean"]` |
| `elaborate` | | `false` | run the formalization through Lean for types, jumps and its own colouring |
| `lake` | | `"lake"` | the build tool to invoke, when elaborating |
| `lake_root` | | nearest lakefile | the package directory to run it in |
| `module_prefix` | | inferred | what Lean calls these modules |

A module is keyed by its **path under `root`**, not by its file name, so two
subdirectories may hold the same name and the directory structure survives into
the file index. Choosing a `root` too deep flattens the tree the index exists
to show.

**Directories beginning with a dot are never descended into**, and that matters
more than it sounds: `lake` checks every dependency out under
`.lake/packages/`, so a `root` pointed at a package root would otherwise read
the whole of Mathlib as if it were your formalization. The symptom would not be
an error — it would be a reader with four thousand modules in the index and a
build reporting success. Use `exclude` for anything else that is present but
not part of the development.

Nothing here names the Lean package: import edges are resolved by finding the
prefix that the imports which do resolve agree on.

### `elaborate` — what the machine page can say about itself

Off, everything Interproof reads is source text. That is what lets a build run
against a formalization whose toolchain you have never installed, including
somebody else's, and it is the default for that reason. The machine page still
colours itself, still links citations, and still follows a name to the
declaration that carries it — by matching the name, with the imprecision a name
match has.

On, each module is handed to
[SubVerso](https://github.com/leanprover/subverso) once at build time and the
page gains what only elaboration knows:

- **colouring by Lean's own grammar** rather than by a keyword list — in
  particular a local binder is told apart from a constant, which no tokenizer
  can do;
- **hover types**: the elaborated signature of a constant with its docstring,
  and the type of a binder;
- **go to definition** that follows what the compiler resolved, including
  through `open` and through notation;
- **every occurrence** of whatever is under the pointer, by the identity Lean
  gave it — so two binders that share a name do not share the highlight;
- **the proof state** each tactic left, on the tactic, with the lines it has
  to prove and the hypotheses it has to prove them from.

What it costs:

- **a Lean toolchain and a formalization that compiles.** `lake` must be on
  `PATH`, and the package must require SubVerso:

  ```toml
  # lakefile.toml, in the package that holds the formalization
  [[require]]
  name = "subverso"
  git  = "https://github.com/leanprover/subverso"
  rev  = "main"
  ```

  ```lean
  -- lakefile.lean, equivalently
  require subverso from git "https://github.com/leanprover/subverso"
  ```

  then `lake update subverso` once.

- **time.** Every module is elaborated separately, so each one pays for
  importing its whole dependency closure. The result is cached under the build
  directory and keyed by the module's text, its imports' text, and the resolved
  dependency set — so a second `build` is nearly free.

  Note what that key implies: an edit to a *base* module invalidates everything
  that imports it, because a type shown downstream genuinely changes when the
  module above it does. On the tracked example that is 5 modules and 4.6
  seconds; on a development over Mathlib it is minutes. Which is why
  `serve --elaborate` never puts elaboration on the path the page waits for —
  it publishes the text reader within its usual second and the elaborated one
  behind it, superseding any pass whose sources have since moved.

  In CI, cache the build directory's `subverso/` alongside `~/.elan` and
  `.lake`, with a `restore-keys` prefix that ignores the sources: an exact miss
  still recovers every module the commit did not touch. `.github/workflows/pages.yml`
  in this repository does exactly that.

- **size.** The overlay is the one part of a manifest that grows with the size
  of the *formalization* rather than with the size of the correspondence.
  `build` reports what it added, measured rather than estimated — 125 KB for
  the 1 845 tokens and 74 proof states of the tracked example. The states are
  9 KB of that: they are recorded per *tactic*, and a development has an order
  of magnitude fewer tactics than tokens.

  Most of that is text, and most of the text is Lean's own: the docstring of
  `simp`, the signature of `Nat.succ`. It is therefore interned **once for the
  whole build**, not per module and not per token, because a docstring belongs
  to as many syntax productions as mention it and to as many modules as use
  it. Storing it per attribute cost 2.7× as much on the example, and per
  module 1.3× again on five modules — a ratio that grows with the module
  count. The consequence is that the overlay scales with the *vocabulary* a
  development touches plus a flat ~11 bytes a token, rather than with the
  product of the two. `--no-inline` remains the escape when a page has to stay
  small.

**Nothing about the artifact changes.** Elaboration happens on the machine that
builds, and what it learned is baked into the manifest; the folder that comes
out still opens with no server, no LaTeX and no Lean. And nothing here can fail
the build: no toolchain, no SubVerso, a module that does not compile — each is
printed with its reason and leaves a reader that says less, never a build that
stops.

`--elaborate` and `--no-elaborate` override this per run, on `build`, `serve`
and `manifest`. `check` never elaborates: it asks whether the citations
resolve, and no answer it gives changes with the types.

## `[grammar]` — this project's LaTeX conventions

Everything here has a default that covers ordinary `amsthm` usage. Set it when
your project does something else; the symptom of not setting it is **0 links
and 0 dangling**, which means the citations were never recognised as citations.

```toml
[grammar]
environments   = ["theorem", "lemma", "definition", "proposition", "corollary",
                  "remark", "example", "conjecture", "fact", "assumption"]
label_prefixes = ["thm", "lem", "def", "prop", "cor", "rem", "sec", "sub",
                  "app", "fig", "tab", "eq"]
proof_environment = "proof"
```

- **`environments`** — which `\begin{…}` blocks are statements. An environment
  not listed here is invisible, including to the coverage overlay.
- **`label_prefixes`** — what a label looks like, and therefore what a citation
  looks like: `lem:one-sided` is recognised because `lem` is here. A project
  writing `t:foo` lists `"t"`.
- **`proof_environment`** — the environment that, when it immediately follows a
  statement, is treated as that statement's proof. It gets its own rectangle,
  which is what the **with proof** button extends the band over.

`[grammar.kind_words]` used to configure a second citation form, naming a
statement by its kind and title. That form was removed — a title is prose, and
it matched prose that was citing nothing — so the table is no longer read, and
a configuration still carrying it is warned about at build time.

---

## A minimal configuration

```toml
[project]
title = "My Paper"

[[document]]
id   = "Paper"
root = "paper"

[formal]
root = "Formal"
```

Everything else defaults: `main.tex`, that one file as the source list, `Paper`
as its own marker, latexmk with SyncTeX, and the standard label grammar.

## Checking one

```bash
interproof check          # resolves? 0 = every citation lands
interproof check --json   # the same, machine-readable
interproof check --strict # also fail when a statement has no counterpart
```

`check` needs no PDFs to tell you whether the citations resolve; it needs them
to tell you whether the statements can be *placed*. `--skip-pdf` trades the
second for speed.
