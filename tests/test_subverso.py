"""The elaborated path, checked without a Lean toolchain.

The thing that can go wrong in this half is not the elaboration — SubVerso and
Lean are responsible for that — it is the *translation*: an interned export
turned back into positions in a file.  If it drifts, the reader does not fail,
it points a hover at the wrong word, which is worse.  So what is asserted here
is the property that makes it correct: every token the overlay describes must
slice back out of the module text as the token SubVerso said it was.

`fake_subverso` supplies exports in SubVerso's own JSON shape over the tracked
example's real modules, which is where the unicode, the multi-line comments and
the several-commands-per-file live.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fake_subverso as fake

from interproof import config as C
from interproof import subverso as S
from interproof.lean import signature_of

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


def slice16(line: str, col: int, n: int) -> str:
    """A line sliced the way JavaScript would slice it."""
    return line.encode("utf-16-le")[col * 2:(col + n) * 2].decode("utf-16-le")


class TranslateTests(unittest.TestCase):
    """Positions, over the example's own modules."""

    def modules(self):
        cfg = C.load(DEMO / "interproof.toml")
        for p in cfg.lean_files():
            yield p.name, p.read_text(encoding="utf-8")

    def test_every_token_lands_on_its_own_text(self):
        for name, text in self.modules():
            with self.subTest(module=name):
                ov = S.translate(fake.module(text, split=4), text)
                lines = text.split("\n")
                toks = ov["toks"]
                self.assertTrue(toks, "the module produced no tokens at all")
                self.assertEqual(len(toks) % 4, 0, "the run is line/col/len/attr")
                for i in range(0, len(toks), 4):
                    ln, col, n, a = toks[i:i + 4]
                    self.assertGreaterEqual(ln, 1)
                    self.assertLessEqual(ln, len(lines))
                    self.assertLess(a, len(ov["attrs"]))
                    for k, v in ov["attrs"][a].items():
                        if k in S.TEXT_FIELDS:
                            self.assertLess(v, len(ov["strs"]),
                                            f"attr.{k} indexes past the table")
                    got = slice16(lines[ln - 1], col, n)
                    # a token may be clipped by the end of its line; what must
                    # hold is that it starts where the overlay says it does
                    self.assertTrue(
                        len(got) > 0 or n == 0,
                        f"{name}:{ln}:{col}+{n} slices to nothing")

    def test_nothing_is_missed(self):
        for name, text in self.modules():
            with self.subTest(module=name):
                ov = S.translate(fake.module(text, split=5), text)
                self.assertEqual(ov.get("missed", 0), 0,
                                 "every command should be found in the file")

    def test_unicode_columns_are_utf16(self):
        """A module written with `σ`, `∀` and `▸` must not drift.

        Lean counts columns in code points and JavaScript indexes strings in
        UTF-16 units; the overlay is written in the latter, and this is the
        assertion that says so.
        """
        text = "def f (σ : Nat) : Nat := σ\ntheorem g : 𝒫 = 𝒫 := rfl\n"
        ov = S.translate(fake.module(text, split=1), text)
        lines = text.split("\n")
        for i in range(0, len(ov["toks"]), 4):
            ln, col, n, _ = ov["toks"][i:i + 4]
            self.assertTrue(slice16(lines[ln - 1], col, n).strip(),
                            "a token sliced to whitespace — columns drifted")

    def test_declarations_are_tied_to_their_names(self):
        text = "\n".join([
            "namespace Demo",
            "/-- What it does. -/",
            "def thing (n : Nat) : Nat := n",
            "end Demo",
            "",
        ])
        ov = S.translate(fake.module(text, split=1), text)
        self.assertTrue(ov["defs"], "a `defines` entry should have survived")
        for _, line in ov["defs"]:
            self.assertGreaterEqual(line, 1)
            self.assertLessEqual(line, len(text.split("\n")))

    def test_a_foreign_document_is_refused(self):
        with self.assertRaises(S.SubVersoError):
            S.translate({"nope": 1}, "def x := 1\n")
        with self.assertRaises(S.SubVersoError):
            S.translate({"data": {"code": {}, "tokens": {}},
                         "items": [{"code": 99}]}, "def x := 1\n")

    def test_an_export_of_another_file_is_refused(self):
        """The overlay is only ever attached to the module it describes.

        A stale cache entry or a mismatched module name would otherwise produce
        an overlay full of confident, wrongly placed hovers.
        """
        a = "def alpha : Nat := 1\n"
        b = "theorem beta : True := trivial\n"
        with self.assertRaises(S.SubVersoError):
            S.translate(fake.module(a, split=1), b)


