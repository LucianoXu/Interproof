# Publishing what `interproof build` made

Interproof stops at a folder, on purpose. It does not do TLS, authentication or
domains, and adding them would mean maintaining a worse version of software you
already run. What it produces is a static site with no server-side anything, so
every way you already publish a static site works on it unchanged.

This page is the recipes, not a feature.

---

## The artifact

```
site/
  index.html          # self-contained: opens from the file system
  manifest.json
  pdf/<id>.pdf
  sources/…
  interproof.toml
  README.md
```

Two properties worth keeping straight, because they pull in different
directions and the default keeps both:

- **`index.html` alone is a working reader.** It inlines pdf.js, the manifest
  and the PDFs. Mail it, put it on a USB stick, open it by double-clicking.
- **The folder is an archive.** The sources that produced the reader travel
  with it, and `interproof build` inside `sources/` reproduces the whole thing.

The cost is that the PDFs are stored twice, once inlined and once as files.
`--no-inline` declines that trade for a paper where a megabyte or two matters —
but the resulting `index.html` fetches its PDFs, and browsers refuse `fetch`
under `file://`, so that variant **must** be served over HTTP.

---

## Sending it to one person

Send the folder as a zip, or send `index.html` by itself. The reader has a
**Download** button that reassembles the full folder — sources, PDFs, page and
configuration — from inside the page, so a colleague who was sent one file can
still get back to the sources.

## Serving it locally

```bash
python3 -m http.server 8000 --directory site
```

Worth doing even for a folder that works over `file://`: served over HTTP,
pdf.js takes its real worker thread instead of rendering on the main one, and
large PDFs scroll noticeably better.

## GitHub Pages

```bash
interproof build -o docs/reader     # or any path Pages is configured to serve
git add docs/reader && git commit -m "reader" && git push
```

Or as an action, so the reader tracks the paper:

```yaml
# .github/workflows/reader.yml
on:
  push: { branches: [main] }
jobs:
  reader:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: sudo apt-get update && sudo apt-get install -y texlive-latex-extra latexmk
      - run: pip install interproof
      - run: interproof check          # dangling citations fail the build
      - run: interproof build -o _site
      - uses: actions/upload-pages-artifact@v3
        with: { path: _site }
```

The `interproof check` step is the one worth copying even if you never publish:
it fails the build when a citation stops resolving, which is the moment a
`\label` was renamed on one side only.

## Netlify, Cloudflare Pages, S3, nginx

Nothing special. Publish directory `site/`, no build command needed if you
commit the folder, or `pip install interproof && interproof build -o site` if
you build there. For nginx, `root /srv/reader;` and `index index.html;` is the
whole of it. There is no routing: the reader deep-links through the URL
fragment (`#P3::lem:one-sided`), which never reaches the server.

---

## Exposing a *live* instance

`interproof serve` is a different thing and should be treated as one. It runs
`latexmk` on your files, it has no authentication, and it binds `127.0.0.1` by
default. It is a tool for the person writing the paper.

If you need to read a live instance from another machine, tunnel to it rather
than opening it up:

```bash
ssh -N -L 8777:127.0.0.1:8777 you@workstation     # then open localhost:8777
```

Tailscale, or any WireGuard mesh, does the same thing more comfortably.

`--host 0.0.0.0` exists and prints a warning. If you are reaching for it to
show someone the reader, `interproof build` and a static host is the answer
that does not put a LaTeX compiler on a network.
