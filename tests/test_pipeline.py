"""The pipeline, checked against the tracked example.

Plain `unittest`, so `python3 -m unittest discover tests` is the whole of it --
no test runner to install beyond what the package already needs.

What is asserted here is mostly *structure*, not counts: a test that pins
"exactly 27 declarations" fails every time somebody improves the example, which
teaches people to ignore it.  The counts that are pinned are the ones that mean
something — zero dangling citations, every statement placed on a page — because
those are the claims the tool makes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interproof import SCHEMA
from interproof import config as C
from interproof import manifest as M
from interproof.check import check
from interproof.pdf import compile_docs
from interproof.synctex import have_text_layout

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"
HAVE_LATEX = shutil.which("latexmk") is not None
HAVE_TEXT = have_text_layout()


class ConfigTests(unittest.TestCase):
    def test_demo_config_loads(self):
        cfg = C.load(DEMO / "interproof.toml")
        self.assertTrue(cfg.documents, "the example must define documents")
        self.assertTrue(cfg.lean_files(), "the example must have Lean sources")
        for d in cfg.documents:
            self.assertTrue(d.main_path.is_file(), f"{d.id}: {d.main} missing")
            self.assertTrue(d.source_files(), f"{d.id}: no source files matched")

    def test_paths_are_relative_to_the_file(self):
        """A configuration must travel with its material.

        The property is checked by moving the whole project somewhere else and
        loading it again: anything absolute would break, and so would anything
        resolved against the working directory.
        """
        with tempfile.TemporaryDirectory() as tmp:
            moved = Path(tmp) / "elsewhere"
            shutil.copytree(DEMO, moved)
            cfg = C.load(moved / "interproof.toml")
            self.assertEqual(cfg.root, moved)
            for d in cfg.documents:
                self.assertTrue(d.main_path.is_file())

    def test_missing_config_says_what_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(C.ConfigError) as e:
                C.load(start=Path(tmp))
            self.assertIn("init", str(e.exception))

    def test_bad_document_root_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "interproof.toml"
            p.write_text('[[document]]\nid="X"\nroot="nowhere"\n'
                         '[formal]\nroot="nowhere"\n')
            with self.assertRaises(C.ConfigError) as e:
                C.load(p)
            self.assertIn("nowhere", str(e.exception))

    def test_grammar_is_configurable(self):
        """A project writing `t:foo` must be readable without touching code."""
        g = C.Grammar(label_prefixes=["t"], environments=["observation"])
        self.assertTrue(g.label_re.search("see t:main"))
        self.assertIsNone(g.label_re.search("see lem:main"))
        self.assertIn("observation", g.env_re)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = C.load(DEMO / "interproof.toml")
        if HAVE_LATEX:
            compile_docs(cls.cfg, quiet=True)
        cls.man = M.build(cls.cfg, quiet=True)

    def test_schema_and_provenance(self):
        self.assertEqual(self.man["schema"], SCHEMA)
        self.assertTrue(self.man["tool"].startswith("interproof "))
        self.assertEqual(self.man["config"], self.cfg.text)

    def test_no_dangling_citations(self):
        """The example must not ship a broken citation.

        It would be indistinguishable, to a first-time user, from the tool
        being broken.
        """
        self.assertEqual(self.man["unresolved"], [],
                         M.dangling(self.man))

    def test_the_correspondence_is_populated(self):
        s = self.man["stats"]
        self.assertGreater(s["links"], 0, "no citations were recognised")
        self.assertGreater(s["linked_items"], 0)
        self.assertGreater(s["lean_decls"], 0)
        self.assertGreater(s["tex_refs"], 0, "no \\Cref edges between statements")
        self.assertGreater(s["decl_refs"], 0, "no name edges between declarations")

    def test_all_three_citation_forms_are_exercised(self):
        vias = {l["via"] for l in self.man["links"]}
        self.assertIn("label", vias)
        self.assertIn("title", vias, "the example must cite something by title")

    def test_module_and_declaration_citations_both_occur(self):
        owners = {l["decl"] is None for l in self.man["links"]}
        self.assertEqual(owners, {True, False},
                         "the example must cite from module prose and from a "
                         "docstring, since the two are banded differently")

    def test_modules_are_in_import_order(self):
        seen: set[str] = set()
        for f in self.man["lean"]:
            for imp in f["imports"]:
                self.assertIn(imp, seen,
                              f"{f['name']} precedes its import {imp}")
            seen.add(f["name"])

    def test_a_gap_is_left_uncovered(self):
        """Coverage is the question the reader answers; a 100% example cannot
        demonstrate it."""
        envs = self.cfg.grammar.environments
        uncovered = [k for k, it in self.man["tex"].items()
                     if it["kind"] in envs and not self.man["by_item"].get(k)]
        self.assertTrue(uncovered, "the example should leave a statement "
                                   "deliberately unformalized")

    def test_sources_travel_with_the_manifest(self):
        paths = {s["path"] for s in self.man["sources"]}
        self.assertTrue(paths, "no LaTeX sources were collected")
        for p in paths:
            self.assertFalse(p.startswith("/"), f"{p} is absolute")
            self.assertNotIn("..", Path(p).parts, f"{p} escapes the artifact")

    @unittest.skipUnless(HAVE_LATEX, "needs latexmk")
    def test_every_statement_is_placed_in_its_pdf(self):
        envs = self.cfg.grammar.environments
        missing = [k for k, it in self.man["tex"].items()
                   if it["kind"] in envs and not it["rect"]]
        self.assertEqual(missing, [], "synctex could not place these")

    @unittest.skipUnless(HAVE_LATEX, "needs latexmk")
    def test_check_passes(self):
        self.assertEqual(check(self.cfg, self.man), 0)

    def test_the_page_geometry_is_measured_and_not_only_bracketed(self):
        """PyMuPDF is a dependency, and this is what it is for.

        Without it `tighten` cannot run and every band falls back to the raw
        SyncTeX bracket, which sits a line low.  That degradation is invisible
        in the manifest -- the rectangles look entirely reasonable -- so it is
        asserted here rather than trusted.
        """
        self.assertTrue(HAVE_TEXT,
                        "install pymupdf: without it every highlight in the "
                        "reader ends one line below its statement")

    @unittest.skipUnless(HAVE_LATEX and HAVE_TEXT, "needs latexmk and pymupdf")
    def test_every_band_ends_on_a_line_of_text(self):
        """A band's bottom edge lands on the bottom of a real typeset line.

        This is the claim the reader makes about itself, and the one way it has
        actually been wrong: the SyncTeX bracket ends where the *next*
        paragraph begins, so an untightened band ends in the whitespace between
        two paragraphs -- one line too low, and visibly so.
        """
        import pymupdf

        for d in self.cfg.documents:
            doc = pymupdf.open(d.pdf)
            for key, it in self.man["tex"].items():
                if it["doc"] != d.id or not it["rect"]:
                    continue
                r = it["rect"]
                page = doc[r["end_page"] - 1]
                bottoms = [ln["bbox"][3]
                           for blk in page.get_text("dict")["blocks"]
                           for ln in blk.get("lines", [])]
                near = min((abs(b - r["bottom"]) for b in bottoms), default=1e9)
                self.assertLess(
                    near, 1.5,
                    f"{key}: band ends at y={r['bottom']:.1f} on page "
                    f"{r['end_page']}, which is {near:.1f}pt from any line of "
                    f"text -- it is ending in a paragraph gap")


class EmptyCorrespondenceTests(unittest.TestCase):
    """The outcome that reads as success: nothing resolved, nothing dangling.

    A first-time user meets this more often than any other result, because the
    precondition — a formalization that cites its paper — is the thing most
    projects have not done yet.  It has to fail loudly and say why.
    """

    def project(self, tmp: str, *, label: str, cite: str) -> Path:
        root = Path(tmp)
        (root / "paper").mkdir()
        (root / "Formal").mkdir()
        (root / "paper" / "main.tex").write_text(
            "\\documentclass{article}\n\\usepackage{amsthm}\n"
            "\\newtheorem{lemma}{Lemma}\n\\begin{document}\n"
            "\\begin{lemma}[a small one]\\label{%s}$1+1=2$.\\end{lemma}\n"
            "\\end{document}\n" % label)
        (root / "Formal" / "A.lean").write_text(
            "/-! # A module\n%s -/\n\n"
            "/-- Adding one to one. -/\ntheorem small : 1 + 1 = 2 := rfl\n" % cite)
        p = root / "interproof.toml"
        p.write_text('[project]\ntitle = "T"\n\n[[document]]\nid = "paper"\n'
                     'root = "paper"\n\n[formal]\nroot = "Formal"\n')
        return p

    def test_no_citations_fails_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = C.load(self.project(tmp, label="lem:small",
                                      cite="This module proves things."))
            man = M.build(cfg, quiet=True)
            self.assertEqual(man["stats"]["links"], 0)
            self.assertEqual(check(cfg, man), 1,
                             "zero citations is not a passing check")
            hint = "\n".join(M.empty_correspondence(cfg, man["lean"]))
            self.assertIn("CITING", hint)

    def test_an_unknown_label_prefix_is_diagnosed(self):
        """The case worth catching: the project *does* cite, in a notation the
        configuration was never told about."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = C.load(self.project(
                tmp, label="t:small",
                cite="The base case is t:small; see t:small and t:big."))
            man = M.build(cfg, quiet=True)
            self.assertEqual(man["stats"]["links"], 0)
            hint = "\n".join(M.empty_correspondence(cfg, man["lean"]))
            self.assertIn("t:", hint)
            self.assertIn("label_prefixes", hint)
            self.assertNotIn("CITING", hint, "this is the wrong diagnosis here")


