"""The correspondence as a report, with an exit code.

This is the `span`-style consistency check, and it is the part of Interproof
that belongs in continuous integration: a citation that resolves to nothing
means one side was renamed and the other was not, and the cheapest moment to
learn that is the commit that did it — not the next time somebody opens the
reader.

Four things are reported, and only the first two are errors by default:

- **dangling** — a citation naming a statement no document holds.  Something is
  wrong *now*, in a file, at a line.
- **duplicate** — a statement claimed as a correspondence by two declarations.
  A correspondence is one to one: one of the claims is really a mention, and
  writing `cf.` before its label is how it says so.
- **unlocated** — a statement the PDF geometry could not place.  The reader
  still works; that item simply cannot be scrolled to.
- **uncovered** — a statement with no corresponding declaration.  This is not
  a defect at all: it is the state of the mechanization, which is the question
  the reader exists to answer.  `--strict` turns it into one, for a project
  that has decided its paper must stay fully formalized.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .manifest import dangling, duplicates


def check(cfg: Config, manifest: dict, *, strict: bool = False,
          as_json: bool = False) -> int:
    s = manifest["stats"]
    dang = dangling(manifest)
    dup = duplicates(manifest)

    # a statement counts as formalized when a declaration *corresponds* to it
    # or to a part of it; mentions talk about it, which is not the same claim
    covered = set(manifest.get("covered") or manifest["by_item"])
    corr_to = lambda k: k in covered
    unlocated = sorted(
        f"{it['doc']}::{it['label']}"
        for it in manifest["tex"].values()
        if it["kind"] in cfg.grammar.environments and not it["rect"])
    uncovered = sorted(
        f"{it['doc']}::{it['label']}"
        for k, it in manifest["tex"].items()
        if it["kind"] in cfg.grammar.environments and not corr_to(k))

    empty = not s["links"]
    bad = empty or bool(dang) or bool(dup) or (strict and bool(uncovered))

    if as_json:
        print(json.dumps({
            "ok": not bad,
            "empty": empty,
            "dangling": dang, "duplicate": dup,
            "unlocated": unlocated, "uncovered": uncovered,
            "stats": s,
        }, ensure_ascii=False, indent=2))
        return 1 if bad else 0

    print(f"{cfg.title}  —  {s['tex_items']} statements, {s['lean_decls']} "
          f"declarations, {s['links']} citations "
          f"({s.get('corr_links', s['links'])} correspondences)")
    print()
    for d in manifest["docs"]:
        items = [k for k, it in manifest["tex"].items()
                 if it["doc"] == d["id"] and it["kind"] in cfg.grammar.environments]
        linked = [k for k in items if corr_to(k)]
        placed = [k for k in items if manifest["tex"][k]["rect"]]
        print(f"  {d['id']:8s} {len(linked):3d}/{len(items):<3d} formalized"
              f"   {len(placed):3d}/{len(items):<3d} located in the PDF"
              f"   {d['title']}")
    print()

    if empty:
        # "0 dangling" over an empty set is true and says nothing.  A run that
        # read no correspondence at all has not passed; the reason was printed
        # while the manifest was built, and this is the verdict.
        print("nothing    no citation resolved — there is no correspondence "
              "here to read.")
        print("           See CITING.md for what a citation looks like, or "
              "[grammar] label_prefixes")
        print("           in the configuration if this project spells its "
              "labels differently.")
        print()
        print("FAIL")
        return 1

    if dang:
        print(f"dangling  {sum(len(v) for v in dang.values())} citations resolve "
              f"to nothing:")
        for lbl, where in dang.items():
            print(f"   ! {lbl:28s} {', '.join(where[:6])}"
                  + (f"  (+{len(where) - 6} more)" if len(where) > 6 else ""))
    else:
        print("dangling  none — every citation resolves")

    if dup:
        print(f"duplicate {len(dup)} statements are claimed by more than one "
              f"declaration — a correspondence is one to one:")
        for key, who in dup.items():
            print(f"   ! {key:28s} {', '.join(who[:4])}"
                  + (f"  (+{len(who) - 4} more)" if len(who) > 4 else ""))
        print("           the declarations that are *about* the statement "
              "rather than being it should say `cf.` before the label")

    if unlocated:
        print(f"unlocated {len(unlocated)} statements have no place in their PDF; "
              f"they cannot be scrolled to:")
        for k in unlocated[:12]:
            print(f"   ? {k}")
        if len(unlocated) > 12:
            print(f"   ? +{len(unlocated) - 12} more")

    if uncovered:
        head = "uncovered" if strict else "gap      "
        print(f"{head} {len(uncovered)} statements have no counterpart in the "
              f"formal sources" + (":" if strict else " — the coverage this "
                                   "reader exists to show"))
        if strict:
            for k in uncovered[:20]:
                print(f"   ! {k}")
            if len(uncovered) > 20:
                print(f"   ! +{len(uncovered) - 20} more")

    print()
    print("FAIL" if bad else "ok")
    return 1 if bad else 0