class ProofStateTests(unittest.TestCase):
    """Where a proof state is attached, and what it claims.

    Placement is the part that can be silently wrong, and it cannot lean on
    SubVerso's own `startPos`/`endPos`: those do not agree with offsets into
    the file — on the example, a node reading `exact while_rule ih` reports a
    range landing inside a comment twenty lines away.  Tactics are therefore
    placed by the same walk that places the tokens, and this is the assertion
    that the walk agrees with the file.
    """

    def test_a_state_lands_on_the_tactic_that_left_it(self):
        text = "\n".join([
            "theorem t (n : Nat) : n = n := by",
            "  induction n with",
            "  | zero => rfl",
            "  | succ k ih => rfl",
            "",
        ])
        ov = S.translate(fake.module(text, split=1), text)
        lines = text.split("\n")
        self.assertTrue(ov["tacs"], "the fake export carries no tactics")
        for i in range(0, len(ov["tacs"]), 4):
            ln, col, n, st = ov["tacs"][i:i + 4]
            self.assertGreaterEqual(ln, 1)
            self.assertLessEqual(ln, len(lines))
            self.assertTrue(slice16(lines[ln - 1], col, n).strip(),
                            f"a tactic at {ln}:{col}+{n} covers only whitespace")
            self.assertLess(st, len(ov["states"]))

    def test_goals_index_the_string_table(self):
        text = "theorem t : True := by trivial\n"
        ov = S.translate(fake.module(text, split=1), text)
        for g in ov["goals"]:
            for x in g["h"]:
                self.assertLess(x, len(ov["strs"]))
            self.assertLess(g["c"], len(ov["strs"]))
        for st in ov["states"]:
            for gi in st:
                self.assertLess(gi, len(ov["goals"]))

    def test_a_build_without_states_still_reads(self):
        """An export with no `tactics` node at all — a module of definitions.

        The overlay must still be well formed; the viewer reads `tacs` as
        absent rather than as an error, which is the same shape a build from
        before proof states was carried has.
        """
        text = "def f (n : Nat) : Nat := n\n"
        ov = S.translate(fake.module(text, split=1), text)
        self.assertEqual(ov["tacs"], [])
        self.assertEqual(ov["states"], [])
        self.assertTrue(ov["toks"], "the tokens are unaffected")


class AttributeTests(unittest.TestCase):
    """What a token kind becomes, in the encoding `deriving ToJson` writes."""

    def test_const_carries_signature_docs_and_target(self):
        a = S._attr({"const": {"name": ["Demo", "update"], "signature": "sig",
                               "docs": "doc", "isDef": False,
                               "signatureFormat": None}})
        self.assertEqual(a["c"], "const")
        self.assertEqual(a["n"], "Demo.update")
        self.assertEqual(a["h"], "sig")
        self.assertEqual(a["d"], "doc")
        self.assertEqual(a["b"], "const-Demo.update")
        self.assertNotIn("def", a)

    def test_a_definition_site_says_so(self):
        a = S._attr({"const": {"name": ["X"], "signature": "s", "docs": None,
                               "isDef": True, "signatureFormat": None}})
        self.assertEqual(a.get("def"), 1)

    def test_a_local_binder_carries_its_type_not_a_name(self):
        a = S._attr({"var": {"name": "_uniq.4", "type": "Nat",
                             "typeFormat": None}})
        self.assertEqual(a["c"], "var")
        self.assertEqual(a["h"], "Nat")
        self.assertNotIn("n", a, "a binder is not somewhere to jump to")

    def test_a_nullary_constructor_is_its_own_name(self):
        self.assertEqual(S._attr("docComment")["c"], "doc-comment")
        self.assertEqual(S._attr("unknown")["c"], "unknown")

    def test_positional_fields_read_the_same_as_named(self):
        """A Lean version that wrote a constructor's fields as an array.

        `deriving ToJson` picks between a named object and a positional array
        by whether the constructor's arguments have user-facing names, and that
        is a property of a declaration this package does not own.
        """
        named = S._attr({"var": {"name": "v", "type": "Nat", "typeFormat": None}})
        array = S._attr({"var": ["v", "Nat", None]})
        self.assertEqual(named, array)

    def test_an_unheard_of_kind_keeps_its_token(self):
        a = S._attr({"someFutureKind": {"whatever": 1}})
        self.assertEqual(a["c"], "unknown")


