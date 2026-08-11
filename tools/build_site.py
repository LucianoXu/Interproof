#!/usr/bin/env python3
"""Inline everything into a single self-contained site/index.html."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "src"
OUT = ROOT / "site" / "index.html"

# a paper grain, as a data URI, so the page stays self-contained
GRAIN_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' "
    "numOctaves='3' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/>"
    "</filter><rect width='180' height='180' filter='url(#n)' opacity='.055'/></svg>"
)


def main() -> int:
    manifest = (ROOT / "site" / "manifest.json").read_text(encoding="utf-8")
    # `<` only ever occurs inside JSON strings, so escaping it keeps the payload
    # valid while making a stray `</script>` impossible
    manifest = manifest.replace("<", "\\u003c")
    tpl = (SRC / "index.template.html").read_text(encoding="utf-8")

    grain = "url(\"data:image/svg+xml;base64,%s\")" % base64.b64encode(
        GRAIN_SVG.encode()).decode()
    app_css = (SRC / "app.css").read_text(encoding="utf-8").replace(
        "--rail: 268px;", "--rail: 268px;\n  --grain: %s;" % grain)

    # the compiled documents themselves; the viewer draws from these.  Which
    # documents there are is the extractor's DOCS table, asked rather than repeated
    sys.path.insert(0, str(ROOT / "tools"))
    from extract import DOCS

    pdfs = {}
    for d in DOCS:
        if not d["pdf"].exists():
            print(f"!! {d['pdf'].relative_to(ROOT)} missing — run `make pdf` first",
                  file=sys.stderr)
            return 1
        pdfs[d["id"]] = base64.b64encode(d["pdf"].read_bytes()).decode()

    # `</script>` cannot occur in a base64 alphabet, so no escaping is needed
    pieces = {
        "/*FONTS*/": (SRC / "fonts.css").read_text(encoding="utf-8"),
        "/*APPCSS*/": app_css,
        "/*PDFJS*/": (SRC / "vendor/pdf.min.mjs").read_text(encoding="utf-8"),
        "/*PDFJSWORKER*/": (SRC / "vendor/pdf.worker.min.mjs").read_text(encoding="utf-8"),
        "/*MANIFEST*/": manifest,
        "/*PDFS*/": json.dumps(pdfs),
        "/*PDFVIEW*/": (SRC / "pdfview.js").read_text(encoding="utf-8"),
        "/*LEANVIEW*/": (SRC / "leanview.js").read_text(encoding="utf-8"),
        "/*APPJS*/": (SRC / "app.js").read_text(encoding="utf-8"),
    }
    html = tpl
    for k, v in pieces.items():
        if k not in html:
            print(f"!! placeholder {k} missing from template", file=sys.stderr)
            return 1
        html = html.replace(k, v, 1)

    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024 / 1024:.2f} MB")
    for k, v in pieces.items():
        print(f"   {k[2:-2]:>10s}  {len(v) / 1024:8.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
