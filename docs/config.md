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

A module is keyed by its **path under `root`**, not by its file name, so two
subdirectories may hold the same name and the directory structure survives into
the file index. Choosing a `root` too deep flattens the tree the index exists
to show.

Nothing here names the Lean package: import edges are resolved by finding the
prefix that the imports which do resolve agree on.

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

[grammar.kind_words]
definition = ["Definition", "Def."]
lemma      = ["Lemma", "Lem."]
theorem    = ["Theorem", "Thm."]
proposition = ["Proposition", "Prop."]
corollary  = ["Corollary", "Cor."]
remark     = ["Remark", "Rem."]
```

- **`environments`** — which `\begin{…}` blocks are statements. An environment
  not listed here is invisible, including to the coverage overlay.
- **`label_prefixes`** — what a label looks like, and therefore what a citation
  looks like: `lem:one-sided` is recognised because `lem` is here. A project
  writing `t:foo` lists `"t"`.
- **`proof_environment`** — the environment that, when it immediately follows a
  statement, is treated as that statement's proof. It gets its own rectangle,
  which is what the **with proof** button extends the band over.
- **`[grammar.kind_words]`** — how a citation that names an item by *title*
  spells its kind. A title citation must agree on the kind, so
  `Lemma (locality)` never resolves to `def:local`; this table is what makes
  that agreement checkable. Adding a spelling here is how you support
  `Satz`/`Théorème`.

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
