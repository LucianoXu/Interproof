"""What elaboration knows, harvested once at build time.

Everything else in this package reads source text, and the reader that comes
out of it can be built against a formalization whose toolchain you do not have.
That is the property worth keeping, and it is why this module is *optional* and
off by default.

What it buys when it is on is the half a tokenizer cannot reach.  A name in a
proof is `Nat.succ` or a local binder or a field projection depending on what
elaboration decided, and no amount of lexing tells them apart; a type is not
written down anywhere in the source of `theorem foo : P := by …`; a `simp` set
resolves to lemmas that occur nowhere in the text.  Hover types, go-to-
definition and colouring by Lean's own grammar all bottom out in the same
requirement — the module has to be elaborated — and
[SubVerso](https://github.com/leanprover/subverso) crosses that threshold once
for all of them.

The shape of the bargain:

  * elaboration happens **at build time, on the author's machine**, and what it
    learned is baked into the manifest.  The artifact stays a folder that opens
    with no server and no Lean, which is the whole deliverable;
  * the cost is real and is reported rather than hidden: `build --elaborate`
    needs `lake` and a formalization that actually compiles, and it is slow the
    first time;
  * every failure here degrades to the source-text reader with a named reason.
    A missing toolchain is not a broken build, it is a build without hovers.

SubVerso's own JSON is explicitly an internal format — "it should be
deserialized using the same version of SubVerso" — so nothing downstream of
this module ever sees it.  What leaves here is the overlay described in
`translate`, which is ours, versioned with the manifest, and small enough to
inline into a page.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from .config import Config
from .lean import import_prefix

# Bumped whenever `translate` changes what it produces, so a cache written by
# an older Interproof is re-extracted rather than trusted.
OVERLAY = 2

LAKEFILES = ("lakefile.toml", "lakefile.lean")

# One `lake exe` per module, and each one imports the module's whole dependency
# closure.  A formalization on top of Mathlib spends most of a minute per
# module on that import alone, so the cache below is not an optimisation, it is
# what makes `serve --elaborate` usable at all.
EXE = "subverso-extract-mod"

# `Token.Kind` -> the CSS classes SubVerso itself would give it.  Mirrored
# rather than derived: the names are `Token.Kind.cssClass`'s, so a stylesheet
# written for Verso's output styles this reader too, and a kind this table has
# never heard of falls through to `unknown` instead of losing its token.
CLASS = {
    "keyword": "keyword",
    "delim": "built-in delim",
    "const": "const",
    "anonCtor": "const anon-ctor",
    "var": "var",
    "wildcard": "wildcard",
    "option": "option",
    "docComment": "doc-comment",
    "sort": "sort",
    "levelVar": "level-var",
    "levelOp": "level-op",
    "levelConst": "level-const",
    "moduleName": "module-name",
    "withType": "typed",
    "num": "literal number",
    "char": "literal char",
    "lineComment": "comment line",
    "blockComment": "comment block",
    "commentDelim": "comment delimiter",
    "operator": "punctuation operator",
    "bracket": "punctuation bracket",
    "separator": "punctuation separator",
    "unknown": "unknown",
}

# The field names each constructor carries, in declaration order, so that a
# Lean version encoding them positionally reads the same as one encoding them
# by name.
FIELDS = {
    "keyword": ("name", "occurrence", "docs"),
    "delim": ("name", "occurrence", "docs"),
    "operator": ("name", "occurrence", "docs"),
    "bracket": ("name", "occurrence", "docs"),
    "separator": ("name", "occurrence", "docs"),
    "const": ("name", "signature", "docs", "isDef", "signatureFormat"),
    "anonCtor": ("name", "signature", "docs", "signatureFormat"),
    "var": ("name", "type", "typeFormat"),
    "wildcard": ("type", "typeFormat"),
    "str": ("string", "interpolation"),
    "option": ("name", "declName", "docs"),
    "sort": ("doc?",),
    "levelVar": ("name",),
    "levelOp": ("which",),
    "levelConst": ("i",),
    "moduleName": ("name",),
    "withType": ("type",),
    "num": ("type", "typeFormat"),
    "char": ("char",),
}


class SubVersoError(Exception):
    """Elaboration was asked for and cannot be delivered.

    Raised only for the failures a person can act on — no `lake`, no package,
    SubVerso not required — and always with the line to add or the command to
    run.  Everything else degrades instead, because a build that stops because
    one module of ninety could not be elaborated has thrown away the
    correspondence to protect a hover.
    """


# --------------------------------------------------------------------------
# reading SubVerso's JSON
# --------------------------------------------------------------------------

def _ctor(v: object) -> tuple[str, object]:
    """A Lean sum type, as `(constructor, payload)`.

    `deriving ToJson` writes a nullary constructor as its own name and every
    other as a one-key object, so this is the whole of the convention.
    """
    if isinstance(v, str):
        return v, {}
    if isinstance(v, dict) and len(v) == 1:
        (k, body), = v.items()
        return k, body
    raise SubVersoError(f"not a constructor: {json.dumps(v)[:120]}")


def _fields(body: object, names: tuple[str, ...]) -> list:
    """A constructor's arguments, however this Lean version wrote them down.

    Named when the constructor named them, an array when it did not, and the
    bare value when there was only one.  Reading all three costs a dozen lines
    and removes a whole class of "worked on my toolchain".
    """
    if isinstance(body, dict):
        return [body.get(n) for n in names]
    if isinstance(body, list):
        return [body[i] if i < len(body) else None for i in range(len(names))]
    return [body] + [None] * (len(names) - 1)


def _name(v: object) -> str:
    """A `Lean.Name` as it is written.

    SubVerso serialises names as an array of components so that they
    round-trip; `FVarId` and the odd plain instance write a string instead.
    Both arrive here.
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return ".".join(str(x) for x in v)
    if isinstance(v, dict):
        for k in ("name", "val"):
            if k in v:
                return _name(v[k])
    return str(v)


