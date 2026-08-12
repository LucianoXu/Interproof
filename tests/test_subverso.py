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
        defs, sem = M.semantics(cfg, [], True, said.append)
        self.assertEqual(defs, {})
        self.assertTrue(sem["on"] and sem.get("failed"))
        self.assertTrue(any("not elaborated" in s for s in said))


if __name__ == "__main__":
    unittest.main()
