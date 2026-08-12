"""A stand-in for `subverso-extract-mod`, so the reader can be tested without Lean.

Elaboration needs a toolchain and a formalization that compiles, and neither is
available to a unit test — but the part of Interproof that can be *wrong* is
not the elaboration, it is the translation: SubVerso's interned export into
positions in a file.  That is pure, and this module gives it something to
translate.

What comes out is the real shape — `{"data": {"nextKey", "tokens",
"messageContents", "goals", "code"}, "items": [...]}`, with `Highlighted`
interned by key and `deriving ToJson`'s one-key-object encoding for sums — over
a real Lean file, crudely tokenized.  The *kinds* are invented, since only a
compiler knows them; the *structure and the positions* are exactly what the
translation has to survive, including block comments spanning lines and the
non-ASCII identifiers a formalization is written in.
"""

from __future__ import annotations

import re

# a token that is worth a `Token` node; everything else becomes `text`
WORD = re.compile(r"[A-Za-z_À-ɏͰ-Ͽ][\w'À-ɏͰ-Ͽ₀-ₜ]*")


class Fake:
    """Builds one module's export, interning as SubVerso does."""

    def __init__(self) -> None:
        self.next = 0
        self.tokens: dict[str, dict] = {}
        self.code: dict[str, dict] = {}
        self.tok_ix: dict[tuple, int] = {}
        self.code_ix: dict[str, int] = {}

    def _key(self) -> int:
        k = self.next
        self.next += 1
        return k

    def token(self, kind: object, content: str) -> int:
        import json
        sig = (json.dumps(kind, sort_keys=True), content)
        if sig not in self.tok_ix:
            k = self._key()
            self.tokens[str(k)] = {"kind": kind, "content": content}
            self.tok_ix[sig] = k
        return self.tok_ix[sig]

    def node(self, node: dict) -> int:
        import json
        sig = json.dumps(node, sort_keys=True)
        if sig not in self.code_ix:
            k = self._key()
            self.code[str(k)] = node
            self.code_ix[sig] = k
        return self.code_ix[sig]

    def text(self, s: str) -> int:
        return self.node({"text": {"str": s}})

    def seq(self, keys: list[int]) -> int:
        return self.node({"seq": {"highlights": keys}})

    def export(self, items: list[dict]) -> dict:
        return {
            "data": {"nextKey": self.next, "tokens": self.tokens,
                     "messageContents": {}, "goals": {}, "code": self.code},
            "items": items,
        }


KEYWORDS = {"import", "def", "theorem", "lemma", "structure", "inductive",
            "namespace", "end", "open", "by", "where", "fun", "match", "with",
            "instance", "abbrev", "class", "deriving", "example", "section"}


def _kind(word: str, defining: bool) -> object:
    """A plausible `Token.Kind` for a word, in SubVerso's JSON encoding."""
    if word in KEYWORDS:
        return {"keyword": {"name": ["Lean", "Parser", word], "occurrence": word,
                            "docs": None}}
    if word[0].islower() and len(word) <= 2:
        return {"var": {"name": "_uniq." + word, "type": "α", "typeFormat": None}}
    return {"const": {"name": word.split("."), "signature": f"{word} : Type",
                      "docs": f"What {word} is." if defining else None,
                      "isDef": defining, "signatureFormat": None}}


def module(text: str, *, split: int = 3) -> dict:
    """One Lean module, as `subverso-extract-mod` would have written it.

    `split` is how many commands the file is cut into.  More than one matters:
    the translation locates each command in the file by searching from where
    the last one ended, and a single command would never exercise that.
    """
    f = Fake()
    lines = text.split("\n")
    per = max(1, (len(lines) + split - 1) // split)
    items = []

    for start in range(0, len(lines), per):
        chunk = lines[start:start + per]
        # every chunk but the last keeps the newline that ends it, so the
        # chunks concatenate back into the file exactly
        body = "\n".join(chunk) + ("\n" if start + per < len(lines) else "")
        if not body:
            continue
        keys, defines, i, seen_decl = [], [], 0, False
        while i < len(body):
            # a block comment is one token and may cross a dozen lines
            if body.startswith("/-", i):
                j = body.find("-/", i)
                j = len(body) if j < 0 else j + 2
                kind = "docComment" if body.startswith("/--", i) else "blockComment"
                keys.append(f.node({"token": {"tok": f.token(kind, body[i:j])}}))
                i = j
                continue
            m = WORD.search(body, i)
            if not m:
                keys.append(f.text(body[i:]))
                break
            if m.start() > i:
                keys.append(f.text(body[i:m.start()]))
            w = m.group(0)
            defining = (not seen_decl) and w not in KEYWORDS and "def " in body[:m.start()]
            if defining:
                seen_decl = True
                defines.append(w)
            keys.append(f.node({"token": {"tok": f.token(_kind(w, defining), w)}}))
            i = m.end()

        items.append({
            "range": {"start": {"line": start + 1, "column": 1},
                      "end": {"line": start + len(chunk), "column": 1}},
            "kind": "Lean.Parser.Command.declaration",
            "defines": defines,
            "code": f.seq(keys),
        })

    return f.export(items)
