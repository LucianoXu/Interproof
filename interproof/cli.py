"""`interproof` — the command line.

Four verbs, and the two that matter are `build` and `serve`: the same pipeline,
ending either in a folder somebody can archive and hand around, or in a local
server that rebuilds while the sources are being edited.

    sources ──latexmk──> PDF + .synctex.gz ──parse──> manifest ──┬─> folder   (build)
                                                                 └─> HTTP+SSE (serve)

Everything is driven by an `interproof.toml` that lives with the material.  The
tool is never configured by editing the tool.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_NAME, Config, ConfigError, load
from .pdf import PdfBuildError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="interproof",
        description="A paper and its formalization, read side by side.")
    p.add_argument("--version", action="version",
                   version=f"interproof {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_config(sp):
        sp.add_argument("-c", "--config", type=Path, default=None,
                        help=f"the {CONFIG_NAME} to use "
                             f"(default: the nearest one at or above the cwd)")
        return sp

    # Elaboration is a property of the project, so it lives in the
    # configuration; these say "not this time" (or "just this once") without
    # editing it, which is what a CI job and a quick local build both want.
    # Three states, not two: unset means whatever the project said.
    def with_elaborate(sp):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--elaborate", dest="elaborate", action="store_true",
                       default=None,
                       help="run the formalization through Lean for hover "
                            "types, go-to-definition and its own colouring; "
                            "needs a toolchain and a project that builds")
        g.add_argument("--no-elaborate", dest="elaborate", action="store_false",
                       help="read the formal sources as text, whatever "
                            "[formal] elaborate says")
        return sp

    sp = sub.add_parser("init", help=f"write an {CONFIG_NAME} for this project")
    sp.add_argument("dir", nargs="?", type=Path, default=Path("."),
                    help="the project root (default: here)")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an existing configuration")

    sp = with_elaborate(
        with_config(sub.add_parser("build", help="compile a self-contained folder")))
    sp.add_argument("-o", "--out", type=Path, default=None,
                    help="output folder (default: project.out, or ./site)")
    sp.add_argument("--no-inline", action="store_true",
                    help="do not inline the PDFs into index.html; the folder then "
                         "needs to be served over HTTP rather than opened directly")
    sp.add_argument("--skip-pdf", action="store_true",
                    help="trust the PDFs already in the build directory")
    sp.add_argument("--force-pdf", action="store_true",
                    help="recompile from scratch (latexmk -g)")

    sp = with_elaborate(
        with_config(sub.add_parser("serve", help="read it live, rebuilt as you edit")))
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8777)
    sp.add_argument("--no-watch", action="store_true",
                    help="serve what is there and do not rebuild")
    sp.add_argument("--open", action="store_true", help="open a browser")
    sp.add_argument("--skip-pdf", action="store_true",
                    help="do not compile the PDFs at startup")

    # No `--elaborate` here on purpose: `check` asks whether the citations
    # resolve, and no answer it gives changes with the types.  It is the
    # command a CI job runs on every push, and making that wait for Lean would
    # be minutes spent to learn nothing.
    sp = with_config(sub.add_parser("check", help="report the correspondence, "
                                                  "and fail on dangling citations"))
    sp.add_argument("--strict", action="store_true",
                    help="also fail when a statement has no counterpart")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--skip-pdf", action="store_true")

    sp = with_config(sub.add_parser("pdf", help="compile the documents only"))
    sp.add_argument("--force", action="store_true")

    sp = with_elaborate(
        with_config(sub.add_parser("manifest", help="write the correspondence "
                                                    "as JSON and stop")))
    sp.add_argument("-o", "--out", type=Path, default=None)
    sp.add_argument("--skip-pdf", action="store_true")

    args = p.parse_args(argv)
    try:
        return DISPATCH[args.cmd](args)
    except ConfigError as e:
        print(f"interproof: {e}", file=sys.stderr)
        return 2
    except PdfBuildError as e:
        print(f"interproof: LaTeX failed.\n{e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


# --------------------------------------------------------------------------

def _prepare(args, *, with_sources: bool = True,
             elaborate: bool | None = None) -> tuple[Config, dict]:
    """The shared front half: configuration, PDFs, manifest.

    `elaborate` is three-valued all the way down — `None` is "whatever the
    project configured", and only a command that has its own reason to differ
    passes anything else.
    """
    from . import manifest as M
    from .pdf import compile_docs

    cfg = load(args.config)
    if not getattr(args, "skip_pdf", False):
        compile_docs(cfg, force=getattr(args, "force_pdf", False))
    if elaborate is None:
        elaborate = getattr(args, "elaborate", None)
    return cfg, M.build(cfg, with_sources=with_sources, elaborate=elaborate)


def cmd_init(args) -> int:
    from .init import init_project
    return init_project(args.dir, force=args.force)


def cmd_build(args) -> int:
    from . import manifest as M
    from .site import build_site

    cfg, manifest = _prepare(args)
    out = (args.out or cfg.out_dir).resolve()
    M.report(manifest)
    build_site(cfg, manifest, out, inline=not args.no_inline)
    return 0


def cmd_serve(args) -> int:
    from .serve import serve

    cfg = load(args.config)
    return serve(cfg, host=args.host, port=args.port,
                 watch=not args.no_watch, open_browser=args.open,
                 skip_pdf=args.skip_pdf, elaborate=args.elaborate)


def cmd_check(args) -> int:
    from .check import check

    cfg, manifest = _prepare(args, with_sources=False, elaborate=False)
    return check(cfg, manifest, strict=args.strict, as_json=args.json)


def cmd_pdf(args) -> int:
    from .pdf import compile_docs

    cfg = load(args.config)
    compile_docs(cfg, force=args.force)
    return 0


def cmd_manifest(args) -> int:
    from . import manifest as M

    cfg, manifest = _prepare(args)
    out = (args.out or (cfg.out_dir / "manifest.json")).resolve()
    M.write(manifest, out)
    M.report(manifest, out=out)
    return 0


DISPATCH = {
    "init": cmd_init,
    "build": cmd_build,
    "serve": cmd_serve,
    "check": cmd_check,
    "pdf": cmd_pdf,
    "manifest": cmd_manifest,
}


if __name__ == "__main__":
    sys.exit(main())