def _u16(s: str) -> int:
    """A string's length as JavaScript will count it.

    The viewer indexes the module text with JS string offsets, which are UTF-16
    code units.  A formalization writing `𝒫` — and they do — desynchronises
    every token after it if this is measured in code points instead.
    """
    return len(s.encode("utf-16-le")) // 2


def _attr(kind: object) -> dict:
    """One `Token.Kind` as the viewer needs it.

    `c` is the class, `h` what a hover shows, `d` its docstring, `n` the name a
    jump would target, `b` the occurrence identity (every token sharing it is
    the same thing, which is what lets one highlight the others), and `def`
    whether this occurrence is the declaration rather than a use.
    """
    ctor, body = _ctor(kind)
    out: dict = {"c": CLASS.get(ctor, "unknown")}
    f = _fields(body, FIELDS.get(ctor, ()))

    if ctor in ("keyword", "delim", "operator", "bracket", "separator"):
        _, occ, docs = f
        if docs:
            out["d"] = docs
        if occ:
            out["b"] = "kw-occ-" + str(occ)
    elif ctor in ("const", "anonCtor"):
        name = _name(f[0])
        out["n"] = name
        if f[1]:
            out["h"] = f[1]
        if f[2]:
            out["d"] = f[2]
        if name:
            out["b"] = "const-" + name
        if ctor == "const" and f[3]:
            out["def"] = 1
    elif ctor == "var":
        fv = _name(f[0])
        if f[1]:
            out["h"] = f[1]
        if fv:
            out["b"] = "var-" + fv
    elif ctor in ("wildcard", "withType"):
        if f[0]:
            out["h"] = f[0]
    elif ctor == "num":
        if f[0]:
            out["h"] = f[0]
    elif ctor == "str":
        # the class carries the distinction, as it does in Verso's own output
        if f[1]:
            out["c"] = "literal string interpolation"
        else:
            out["c"] = "literal string"
    elif ctor == "option":
        name = _name(f[0])
        if f[2]:
            out["d"] = f[2]
        if name:
            out["b"] = "option-" + name
    elif ctor == "sort":
        if f[0]:
            out["d"] = f[0]
    elif ctor == "moduleName":
        name = _name(f[0])
        if name:
            out["n"] = name
            out["b"] = "module-name-" + name
    elif ctor in ("levelVar", "levelOp", "levelConst"):
        v = _name(f[0]) if ctor == "levelVar" else str(f[0])
        if v:
            out["b"] = CLASS[ctor] + "-" + v
    return out