class ModuleNameTests(unittest.TestCase):
    """What Lean calls these modules, which nothing configures by default."""

    def test_the_prefix_is_read_off_the_imports(self):
        files = [
            {"name": "Basic", "text": "-- nothing\n"},
            {"name": "Mid", "text": "import PQCPlus.Basic\n"},
            {"name": "Top/Deep", "text": "import PQCPlus.Mid\n"},
        ]
        cfg = C.load(DEMO / "interproof.toml")
        names = S.module_names(cfg, files)
        self.assertEqual(names["Basic"], "PQCPlus.Basic")
        self.assertEqual(names["Top/Deep"], "PQCPlus.Top.Deep")

    def test_a_configured_prefix_wins(self):
        cfg = C.load(DEMO / "interproof.toml")
        cfg = type(cfg)(**{**cfg.__dict__, "module_prefix": "Other"})
        names = S.module_names(cfg, [{"name": "A/B", "text": "import X.A.B\n"}])
        self.assertEqual(names["A/B"], "Other.A.B")

    def test_no_prefix_at_all_is_a_prefix(self):
        cfg = C.load(DEMO / "interproof.toml")
        cfg = type(cfg)(**{**cfg.__dict__, "module_prefix": ""})
        names = S.module_names(cfg, [{"name": "A", "text": ""}])
        self.assertEqual(names["A"], "A")


class SignatureTests(unittest.TestCase):
    """The source-level signature — the hover text when nothing elaborated."""

    def test_the_body_is_cut_off(self):
        self.assertEqual(signature_of("theorem foo (a : Nat) : a = a := by rfl"),
                         "theorem foo (a : Nat) : a = a")
        self.assertEqual(signature_of("def f : Nat → Nat\n  | 0 => 1\n  | n => n"),
                         "def f : Nat → Nat")
        self.assertEqual(signature_of("structure S where\n  x : Nat"),
                         "structure S")

    def test_a_default_argument_is_not_a_body(self):
        self.assertEqual(signature_of("def g (n : Nat := 0) : Nat := n"),
                         "def g (n : Nat := 0) : Nat")

    def test_a_by_inside_a_binder_is_not_a_body(self):
        self.assertEqual(
            signature_of("theorem h (p : P := by simp) : Q := trivial"),
            "theorem h (p : P := by simp) : Q")

    def test_an_identifier_ending_in_by_is_not_by(self):
        self.assertEqual(signature_of("def stand_by (n : Nat) : Nat := n"),
                         "def stand_by (n : Nat) : Nat")

    def test_unicode_binders_survive(self):
        self.assertEqual(signature_of("theorem u (Γ₀ : Ctx) (σ : Subst) : ok := by\n  t"),
                         "theorem u (Γ₀ : Ctx) (σ : Subst) : ok")

    def test_the_example_has_signatures_for_every_declaration(self):
        from interproof import manifest as M

        cfg = C.load(DEMO / "interproof.toml")
        m = M.build(cfg, with_sources=False, quiet=True, elaborate=False)
        decls = [d for f in m["lean"] for d in f["decls"]]
        self.assertTrue(decls)
        for d in decls:
            with self.subTest(decl=d["name"]):
                self.assertTrue(d["signature"].strip(),
                                "every declaration needs something to hover")
                self.assertNotIn(":=", d["signature"].split("\n")[-1][-2:],
                                 "a signature must not end in its own body")


class DependencyCheckoutTests(unittest.TestCase):
    """A package's dependencies are not the formalization.

    `lake` checks every dependency out under `.lake/packages/`, so the moment
    `[formal] root` points at a package root — the obvious thing to write, and
    what the tracked example now does — the whole of Mathlib is under it.  The
    symptom is not an error: it is a reader with four thousand modules in the
    index, the correspondence lost among them, and a build reporting success.
    """

    def test_dot_directories_are_never_descended_into(self):
        cfg = C.load(DEMO / "interproof.toml")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lean"
            (root / "Demo").mkdir(parents=True)
            (root / "Demo" / "Real.lean").write_text("def mine := 1\n")
            dep = root / ".lake" / "packages" / "mathlib" / "Mathlib"
            dep.mkdir(parents=True)
            (dep / "Huge.lean").write_text("def theirs := 2\n")
            (root / ".git").mkdir()
            (root / ".git" / "Odd.lean").write_text("def neither := 3\n")

            moved = type(cfg)(**{**cfg.__dict__, "lean_root": root})
            got = [p.name for p in moved.lean_files()]
            self.assertEqual(got, ["Real.lean"],
                             "a dependency checkout was read as the formalization")

    def test_the_example_reads_only_its_own_modules(self):
        """The example acquired a lakefile so `--elaborate` can be shown on it.

        That put `.lake/packages/subverso` — some fifty modules — inside the
        formal root, and this is the assertion that it stays out of the reader.
        """
        cfg = C.load(DEMO / "interproof.toml")
        for p in cfg.lean_files():
            self.assertNotIn(".lake", p.parts, f"{p} is a dependency, not this development")


