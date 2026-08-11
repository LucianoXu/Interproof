PQCPLUS := /data/vault/assets/1-projects/PQCPlus
BUILD   := stignore-build

.PHONY: all pdf extract site sync serve clean distclean

all: pdf extract site

## Compile every document in the DOCS table of tools/extract.py, which is the
## one place this build knows which documents exist.  -synctex=1 is what makes
## label -> page,rectangle possible; latexmk handles incrementality itself.
pdf:
	python3 tools/build_pdf.py

extract: pdf
	python3 tools/extract.py

site:
	python3 tools/build_site.py

## Populate the read-only source copies from the live project.  `sandbox/` is
## not tracked — this repository holds the framework, never the material being
## read — so this target creates it, and a fresh clone starts here.
sync:
	mkdir -p sandbox/lean sandbox/tex/common sandbox/tex/note \
	         sandbox/tex/P3-easypqc/sections
	cp $(PQCPLUS)/Formalization/PQCPlus/*.lean            sandbox/lean/
	cp $(PQCPLUS)/auto-research/P3-easypqc/main.tex       sandbox/tex/P3-easypqc/
	cp $(PQCPLUS)/auto-research/P3-easypqc/sections/*.tex sandbox/tex/P3-easypqc/sections/
	cp $(PQCPLUS)/auto-research/common/preamble.tex       sandbox/tex/common/
	cp $(PQCPLUS)/auto-research/common/refs.bib           sandbox/tex/common/
	cp "$(PQCPLUS)/notes/RHL-with-Arbitrary-Quantum-Adversary/Quantum Procedure Call Semantics.tex" \
	   sandbox/tex/note/main.tex
	cp "$(PQCPLUS)/notes/RHL-with-Arbitrary-Quantum-Adversary/appendix.tex" sandbox/tex/note/
	cp $(PQCPLUS)/auto-research/Lean*Spec.md              sandbox/

serve:
	cd site && python3 -m http.server 8777 --bind 127.0.0.1

clean:
	rm -f site/manifest.json site/index.html

## also drop the compiled PDFs (`make` rebuilds them in ~20 s)
distclean: clean
	rm -rf $(BUILD)