@contextmanager
def _deep():
    """Room to walk a proof term.

    The export is a DAG and `_flatten` follows it recursively; its depth is the
    nesting of the syntax, which on a long `calc` or a deeply structured proof
    passes CPython's default limit.  Raised for the walk and put back after, so
    a crash in this optional stage cannot leave the rest of the build with a
    limit it never asked for.
    """
    was = sys.getrecursionlimit()
    sys.setrecursionlimit(max(was, 40000))
    try:
        yield
    finally:
        sys.setrecursionlimit(was)


# Which of an attribute's fields are text, and therefore worth interning
# rather than repeating.
TEXT_FIELDS = ("c", "h", "d", "n", "b")


class _Pool:
    """The attribute table, interned — and its strings, interned separately.

    Two levels, and the second one is where the size of this overlay is won or
    lost.  Deduplicating whole attributes is the obvious half: every occurrence
    of `Nat` carries the same name, signature and docstring, and SubVerso's own
    export interns tokens for exactly this reason.

    But an attribute is not the unit the *text* repeats at.  Lean tags each
    syntax production with its own `occurrence`, so `simp`'s documentation — a
    page of it — belongs to a dozen distinct attributes, and a table keyed by
    the whole attribute writes that page out a dozen times.  Measured on the
    tracked example, which is four hundred lines: 80 distinct docstrings stored
    494 times, two thirds of the entire overlay.  So the strings live in their
    own table and an attribute holds indices into it, and what the docstrings
    cost becomes what Lean's vocabulary costs rather than what this
    formalization's use of it costs.
    """

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.ix: dict[str, int] = {}
        self.strs: list[str] = []
        self.six: dict[str, int] = {}

    def text(self, v: str) -> int:
        if v not in self.six:
            self.six[v] = len(self.strs)
            self.strs.append(v)
        return self.six[v]

    def add(self, attr: dict) -> int:
        packed = {k: (self.text(v) if k in TEXT_FIELDS else v)
                  for k, v in attr.items()}
        k = json.dumps(packed, sort_keys=True)
        if k not in self.ix:
            self.ix[k] = len(self.items)
            self.items.append(packed)
        return self.ix[k]


def _flatten(data: dict, key: int, pool: _Pool, memo: dict) -> tuple[str, list]:
    """One node of SubVerso's export DAG, as text and the tokens inside it.

    Returns `(text, [(offset, length, attr), …])` with offsets relative to the
    start of this node, so a shared subtree is walked once and reused wherever
    it occurs.  The export is deduplicated — that is its whole purpose — and a
    walk that re-expanded every occurrence would be quadratic on the proofs
    that are shared the most.
    """
    if key in memo:
        return memo[key]

    node = data["code"].get(str(key))
    if node is None:
        raise SubVersoError(f"dangling code key {key}")
    ctor, body = _ctor(node)

    if ctor == "token":
        tk = _fields(body, ("tok",))[0]
        tok = data["tokens"].get(str(tk))
        if tok is None:
            raise SubVersoError(f"dangling token key {tk}")
        content = tok.get("content", "")
        got = (content, [(0, _u16(content), pool.add(_attr(tok.get("kind"))))]
               if content else [])
    elif ctor in ("text", "unparsed"):
        got = (_fields(body, ("str",))[0] or "", [])
    elif ctor == "seq":
        parts, spans, at = [], [], 0
        for k in _fields(body, ("highlights",))[0] or []:
            t, ss = _flatten(data, k, pool, memo)
            spans.extend((o + at, n, a) for o, n, a in ss)
            parts.append(t)
            at += _u16(t)
        got = ("".join(parts), spans)
    elif ctor == "span":
        got = _flatten(data, _fields(body, ("info", "content"))[1], pool, memo)
    elif ctor == "tactics":
        got = _flatten(
            data, _fields(body, ("info", "startPos", "endPos", "content"))[3],
            pool, memo)
    elif ctor == "point":
        got = ("", [])
    else:
        raise SubVersoError(f"unknown highlight node {ctor!r}")

    memo[key] = got
    return got


