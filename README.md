# Interproof

A paper and its formalization, read side by side: **the compiled PDF on the
left, the Lean sources on the right**, scrolled together and linked by the
citations that are already in them.

Pick a lemma in the paper and the right pane opens the module that formalizes
it, scrolled to the declaration and banded. Pick a declaration and the paper
marks every statement it claims to be. Press `a` and every mechanized statement
in the paper lights up at once — coverage as a property of the page rather than
as a table somewhere else.

The paper side is the **compiled PDF**, not a re-render of the LaTeX. A
113-macro preamble, `mathpartir` rule displays and `\inferrule` do not survive
re-rendering, and every approximation is a place where a reader cannot trust
what they are looking at. SyncTeX supplies `label → page, rectangle`, so
fidelity is exact by construction.

> **The precondition.** Interproof does not invent the correspondence; it reads
> one you already wrote. A formalization whose comments cite the paper —
> `P3:lem:one-sided`, `note, Def. procedure declaration` — already holds it.
> Point this at sources that cite nothing and the manifest comes back empty.
> The protocol is one page: **[docs/CITING.md](docs/CITING.md)**.

---

## Look at one first

The repository publishes its own example — a small paper, its Lean
formalization, and the correspondence between them — as a live reader:
**[a working Interproof site](https://lucianoxu.github.io/Interproof/)**.
Nothing to install; press `?` in the page for what you are looking at. The
sources for it are [`examples/demo`](examples/demo).

## Install

```bash
pipx install git+https://github.com/LucianoXu/Interproof     # today
pipx install interproof                                      # once published to PyPI
```

`pip install` instead of `pipx` works equally well.

You also need a **LaTeX installation** (`latexmk` and SyncTeX, which every
TeXLive has). That is the real dependency, and it is why this ships as a
command rather than as a binary: no bundle can carry TeXLive, and a machine
that has TeXLive is not short of a Python.

You do **not** need a Lean toolchain. Both sides are parsed as source text, so
Interproof runs against a formalization you have never built — including
someone else's. A toolchain buys hover types and real go-to-definition when you
have one (`--elaborate`, see **Reading the code**); it is never required.

## Quickstart

```bash
cd my-project              # the one holding the paper and the Lean sources
interproof init            # writes interproof.toml by looking at what is here
interproof check           # does anything resolve yet?
interproof serve           # read it, rebuilt as you edit
interproof build           # a folder you can archive, publish, or hand over
```

`init` guesses: every `.tex` with a `\documentclass` is a document, what it
`\input`s is its source list, the shallowest directory holding `.lean` files is
the formal root. It writes those guesses out as a filled-in, commented file —
correcting a guess is easier than filling in a blank.

There is a complete worked example in **[examples/demo](examples/demo)**: a
small paper, a small formalization, and a configuration written to be read.
It builds from a fresh clone with no material of your own.

## How the connection is made

Three things happen, in this order, and each is a separate command if you want
it to be:

1. **`latexmk -synctex=1`** compiles each document. SyncTeX is not optional:
   it is what lets a `\label` be found as a page and a rectangle.
2. **Both sides are parsed as source text.** From the LaTeX: every labelled
   `theorem`/`lemma`/`definition`/… with its statement, its proof, its place in
   the section tree, and the labels it cites. From the Lean: declarations with
   their docstrings, module docstrings, and every citation occurring in a
   comment. Citations are resolved against the label universe of each document;
   what does not resolve is reported, not dropped.
3. **The manifest** — a checked `label ↔ declaration` mapping, the data model
   borrowed from [`span`](https://github.com/dwrensha/span) — is handed to a
   viewer that knows nothing about your documents.

Both directions of both reference structures come out of this: what a statement
cites and what cites it, what a declaration uses and what uses it. A proof can
be walked backwards to its hypotheses on either side.

## Two modes

| | `interproof serve` | `interproof build` |
|---|---|---|
| what it is | a local server that rebuilds as you edit | a folder that stands alone |
| who it is for | whoever is writing the paper or the Lean | whoever is reading it |
| on a `.lean` edit | reparsed, browser updates, < 1 s | — |
| on a `.tex` edit | latexmk (incremental) then reparse, 1–3 s | — |
| needs LaTeX | yes | to build; never to read |
| needs Lean | only with `--elaborate`, and then only the modules that moved | to build; never to read |

`serve` binds `127.0.0.1` by default, and that is the intended shape: it runs
`latexmk` on your files and has no authentication. Its real audience is the
*author* — change a `\label` and watch which citations go dangling.

## What `build` produces

```
site/
  index.html          # the reader, self-contained: double-click it
  manifest.json       # the correspondence, machine-readable
  pdf/<id>.pdf        # the compiled documents
  sources/…           # the LaTeX and Lean sources, in their original layout
  interproof.toml     # the configuration that produced all of it
  README.md           # what the folder is and how to rebuild it
```

`index.html` inlines everything it needs — pdf.js, the manifest, the PDFs — so
it opens from the file system with no server and no network. The folder around
it is what makes the artifact honest: the sources that produced the reader
travel with it, and `interproof build` inside `sources/` reproduces the whole
thing. The PDFs are therefore stored twice; that costs a megabyte or two and
buys both properties, and `--no-inline` declines the trade for a paper where it
matters (that variant needs to be served over HTTP).

The **Download** button, top right of the reader, packs all of the above —
including the page itself — into a zip in the browser. A reader who was sent a
single HTML file can still get back to the sources.

## Configuration

One file, `interproof.toml`, living with the material rather than with the
tool. Every path in it is relative to itself, so a configuration is portable.

```toml
[project]
title = "PQCPlus"

[[document]]
id      = "P3"                       # how a citation in the Lean names it
title   = "EasyPQC on a Concrete Semantics"
root    = "auto-research/P3-easypqc"
main    = "main.tex"
files   = ["sections/*.tex"]         # in reading order
markers = ['\bP3\b', 'EasyPQC']      # only needed to break ambiguity
env     = { BIBINPUTS = "../common:" }

[formal]
kind = "lean"
root = "Formalization/PQCPlus"

[grammar]                            # optional: this project's conventions
label_prefixes = ["thm", "lem", "def", "prop", "cor"]
environments   = ["theorem", "lemma", "definition", "proposition", "corollary"]
```

Full reference: **[docs/config.md](docs/config.md)**.

## Reading the page

The index on the left is one tree with two roots — **Notes** and **Lean**, the
written side and the machine side — and it folds. There is no mode to set
first: picking a row is what says which of the two you are reading in, and the
root it belongs to is marked.

- **Notes**: document, section, statement. Pick a statement, get the module
  that cites it. Other declarations citing the same statement are banded dimly
  and named in the strip above.
- **Lean**: directory, module, declaration — under each module, the
  declarations that carry a citation. Pick one, and the paper marks every
  statement it cites at once, focused one first. Modules are in **import
  order**, not alphabetical: alphabetical is the file system's order and says
  nothing about how a development is built up.
- **A file row opens the file.** A document row opens the whole PDF, a module
  row the whole module, neither banded because nothing was selected inside
  them — one page moves and the other is left alone, which is how you put an
  arbitrary paper beside an arbitrary module. It is also why a module that
  cites nothing, or a document nothing cites, is still listed and still opens:
  the tree is the source tree, not only the part of it the correspondence
  reaches. Click the triangle to fold such a row instead of opening it.
- **References**, above both pages: `cites` / `cited by` for a statement,
  `uses` / `used by` for a declaration — each direction on its own row, because
  they answer different questions.
- **Formalized** (`a`): every mechanized statement marked in the paper at once.
  A gap reads as a gap.

## Reading the code

The machine page is not a code listing. Hover a name and it says what the name
is; click it and the pane goes to where it is defined; every other occurrence
of whatever is under the pointer is marked while you are on it. A citation in a
comment stays a link into the paper, and a docstring in a hover card keeps its
own links.

How much of that is *true* depends on one switch, and the two answers are
different claims rather than different amounts of polish.

| | default | `[formal] elaborate = true` |
|---|---|---|
| needs | nothing | `lake`, and a formalization that compiles |
| colouring | a tokenizer over the source | Lean's own grammar — a binder is not a constant |
| hover | the declaration **as written**, and its docstring | the **elaborated** signature or type |
| jump | a name matched against this build | what the compiler resolved, through `open` and notation |
| occurrences | — | the identity Lean gave the token |

The default is the promise the rest of this tool makes: everything is source
text, so a reader builds against a formalization whose toolchain you have never
installed — including somebody else's. Turning elaboration on trades that for
the other column, once, at build time: each module goes through
[SubVerso](https://github.com/leanprover/subverso) and what it learned is baked
into the manifest.

**The artifact does not change.** The folder still opens with no server, no
LaTeX and no Lean; only the machine that *builds* it needs a toolchain. And
nothing on this path can fail a build — a missing `lake`, a package that does
not require SubVerso, a module that will not compile — each is reported with
its reason and leaves the reader it would have had anyway.

```bash
cd examples/demo
interproof build --elaborate       # the tracked example is a Lean package
interproof build --no-elaborate    # …or not this once
```

The example is where to see the difference: it is a `lake` package requiring
SubVerso, it depends on nothing but Lean core, and `--elaborate` on it costs
about twenty seconds the first time and two after that.

What it costs the artifact is reported, not estimated — on that example, 1 845
tokens over five modules add 116 KB to a manifest. Setup, caching and the size
argument: **[docs/config.md](docs/config.md#elaborate--what-the-machine-page-can-say-about-itself)**.
- **Clean** (`c`): the apparatus put away, leaving the two documents.
- `/` filter — it searches both indexes at once, by statement, by declaration
  and by file name, and shows what it found in each · `j`/`k` move · `h`/`l`
  fold and unfold the branch you are in · `a` formalized · `c` clean · the URL
  hash deep-links an item, unfolding the tree to it · `\Cref` links inside the
  PDF are followable.

## Publishing

Interproof stops at a folder. It does not do TLS, authentication, or domains,
and it should not: the folder is a static site, and every way you already
publish a static site works on it unchanged — GitHub Pages, Netlify, nginx, a
USB stick, an email attachment. Recipes, including how to expose a *live*
instance safely over a tunnel: **[docs/hosting.md](docs/hosting.md)**.

## For AI agents

If you were handed this README and asked to set up Interproof on a repository,
this is the whole procedure.

1. **Check the precondition first.** `grep -rE '\b(thm|lem|def|prop|cor):' --include=*.lean .`
   If nothing comes back, the formal sources cite no paper, and there is
   nothing for this tool to read. Say so and stop; read
   [docs/CITING.md](docs/CITING.md) and propose adding citations instead of
   building an empty reader.
2. `pipx install interproof` (or `pip install interproof`), and confirm
   `latexmk --version` works. Without LaTeX, `interproof check` still runs — it
   just cannot place anything on a page.
3. `interproof init` at the repository root, then **read the generated
   `interproof.toml` and correct it**. The guesses to check: is each
   `[[document]]` really a document rather than an included fragment; is
   `[formal] root` the directory whose subdirectories you want to see in the
   index.
4. `interproof check`. Exit code 0 means every citation resolves. Nonzero means
   dangling citations, and the report names each one with a file and a line.
   That report is the deliverable of this step — fix or report them before
   building anything.
5. `interproof build -o site`. The result is a folder; `site/index.html` opens
   with no server.
6. Useful for scripting: `interproof check --json` (machine-readable report,
   nonzero exit on dangling) and `interproof manifest -o out.json` (the full
   correspondence, schema version in `manifest.schema`).

Failure modes you will actually hit, and what they mean:

| symptom | cause |
|---|---|
| `no interproof.toml here or in any parent` | run `interproof init` first |
| `root '…' does not exist` | a path in the configuration is wrong; they are relative to the toml |
| `no .synctex.gz beside main.pdf` | `-synctex=1` was removed from that document's `latexmk` |
| every statement `unlocated` | the PDFs were never compiled — drop `--skip-pdf` |
| 0 links, 0 dangling | the citations use a label prefix not in `[grammar] label_prefixes` |
| `LaTeX failed` | the document does not compile on its own; fix that first |
| `not elaborated: … does not require SubVerso` | `--elaborate` was asked for; add the `require` to the package's lakefile, or drop the flag |

Do not edit the Python to retarget the tool. Everything that varies between
projects is in `interproof.toml`; if something you need is not, that is a bug
worth reporting rather than a patch worth making.

## Known limits

- **Statement-level granularity.** Proof-body ↔ tactic-block alignment — the
  actual research contribution this project would make — is not here yet.
- **No goal states.** What a tactic did to the proof obligation needs
  elaboration *and* a place to put it; the elaboration is now here (see
  **Reading the code**) and the alignment is the item above. Until then the
  machine page shows the proof, not the proof in progress.
- **Citations are trusted, not verified.** Nothing checks that a declaration
  states what the statement it cites says. Interproof puts the two texts side
  by side so a reader can check in a second, which is a different and more
  honest claim.
- The `uses` graph is what the source *names* — a good approximation of what a
  proof depends on, and not the same thing. It cannot see a lemma a `simp` set
  applied for you.
- The band is only as good as SyncTeX's line attribution; an item whose
  `\begin` is inside a macro will drift.
- Under `file://` pdf.js runs in the main thread — a blob-URL worker inherits
  the opaque origin and is refused. Served over HTTP it takes the real worker.
- Lean 4 only. The formal side is one module (`interproof/lean.py`); a second
  prover is a new module, not a setting.

## Related work

Surveyed before writing any of this: leanblueprint, Verso Blueprint,
LeanArchitect, Alectryon/LeanInk, SubVerso, `span`, Lean Atlas, doc-gen4. The
short version of why none of them fit: they want the correspondence to point
**LaTeX → Lean** (`\lean{}` markers in the paper), which means annotating the
half that is still being edited, and they link a theorem to its generated API
page rather than showing the proof body. Interproof reads the correspondence in
the direction formalizers already write it, and shows both sources.

The long version, with the numbers from the first real pair —
134 citations, 0 dangling, 906 declarations over 18,413 lines, 34 of 46
statements mechanized — is in
**[docs/case-study-PQCPlus.md](docs/case-study-PQCPlus.md)**.

## Development

```bash
git clone …  &&  cd interproof
pip install -e .
make demo              # build the tracked example
```

The repository holds the framework and never the material being read.
`interproof/` is the package (`tex.py` and `lean.py` are the two parsers,
`synctex.py` is the geometry, `subverso.py` is the optional elaboration pass,
`web/` is the viewer), `examples/demo/` is the tracked pair that a fresh clone
can build, and `docs/` is everything above in more detail.

The elaborated path is tested without a Lean toolchain: `tests/fake_subverso.py`
writes exports in SubVerso's own JSON shape over the example's real modules, and
the suite asserts that every token the overlay describes slices back out of the
file as the token it claimed to be. That is the part that can be silently
wrong — a hover on the wrong word is worse than no hover — so it is the part
that is pinned.

`python -m unittest discover -s tests` is the suite; CI runs it against
`examples/demo` with a real TeX installation, then publishes that example to
Pages. Licensed under Apache 2.0.