@unittest.skipUnless(HAVE_LATEX, "needs latexmk")
class BuildTests(unittest.TestCase):
    """`interproof build` produces a folder that stands on its own."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "site"
        r = subprocess.run(
            [sys.executable, "-m", "interproof.cli", "build",
             "-c", str(DEMO / "interproof.toml"), "-o", str(cls.out)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent))
        cls.proc = r

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build_succeeds(self):
        self.assertEqual(self.proc.returncode, 0,
                         self.proc.stdout + self.proc.stderr)

    def test_the_folder_holds_everything_it_claims_to(self):
        for p in ("index.html", "manifest.json", "interproof.toml", "README.md"):
            self.assertTrue((self.out / p).is_file(), f"{p} missing")
        self.assertTrue(list((self.out / "pdf").glob("*.pdf")), "no PDFs")
        self.assertTrue(list((self.out / "sources").rglob("*.tex")), "no LaTeX")
        self.assertTrue(list((self.out / "sources").rglob("*.lean")), "no Lean")

    def test_no_placeholder_survives_into_the_page(self):
        html = (self.out / "index.html").read_text(encoding="utf-8")
        for ph in ("/*BOOT*/", "/*APPJS*/", "/*PDFJS*/", "/*APPCSS*/",
                   "/*PDFVIEW*/", "/*LEANVIEW*/", "/*DOWNLOAD*/",
                   "/*FONTS*/", "<!--TITLE-->"):
            self.assertNotIn(ph, html, f"{ph} was never filled in")

    def test_the_page_is_self_contained(self):
        """Nothing may be fetched from a network: the artifact has to open on a
        laptop with no internet, which is most of the point of it."""
        html = (self.out / "index.html").read_text(encoding="utf-8")
        for bad in ("http://", "https://cdn", "src=\"http"):
            self.assertNotIn(bad + "cdn", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<link rel=\"stylesheet\"", html)


if __name__ == "__main__":
    unittest.main()