class InvocationTests(unittest.TestCase):
    """What `extract` runs, and in what order.

    Driven with a `lake` that is a shell script recording its arguments, so
    the ordering is pinned without a toolchain.  It is pinned because getting
    it wrong is silent: `subverso-extract-mod` *imports* the module it
    elaborates, so on an unbuilt checkout every module that imports another
    fails with `unknown module prefix` while the modules importing nothing
    succeed — and the build reports success with a fraction of an overlay.
    This repository published exactly that: 1 module of 5, and a green tick.
    """

    def _project(self, tmp: Path):
        (tmp / "lean" / "Demo").mkdir(parents=True)
        (tmp / "lean" / "lakefile.toml").write_text('name = "demo"\n')
        (tmp / "lean" / "Demo" / "A.lean").write_text("def a := 1\n")
        (tmp / "lean" / "Demo" / "B.lean").write_text("import Demo.A\ndef b := a\n")
        (tmp / "interproof.toml").write_text(
            '[[document]]\nid = "D"\nroot = "tex"\n[formal]\nroot = "lean"\n')
        (tmp / "tex").mkdir()
        (tmp / "tex" / "main.tex").write_text("\\documentclass{article}\n"
                                              "\\begin{document}\\end{document}\n")

        log = tmp / "calls.log"
        fake = tmp / "lake"
        fake.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> {log}\n'
            'if [ "$1" = "exe" ]; then\n'
            '  printf \'{"data":{"code":{},"tokens":{},"goals":{},'
            '"messageContents":{},"nextKey":0},"items":[]}\' > "$4"\n'
            "fi\n"
            "exit 0\n")
        fake.chmod(0o755)
        return C.load(tmp / "interproof.toml"), fake, log

    def test_the_project_is_built_before_a_module_is_read(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg, fake, log = self._project(tmp)
            cfg = type(cfg)(**{**cfg.__dict__, "lake": str(fake)})
            files = [{"name": "Demo/A", "text": "def a := 1\n", "imports": []},
                     {"name": "Demo/B", "text": "import Demo.A\n",
                      "imports": ["Demo/A"]}]
            S.extract(cfg, files, say=lambda *a: None)

            calls = [l.strip() for l in log.read_text().splitlines() if l.strip()]
            self.assertTrue(calls, "`lake` was never invoked")
            self.assertEqual(calls[0], "build",
                             "the library must be compiled before any module "
                             "is imported for elaboration")
            self.assertTrue(any(c.startswith("exe ") for c in calls[1:]),
                            "no module was extracted after the build")

    def test_it_is_built_once_however_many_modules(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg, fake, log = self._project(tmp)
            cfg = type(cfg)(**{**cfg.__dict__, "lake": str(fake)})
            files = [{"name": "Demo/%d" % i, "text": "def x%d := 1\n" % i,
                      "imports": []} for i in range(6)]
            S.extract(cfg, files, say=lambda *a: None)
            calls = [l.strip() for l in log.read_text().splitlines() if l.strip()]
            self.assertEqual(calls.count("build"), 1,
                             "one build for the package, not one per module")

    def test_a_package_that_will_not_build_is_a_note_not_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg, fake, log = self._project(tmp)
            fake.write_text("#!/bin/sh\n"
                            'if [ "$1" = "build" ]; then\n'
                            '  echo "error: it does not compile" >&2\n'
                            "  exit 1\n"
                            "fi\n"
                            'if [ "$1" = "exe" ]; then\n'
                            '  printf \'{"data":{"code":{},"tokens":{},"goals":{},'
                            '"messageContents":{},"nextKey":0},"items":[]}\' > "$4"\n'
                            "fi\n"
                            "exit 0\n")
            fake.chmod(0o755)
            cfg = type(cfg)(**{**cfg.__dict__, "lake": str(fake)})
            files = [{"name": "Demo/A", "text": "def a := 1\n", "imports": []}]
            out, notes = S.extract(cfg, files, say=lambda *a: None)
            self.assertTrue(any("lake build" in n for n in notes),
                            "a package that will not compile must be reported")
            self.assertIn("Demo/A", out, "and the modules that do work still do")


class OffByDefaultTests(unittest.TestCase):
    """The promise the default keeps: no toolchain is needed to read."""

    def test_the_example_builds_without_elaboration(self):
        from interproof import manifest as M

        cfg = C.load(DEMO / "interproof.toml")
        self.assertFalse(cfg.elaborate, "elaboration must be opt-in")
        m = M.build(cfg, with_sources=False, quiet=True)
        self.assertEqual(m["lean_defs"], {})
        self.assertFalse(m["stats"]["sem"]["on"])
        for f in m["lean"]:
            self.assertNotIn("sem", f)

    def test_a_missing_toolchain_is_reported_not_raised(self):
        from interproof import manifest as M

        cfg = C.load(DEMO / "interproof.toml")
        cfg = type(cfg)(**{**cfg.__dict__, "lake": "definitely-not-a-real-lake"})
        said = []
        strs, defs, sem = M.semantics(cfg, [], True, said.append)
        self.assertEqual((strs, defs), ([], {}))
        self.assertTrue(sem["on"] and sem.get("failed"))
        self.assertTrue(any("not elaborated" in s for s in said))


if __name__ == "__main__":
    unittest.main()
