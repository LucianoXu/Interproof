"""Interproof — a paper and its formalization, read side by side.

The correspondence is not invented here.  A formalization that cites its
paper — `P3:lem:one-sided` in a docstring — already holds it; this package
harvests it, checks it, places each cited statement in the compiled PDF with
SyncTeX, and builds a reader in which the two sides scroll together.

Public entry points:

    interproof.config.load()        read an `interproof.toml`
    interproof.pdf.compile_docs()   sources          -> PDF + .synctex.gz
    interproof.manifest.build()     sources + PDFs   -> the correspondence
    interproof.site.build_site()    manifest + PDFs  -> a self-contained folder
    interproof.serve.serve()        the same, live, rebuilt as the sources change
    interproof.check.check()        the correspondence, as a report
"""

__version__ = "0.2.0"

SCHEMA = 1          # manifest format; an artifact outlives the tool that made it