def translate(mod: dict, text: str) -> dict:
    """SubVerso's export for one module, as the overlay the viewer reads.

        {"strs":  [ "…", … ],                       # every string, once
         "attrs": [ {c, h?, d?, n?, b?, def?}, … ],  # values index `strs`
         "toks":  [line, col, len, attr, …],         # flat, in source order
         "defs":  [[fully.qualified.name, line], …]}

    `line` is 1-based; `col` and `len` are UTF-16 code units, which is what a
    JavaScript string is indexed in.  The token list is flat because it is the
    one part of a manifest that scales with the size of the formalization
    rather than with the size of the correspondence — a shape that costs four
    numbers a token rather than an object a token.

    Positions are *found*, not trusted.  Each command's highlighted text is a
    contiguous slice of the module, so it is located in the file by search from
    where the previous one ended; a command whose text is not there is dropped
    and counted.  That makes a SubVerso whose output this module has misread
    produce a thin overlay rather than a set of confidently wrong hovers.
    """
    data = mod.get("data")
    items = mod.get("items")
    if not isinstance(data, dict) or not isinstance(items, list):
        raise SubVersoError("not a subverso-extract-mod document "
                            "(no `data`/`items`)")
    for t in ("code", "tokens"):
        if not isinstance(data.get(t), dict):
            raise SubVersoError(f"the export carries no `{t}` table")

    pool = _Pool()
    with _deep():
        toks, defs, missed = _scan(data, items, text, pool)

    if missed and missed == len([i for i in items if isinstance(i, dict)]):
        raise SubVersoError("no command's highlighted text occurs in the "
                            "module — the export does not describe this file")
    return {"strs": pool.strs, "attrs": pool.items, "toks": toks, "defs": defs,
            **({"missed": missed} if missed else {})}


def _scan(data: dict, items: list, text: str,
          pool: _Pool) -> tuple[list[int], list[list], int]:
    """Every command of the module, placed in the file it came from."""
    memo: dict = {}
    # character offsets of each line start, for turning the place a command was
    # found into the (line, column) the overlay is written in
    lines = text.split("\n")
    starts, at = [], 0
    for ln in lines:
        starts.append(at)
        at += len(ln) + 1

    toks: list[int] = []
    defs: list[list] = []
    cursor, missed = 0, 0

    for item in items:
        if not isinstance(item, dict) or "code" not in item:
            continue
        code, spans = _flatten(data, item["code"], pool, memo)
        if not code:
            continue
        found = text.find(code, cursor)
        if found < 0:
            missed += 1
            continue
        cursor = found + len(code)

        # the file offset of the command, as a (line, column-in-UTF-16) pair
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= found:
                lo = mid
            else:
                hi = mid - 1
        base_line, base_col = lo, _u16(lines[lo][:found - starts[lo]])

        # One walk of the command for all of its tokens, not one per token: the
        # spans come out of `_flatten` in source order, so a single cursor
        # crossing the text answers every one of them.
        line, col, k, i = base_line, base_col, 0, 0
        first = 0
        for off, n, a in sorted(spans):
            while k < off and i < len(code):
                ch = code[i]
                i += 1
                k += _u16(ch)
                if ch == "\n":
                    line += 1
                    col = 0
                else:
                    col += _u16(ch)
            toks.extend((line + 1, col, n, a))
            first = first or line + 1

        # `defines` is what makes a jump possible at all: SubVerso names a
        # constant in full (`Demo.Store.update`) and this build keys a
        # declaration by what the source wrote (`update`), so the two are tied
        # together here, through the command that did the defining.
        #
        # The line recorded is the command's first *token*, not the start of
        # the slice it was found at: a command owns the blank line and the
        # docstring above it, and a line number pointing at those lands outside
        # every declaration this build knows about.
        for name in item.get("defines") or []:
            defs.append([_name(name), first or base_line + 1])

    return toks, defs, missed


