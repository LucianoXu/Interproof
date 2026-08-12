## Interproof — development shortcuts.
##
## The tool itself is `interproof`, and it is driven by an `interproof.toml`
## that lives with the material being read.  Nothing here is required to use
## it: this file exists because *this* repository also carries a case study
## whose sources are fetched from elsewhere, and fetching them is the one step
## the tool cannot do for you.
##
##     pip install -e .        # or: pipx install interproof
##     interproof init         # in the project holding the paper and the Lean
##     interproof serve        # read it, rebuilt as you edit
##     interproof build        # a folder to archive or publish

PQCPLUS := /data/vault/assets/1-projects/PQCPlus

.PHONY: all check serve demo sync clean distclean install

## The case study: sandbox/ must exist first (`make sync`).
all:
	interproof build

check:
	interproof check

serve:
	interproof serve

## The tracked example — the one thing a fresh clone can build with no
## material of its own.  It is also the regression test: the parsing rules
## were learned from real sources, and this is where they stay checked.
demo:
	cd examples/demo && interproof build -o ../../stignore-build/demo-site

install:
	python3 -m pip install -e .

## Populate the read-only source copies from the live project.  `sandbox/` is
## not tracked — this repository holds the framework, never the material being
## read — so this target creates it, and a fresh clone of the case study starts
## here.  A project of your own needs none of this: point `interproof.toml` at
## the sources where they already are.
sync:
	mkdir -p sandbox/lean sandbox/tex/common sandbox/tex/note \
	         sandbox/tex/P3-easypqc/sections
## the Lean tree is copied as a tree: a module is keyed by its path under the
## formal root, and the file index shows that structure
	rsync -am --include='*/' --include='*.lean' --exclude='*' \
	      $(PQCPLUS)/Formalization/PQCPlus/ sandbox/lean/
	cp $(PQCPLUS)/auto-research/P3-easypqc/main.tex       sandbox/tex/P3-easypqc/
	cp $(PQCPLUS)/auto-research/P3-easypqc/sections/*.tex sandbox/tex/P3-easypqc/sections/
	cp $(PQCPLUS)/auto-research/common/preamble.tex       sandbox/tex/common/
	cp $(PQCPLUS)/auto-research/common/refs.bib           sandbox/tex/common/
	cp "$(PQCPLUS)/notes/RHL-with-Arbitrary-Quantum-Adversary/Quantum Procedure Call Semantics.tex" \
	   sandbox/tex/note/main.tex
	cp "$(PQCPLUS)/notes/RHL-with-Arbitrary-Quantum-Adversary/appendix.tex" sandbox/tex/note/
	cp $(PQCPLUS)/auto-research/Lean*Spec.md              sandbox/
## The configuration is the one part of the case study that nothing else can
## regenerate: `sandbox/` comes from the live project and the PDFs come from
## latexmk, but this file exists only here.  It is copied rather than tracked
## in place, so that a fresh clone does not carry an `interproof.toml` at its
## root pointing at material that has not been fetched yet.
	@test -f interproof.toml || cp tools/case-study.toml interproof.toml
	@echo "sandbox/ populated, interproof.toml in place.  Now: make"

clean:
	rm -rf site

## also drop the compiled PDFs (`make` rebuilds them in ~20 s)
distclean: clean
	rm -rf stignore-build
