"""The one thing that ties a build to a particular pair of documents.

Everything downstream — the LaTeX parser, the Lean parser, the geometry, the
viewer, the site build — asks this object rather than knowing anything about
the material.  Retargeting Interproof is writing an `interproof.toml`; it is
never an edit to the code.

The file lives with the *material*, not with the tool: the paper and the
formalization are the thing that has a correspondence, so the description of
that correspondence belongs beside them and travels with them.  Its directory
is the project root, and every path in it is read relative to that, so a
configuration is portable between checkouts.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "interproof.toml"

# What a labelled statement looks like in LaTeX, and what a citation of one
# looks like in prose.  These are defaults, not laws: a project that writes
# `t:foo` instead of `thm:foo`, or that has a `\begin{observation}`, says so in
# `[grammar]` rather than being unreadable.
DEFAULT_ENVIRONMENTS = [
    "theorem", "lemma", "definition", "proposition", "corollary",
    "remark", "example", "conjecture", "fact", "assumption",
]
DEFAULT_LABEL_PREFIXES = [
    "thm", "lem", "def", "prop", "cor", "rem", "sec", "sub", "app",
    "fig", "tab", "eq",
]
DEFAULT_LATEXMK = ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode"]


class ConfigError(Exception):
    """A configuration that cannot be acted on.

    Raised with a message written for someone whose first build just failed:
    what was expected, what was found, and where it was looked for.
    """


@dataclass(frozen=True)
class Grammar:
    """The label and citation conventions of one project."""

    environments: list[str] = field(default_factory=lambda: list(DEFAULT_ENVIRONMENTS))
    label_prefixes: list[str] = field(default_factory=lambda: list(DEFAULT_LABEL_PREFIXES))
    proof_environment: str = "proof"

    @property
    def label_re(self) -> re.Pattern[str]:
        """`thm:foo` and friends, as they occur in a `\\Cref` or a docstring."""
        alt = "|".join(sorted(map(re.escape, self.label_prefixes), key=len, reverse=True))
        return re.compile(r"\b(%s):([A-Za-z0-9][A-Za-z0-9\-_.]*)" % alt)

    @property
    def env_re(self) -> str:
        return "|".join(map(re.escape, self.environments))


@dataclass(frozen=True)
class Document:
    """One informal document: a LaTeX source tree and the PDF it compiles to."""

    id: str                       # key prefix, and how a citation names it
    title: str
    short: str
    root: Path                    # absolute; what synctex resolves against
    main: str                     # what latexmk compiles, relative to root
    files: list[str]              # globs relative to root, in document order
    markers: list[str]            # regexes: how a Lean comment names this document
    env: dict[str, str]           # extra environment for the LaTeX run
    latexmk: list[str]
    build_dir: Path               # where this document's PDF is written

    @property
    def pdf(self) -> Path:
        return self.build_dir / (Path(self.main).stem + ".pdf")

    @property
    def main_path(self) -> Path:
        return self.root / self.main

    def source_files(self) -> list[Path]:
        """The document's sources, globs expanded, in the order given.

        Order is the configuration's, not the file system's: `files` is a
        reading order, and the viewer's index inherits it.
        """
        out: list[Path] = []
        for pat in self.files:
            if "*" in pat:
                out.extend(sorted(self.root.glob(pat)))
            elif (self.root / pat).exists():
                out.append(self.root / pat)
        return out


@dataclass(frozen=True)
class Config:
    path: Path                    # the interproof.toml itself
    root: Path                    # its directory — every path is relative to this
    title: str
    documents: list[Document]
    lean_root: Path
    lean_exclude: list[str]
    grammar: Grammar
    build_dir: Path
    out_dir: Path
    text: str                     # the file verbatim, so an artifact carries it

    # --- elaboration, which is the one thing here that needs a toolchain ---
    #
    # Off by default, and that default is a promise rather than a preference:
    # everything else in this package reads source text, so a build runs
    # against a formalization whose Lean you have never installed — including
    # somebody else's.  Turning this on trades that for hover types, real
    # go-to-definition and Lean's own colouring, and the trade is the user's
    # to make.  What comes out is baked into the manifest either way: the
    # artifact never needs a toolchain, only the machine that built it.
    elaborate: bool = False
    lake: str = "lake"
    lake_root: Path | None = None     # the package to run lake in
    module_prefix: str | None = None  # what Lean calls these modules; inferred

    def document(self, doc_id: str) -> Document | None:
        return next((d for d in self.documents if d.id == doc_id), None)

    def lean_files(self) -> list[Path]:
        """Every module under the Lean root, recursively.

        Recursive because a formalization organises itself in directories, and
        a module is keyed by its path rather than its file name — two
        subdirectories may hold the same name.

        Dot-directories are never descended into, and that is not a nicety.
        `lake` checks every dependency out under `.lake/packages/`, so a
        `[formal] root` pointed at a package root — the obvious thing to
        write — otherwise reads the whole of Mathlib as if it were the
        formalization: thousands of modules in the index, the correspondence
        drowned in them, and a build that reports success.  The symptom is a
        module count far larger than the development, which is exactly the
        kind of failure that looks like success.
        """
        out = []
        for f in sorted(self.lean_root.rglob("*.lean")):
            rel = f.relative_to(self.lean_root)
            if any(part.startswith(".") for part in rel.parts[:-1]):
                continue
            posix = rel.as_posix()
            if any(f.match(p) or Path(posix).match(p) for p in self.lean_exclude):
                continue
            out.append(f)
        return out

    @property
    def marker_re(self) -> re.Pattern[str]:
        """One alternation over every document's markers, each in its own named
        group, so a match can be traced back to the document that claimed it."""
        return re.compile("|".join(
            "(?P<%s>%s)" % (_group(d.id), "|".join(d.markers))
            for d in self.documents if d.markers))

    @property
    def marker_of(self) -> dict[str, str]:
        return {_group(d.id): d.id for d in self.documents if d.markers}


def _group(doc_id: str) -> str:
    """A document id as a regex group name — which may hold only word chars."""
    return "d_" + re.sub(r"\W", "_", doc_id)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def find_config(start: Path | None = None) -> Path | None:
    """The nearest `interproof.toml` at or above `start`.

    Walking up is what makes `interproof build` work from anywhere inside the
    project, the way `git` and `make` do.
    """
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / CONFIG_NAME).is_file():
            return d / CONFIG_NAME
    return None


def load(path: Path | None = None, *, start: Path | None = None) -> Config:
    """Read a configuration, or explain why there is none to read."""
    if path is None:
        found = find_config(start)
        if found is None:
            raise ConfigError(
                f"no {CONFIG_NAME} here or in any parent directory.\n"
                f"    Run `interproof init` in the project that holds the papers "
                f"and the Lean sources.")
        path = found
    path = path.resolve()
    if not path.is_file():
        raise ConfigError(f"{path}: no such file")

    text = path.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None

    root = path.parent
    project = raw.get("project", {})
    build_dir = _abs(root, project.get("build_dir", ".interproof/build"))
    out_dir = _abs(root, project.get("out", "site"))

    grammar = _grammar(raw.get("grammar", {}), path)
    documents = _documents(raw, root, build_dir, path)

    formal = raw.get("formal", {})
    kind = formal.get("kind", "lean")
    if kind != "lean":
        raise ConfigError(
            f"{path}: formal.kind = {kind!r}; this version reads Lean 4 only.\n"
            f"    The parser is one module ({__package__}.lean); a second prover "
            f"is a new module, not a setting.")
    if "root" not in formal:
        raise ConfigError(f"{path}: [formal] needs a `root` — the directory "
                          f"holding the .lean sources")
    lean_root = _abs(root, formal["root"])
    if not lean_root.is_dir():
        raise ConfigError(f"{path}: [formal] root {formal['root']!r} "
                          f"does not exist ({lean_root})")

    lake_root = None
    if "lake_root" in formal:
        lake_root = _abs(root, formal["lake_root"])
        if not lake_root.is_dir():
            raise ConfigError(f"{path}: [formal] lake_root "
                              f"{formal['lake_root']!r} does not exist "
                              f"({lake_root})")

    cfg = Config(
        path=path, root=root,
        title=project.get("title") or root.name,
        documents=documents,
        lean_root=lean_root,
        lean_exclude=list(formal.get("exclude", [])),
        grammar=grammar,
        build_dir=build_dir, out_dir=out_dir,
        text=text,
        elaborate=bool(formal.get("elaborate", False)),
        lake=str(formal.get("lake", "lake")),
        lake_root=lake_root,
        module_prefix=(str(formal["module_prefix"])
                       if "module_prefix" in formal else None),
    )
    if not cfg.lean_files():
        raise ConfigError(f"{path}: no .lean files under {formal['root']!r}")
    return cfg


def _abs(root: Path, p: str) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else (root / q)


def _grammar(g: dict, path: Path) -> Grammar:
    return Grammar(
        environments=list(g.get("environments", DEFAULT_ENVIRONMENTS)),
        label_prefixes=list(g.get("label_prefixes", DEFAULT_LABEL_PREFIXES)),
        proof_environment=g.get("proof_environment", "proof"),
    )


def _documents(raw: dict, root: Path, build_dir: Path, path: Path) -> list[Document]:
    entries = raw.get("document", [])
    if isinstance(entries, dict):                 # [document.P3] style
        entries = [{"id": k, **v} for k, v in entries.items()]
    if not entries:
        raise ConfigError(f"{path}: no [[document]] — there is nothing to read "
                          f"the Lean sources against")

    docs: list[Document] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        where = f"{path}: [[document]] #{i + 1}"
        for k in ("id", "root"):
            if k not in e:
                raise ConfigError(f"{where} has no `{k}`")
        doc_id = str(e["id"])
        if doc_id in seen:
            raise ConfigError(f"{where}: duplicate id {doc_id!r}")
        seen.add(doc_id)
        droot = _abs(root, e["root"])
        if not droot.is_dir():
            raise ConfigError(f"{where} ({doc_id}): root {e['root']!r} does not "
                              f"exist ({droot})")
        main = e.get("main", "main.tex")
        if not (droot / main).is_file():
            raise ConfigError(f"{where} ({doc_id}): main {main!r} not found in "
                              f"{e['root']!r}")
        # By default the document is its main file.  `files` is for a paper
        # split across sections, and then it is a reading order.
        files = list(e.get("files", [main]))
        # A document with no marker can still be cited — by a canonical label
        # that only it holds.  Only ambiguity needs a marker, so the default is
        # the id itself, which is what people write anyway.
        #
        # Case-insensitively, though.  An id comes from a directory name and is
        # usually capitalised (`Paper`); prose writes it as it falls in the
        # sentence (`see paper, def:state`).  A default that missed on that
        # difference would silently attribute the one kind of citation markers
        # exist for — an ambiguous label — to the wrong document.  A marker
        # written by hand is left exactly as written.
        markers = list(e.get("markers", [r"(?i:\b%s\b)" % re.escape(doc_id)]))
        for m in markers:
            try:
                re.compile(m)
            except re.error as err:
                raise ConfigError(f"{where} ({doc_id}): marker {m!r} is not a "
                                  f"regular expression: {err}") from None
        docs.append(Document(
            id=doc_id,
            title=e.get("title", doc_id),
            short=e.get("short", doc_id),
            root=droot, main=main, files=files, markers=markers,
            env={str(k): str(v) for k, v in e.get("env", {}).items()},
            latexmk=list(e.get("latexmk", DEFAULT_LATEXMK)),
            build_dir=build_dir / doc_id,
        ))
    return docs