# --------------------------------------------------------------------------
# running it
# --------------------------------------------------------------------------

REQUIRE = """      # lakefile.toml
      [[require]]
      name = "subverso"
      git  = "https://github.com/leanprover/subverso"
      rev  = "main"

      -- lakefile.lean, equivalently
      require subverso from git "https://github.com/leanprover/subverso"
"""


def package_root(cfg: Config) -> Path | None:
    """The lake package the formalization belongs to.

    Configured if the project says so, and otherwise the nearest directory at
    or above the formal root holding a lakefile — which is where `lake` has to
    be run from, and is usually not the formal root itself.
    """
    if cfg.lake_root is not None:
        return cfg.lake_root
    for d in [cfg.lean_root, *cfg.lean_root.parents]:
        if any((d / f).is_file() for f in LAKEFILES):
            return d
    return None


def module_names(cfg: Config, files: list[dict]) -> dict[str, str]:
    """Every module key of this build, as the dotted name Lean knows it by."""
    prefix = cfg.module_prefix if cfg.module_prefix is not None else import_prefix(files)
    prefix = (prefix.rstrip(".") + ".") if prefix.strip(".") else ""
    return {f["name"]: prefix + f["name"].replace("/", ".") for f in files}


def _closure(files: list[dict]) -> dict[str, list[str]]:
    """Each module with everything it imports, transitively.

    The cache key of a module has to include them: a hover shows a *type*, and
    editing the lemma a module imports changes what the type is without
    touching a byte of the module itself.
    """
    imports = {f["name"]: list(f.get("imports") or []) for f in files}
    out: dict[str, list[str]] = {}

    def walk(name: str, seen: frozenset[str]) -> list[str]:
        if name in out:
            return out[name]
        if name in seen:
            return []
        got: set[str] = set()
        for p in imports.get(name, []):
            got.add(p)
            got.update(walk(p, seen | {name}))
        out[name] = sorted(got)
        return out[name]

    for f in files:
        walk(f["name"], frozenset())
    return out


def _stamp(cfg: Config, root: Path) -> str:
    """What the extraction depends on besides the module texts.

    A dependency bump changes every signature in the development and no source
    file of it, so the resolved dependency set is part of the key.  Without it
    a `lake update` leaves a cache full of types that were true last month.
    """
    h = hashlib.sha1(f"{OVERLAY}\0".encode())
    for f in ("lake-manifest.json", "lean-toolchain", *LAKEFILES):
        p = root / f
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _key(text: str, deps: list[str], by_name: dict[str, str], stamp: str) -> str:
    h = hashlib.sha1(stamp.encode())
    h.update(text.encode("utf-8"))
    for d in deps:
        h.update(b"\0")
        h.update(by_name.get(d, "").encode("utf-8"))
    return h.hexdigest()


