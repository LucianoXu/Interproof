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

    def test_only_a_label_is_a_citation(self):
        """A title is prose, and prose does not cite.

        Naming an item by kind and title — `Definition (frame lifting)` — was
        read as a citation once.  It matched sentences that were citing
        nothing, and the extent it produced was wrong often enough that the
        reader could not be trusted; this pins the removal.
        """
        from interproof.lean import Citations, parse_file

        cites = Citations.of(self.cfg)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "M.lean"
            p.write_text("/-- Definition (frame lifting), and Lemma (locality). -/\n"
                         "def a : Nat := 0\n"
                         "/-- Agreement on a frame, def:frame in the note. -/\n"
                         "def b : Nat := 0\n", encoding="utf-8")
            _, _, refs = parse_file(p, "M", cites)
        self.assertEqual([r["label"] for r in refs], ["def:frame"])

    def test_members_are_read_and_are_their_own_declarations(self):
        """A constructor is a declaration, with its own span.

        A paper's grammar has productions and its definitions have clauses, and
        the counterpart of one of those is one constructor — not the whole
        `inductive`.  Lean names every one, so they are read rather than
        annotated.
        """
        syn = next(f for f in self.man["lean"] if f["name"] == "Demo/Syntax")
        by = {d["name"]: d for d in syn["decls"]}
        self.assertIn("Cmd.whileDo", by, "constructors are not being read")
        self.assertIn("Proc.params", by, "structure fields are not being read")
        self.assertEqual(by["Cmd.whileDo"]["parent"], "Cmd")
        self.assertEqual(by["Cmd.whileDo"]["kind"], "constructor")
        self.assertEqual(by["Proc.params"]["kind"], "field")
        # a member's span is its own lines, inside its parent's
        m, p = by["Cmd.whileDo"], by["Cmd"]
        self.assertGreaterEqual(m["line"], p["line"])
        self.assertLessEqual(m["end_line"], p["end_line"])
        self.assertLess(m["end_line"] - m["line"], p["end_line"] - p["line"])
        # `deriving Repr` closes the body and belongs to no constructor
        self.assertNotIn("deriving", "\n".join(
            syn["text"].split("\n")[m["line"] - 1:m["end_line"]]))

    def test_a_citation_on_a_member_belongs_to_the_member(self):
        """Innermost wins.

        A constructor sits inside its datatype's span, so first-match would
        hand the citation to the parent and band the whole datatype for a claim
        about one production.
        """
        on_member = [l for l in self.man["links"] if l["decl"] == "Cmd.whileDo"]
        self.assertTrue(on_member, "the example must cite a constructor")

    def test_a_label_path_peels_to_the_statement_it_names(self):
        """`def:cmd:while` is a part of `def:cmd`.

        Until the paper carries an anchor by that name the citation still names
        the statement, so the tail is peeled and recorded rather than dangled —
        coarser than it was written, never absent.
        """
        ref = {"label": "def:cmd:nosuchpart", "doc_hint": "", "file": "M",
               "line": 1, "decl": None}
        known = {d.id: ({"def:cmd"} if d.id == "paper" else set())
                 for d in self.cfg.documents}
        links, unresolved = M.resolve([ref], known, self.cfg.documents)
        self.assertEqual(unresolved, [], "a path must not dangle")
        self.assertEqual(links[0]["label"], "def:cmd")
        self.assertEqual(links[0]["sub"], "nosuchpart")
        self.assertEqual(links[0]["key"], "paper::def:cmd")

        # and when the anchor *does* exist, nothing is peeled
        self.assertIn("paper::def:cmd:while", self.man["tex"])
        got = [l for l in self.man["links"] if l["key"] == "paper::def:cmd:while"]
        self.assertTrue(got)
        self.assertNotIn("sub", got[0])

    def test_the_viewer_is_told_what_a_label_looks_like(self):
        """The page linkifies what the build read, not a list of its own."""
        self.assertEqual(self.man["grammar"]["label_prefixes"],
                         list(self.cfg.grammar.label_prefixes))

    def test_an_anchor_is_a_part_of_a_statement(self):
        """`% @interproof anchor def:aeval:arith` names one clause.

        The directive is a LaTeX comment, so the paper still compiles for
        somebody who has never heard of this tool.
        """
        anch = {k: it for k, it in self.man["tex"].items() if it["kind"] == "anchor"}
        self.assertTrue(anch, "the example must carry anchors")
        for k, it in anch.items():
            self.assertTrue(it["parent"], f"{k} has no enclosing statement")
            self.assertTrue(k.startswith(f"{it['doc']}::{it['parent']}:"),
                            f"{k} does not extend its parent's label")

    def test_a_citation_reaches_the_anchor_itself(self):
        """Not peeled: the anchor exists, so the link is to the clause."""
        keys = {l["key"] for l in self.man["links"]}
        self.assertIn("paper::def:aeval:arith", keys)
        self.assertIn("paper::def:aeval:bool", keys)
        for l in self.man["links"]:
            if l["key"] == "paper::def:aeval:arith":
                self.assertEqual(l["decl"], "AExp.eval")
                self.assertNotIn("sub", l, "an existing anchor must not peel")

    @unittest.skipUnless(HAVE_LATEX, "needs latexmk")
    def test_an_anchor_bands_less_than_its_statement(self):
        """The whole point: a tighter rectangle than the statement it is in.

        `def:aeval` runs across a page break; each of its two clauses sits on
        one page and covers a fraction of it.  If an anchor ever bands as much
        as its parent, the geometry has stopped saying anything.
        """
        def height(k):
            r = self.man["tex"][k]["rect"]
            self.assertIsNotNone(r, f"{k} was not located")
            pages = r["end_page"] - r["page"]
            return pages * 2000 + (r["bottom"] - r["top"])

        whole = height("paper::def:aeval")
        for part in ("paper::def:aeval:arith", "paper::def:aeval:bool"):
            self.assertLess(height(part), whole,
                            f"{part} bands no tighter than the statement it is part of")
            self.assertEqual(self.man["tex"][part]["rect"]["page"],
                             self.man["tex"][part]["rect"]["end_page"],
                             f"{part} should sit on one page")

    @unittest.skipUnless(HAVE_LATEX and HAVE_TEXT, "needs latexmk and PyMuPDF")
    def test_spans_of_one_line_are_measured_apart(self):
        """The reason step 3 exists.

        `def:aeval:arith`'s three equations are separated by `\\qquad` inside
        one `\\[…\\]`: they share a typeset line, and SyncTeX has one box for
        all of them.  The marked build measures each, so they must come back
        on the same line, in source order, not overlapping — and each must be
        narrower than the line they sit on.
        """
        parts = ["paper::def:aeval:arith:" + p for p in ("lit", "var", "add")]
        boxes = []
        for k in parts:
            it = self.man["tex"].get(k)
            self.assertIsNotNone(it, f"{k} is missing")
            self.assertTrue(it["rects"], f"{k} was not measured by the marked build")
            self.assertEqual(len(it["rects"]), 1, f"{k} should not wrap")
            boxes.append(it["rects"][0])

        self.assertEqual(len({b["page"] for b in boxes}), 1, "all on one page")
        self.assertEqual(len({round(b["top"], 1) for b in boxes}), 1,
                         "all on one typeset line — that is the whole point")
        for a, b in zip(boxes, boxes[1:]):
            self.assertLess(a["x"] + a["w"], b["x"],
                            "measured spans overlap; the regions are wrong")
        line = self.man["tex"]["paper::def:aeval:arith"]["rect"]
        for b, k in zip(boxes, parts):
            self.assertLess(b["w"], line["w"], f"{k} is as wide as the whole clause")

    def test_parts_of_one_statement_get_different_tints(self):
        """A colour is what tells three spans of one line apart, and what
        carries a part across the gutter."""
        sib = [it for it in self.man["tex"].values()
               if it["kind"] == "anchor" and it["parent"] == "def:aeval:arith"]
        self.assertEqual(len(sib), 3)
        self.assertEqual(sorted(it["tint"] for it in sib), [0, 1, 2])

    def test_module_and_declaration_citations_both_occur(self):
        owners = {l["decl"] is None for l in self.man["links"]}
        self.assertEqual(owners, {True, False},
                         "the example must cite from module prose and from a "
                         "docstring, since the two are banded differently")

    def test_mention_and_correspondence_are_told_apart(self):
        """`cf.` demotes a citation to a mention, and module prose can only
        mention — no declaration owns it."""
        for l in self.man["links"]:
            if l["decl"] is None:
                self.assertFalse(l["corr"], f"module prose corresponds: {l}")
        upd = self.man["by_item"]["note::def:update"]
        corr = sorted({l["decl"] for l in upd if l["corr"]})
        self.assertEqual(corr, ["Store.update"],
                         "exactly one declaration is the update")
        self.assertTrue(any(not l["corr"] and l["decl"] for l in upd),
                        "the example should keep a cf. mention of it")
        # the correspondence comes first, so whoever takes the first citing
        # declaration gets the one that is the item
        self.assertTrue(upd[0]["corr"])

    def test_correspondence_is_one_to_one(self):
        self.assertEqual(M.duplicates(self.man), {},
                         "two declarations claim one statement")

    def test_coverage_rolls_up_through_anchors(self):
        """`def:aeval` is formalized clause by clause: nothing corresponds to
        the statement whole, and it must still count as covered."""
        own = self.man["by_item"].get("paper::def:aeval", [])
        self.assertFalse(any(l["corr"] for l in own),
                         "the roll-up case needs a statement whose own "
                         "citations are all mentions")
        self.assertIn("paper::def:aeval", self.man["covered"])
        self.assertNotIn("paper::lem:bigstep-det", self.man["covered"])

    def test_proof_steps_are_cited_from_the_proof_body(self):
        """A comment inside the proof belongs to the theorem, and the anchor
        it cites is a part of the paper's proof."""
        for part in ("ind", "base", "step"):
            ls = self.man["by_item"]["paper::thm:soundness:" + part]
            self.assertEqual([l["decl"] for l in ls], ["soundness"])
            self.assertTrue(ls[0]["corr"])

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