def extract(cfg: Config, files: list[dict], *,
            say=print) -> tuple[dict[str, dict], list[str]]:
    """Elaborate every module and return its overlay, keyed by module.

    Returns the overlays it got and the notes worth printing.  A module that
    cannot be elaborated is a note and an absence, never an exception: the
    reader degrades to source text for that one module and stays a reader.
    The failures that are *not* recoverable — no `lake`, no package, SubVerso
    not required by the project — are raised, because every module would fail
    for the same reason and ninety copies of it is not a report.
    """
    # The toolchain first, then the package: a machine with no Lean at all is
    # the common case, and telling someone their `lean_root` is not a lake
    # package when the real answer is "there is no lake" sends them to fix the
    # wrong file.
    lake = shutil.which(cfg.lake)
    if lake is None:
        raise SubVersoError(
            f"`{cfg.lake}` is not on PATH, and elaboration needs the Lean "
            f"toolchain of the formalization.\n"
            f"    Install elan, or read the sources as text with "
            f"`--no-elaborate`.")
    root = package_root(cfg)
    if root is None:
        raise SubVersoError(
            f"no lakefile at or above {cfg.lean_root}, so there is no lake "
            f"package to elaborate in.\n"
            f"    Point [formal] lake_root at the package, or read the sources "
            f"as text with `--no-elaborate`.")

    names = module_names(cfg, files)
    deps = _closure(files)
    by_name = {f["name"]: f["text"] for f in files}
    stamp = _stamp(cfg, root)

    cache = cfg.build_dir / "subverso"
    cache.mkdir(parents=True, exist_ok=True)

    out: dict[str, dict] = {}
    notes: list[str] = []
    todo = []
    for f in files:
        want = _key(f["text"], deps.get(f["name"], []), by_name, stamp)
        got = _cached(cache, f["name"], want)
        if got is not None:
            out[f["name"]] = got
        else:
            todo.append((f, want))

    if todo:
        say(f"elaborating      {len(todo)} of {len(files)} modules "
            f"({len(files) - len(todo)} cached) — `{EXE}` in {root}")
    for i, (f, want) in enumerate(todo, start=1):
        mod = names[f["name"]]
        say(f"   {i:>4}/{len(todo)}  {mod}")
        try:
            raw = _run(lake, root, mod, cache)
        except SubVersoError:
            raise
        except Exception as e:                       # noqa: BLE001 - reported
            notes.append(f"{mod}: {e}")
            continue
        try:
            ov = translate(raw, f["text"])
        except SubVersoError as e:
            notes.append(f"{mod}: {e}")
            continue
        _store(cache, f["name"], want, ov)
        out[f["name"]] = ov

    return out, notes


def _cachefile(cache: Path, name: str) -> Path:
    """One file per module, named so that two directories holding the same
    module name do not share an entry."""
    safe = name.replace("/", "%2F")
    return cache / f"{safe}.json"


def _cached(cache: Path, name: str, want: str) -> dict | None:
    p = _cachefile(cache, name)
    if not p.is_file():
        return None
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got.get("overlay") if got.get("key") == want else None


def _store(cache: Path, name: str, want: str, overlay: dict) -> None:
    try:
        _cachefile(cache, name).write_text(
            json.dumps({"key": want, "overlay": overlay}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass                      # a cache that cannot be written is not a build failure


def _run(lake: str, root: Path, mod: str, cache: Path) -> dict:
    """One module through `lake exe subverso-extract-mod`."""
    dest = cache / "_raw.json"
    dest.unlink(missing_ok=True)
    proc = subprocess.run([lake, "exe", EXE, mod, str(dest)],
                          cwd=root, capture_output=True, text=True)
    err = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0 and not dest.is_file():
        if "unknown executable" in err or "unknown target" in err:
            raise SubVersoError(
                f"{root} does not require SubVerso, so there is nothing to "
                f"elaborate with.\n"
                f"    Add it to the package's lakefile and run `lake update "
                f"subverso`:\n\n{REQUIRE}")
        raise RuntimeError(_clip(err) or f"{EXE} exited {proc.returncode}")
    if not dest.is_file():
        raise RuntimeError(_clip(err) or f"{EXE} wrote no output")
    try:
        raw = dest.read_text(encoding="utf-8")
    finally:
        dest.unlink(missing_ok=True)
    try:
        return json.loads(raw)
    except ValueError:
        # The extractor opens its output file *before* it elaborates, so a
        # module it cannot import leaves an empty file behind and a reason on
        # stderr.  Reporting the JSON parse error instead would say "Expecting
        # value: line 1 column 1" about a build failure, and send whoever reads
        # the note to look at this module rather than at their module.
        raise RuntimeError(_clip(err) or
                           f"{EXE} wrote no usable JSON") from None


def _clip(s: str, limit: int = 400) -> str:
    """A tool's output as a note: the first lines, which is where it says what
    went wrong, and never the page of build progress before them."""
    lines = [l for l in (s or "").splitlines() if l.strip()]
    keep = [l for l in lines if "error" in l.lower()] or lines
    out = " · ".join(keep[-4:])
    return out if len(out) <= limit else out[:limit] + "…"
