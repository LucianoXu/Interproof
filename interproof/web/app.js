/* =========================================================================
   Interproof viewer
   ========================================================================= */
(function () {
"use strict";

/* The page is handed exactly one object, and it says where everything else
   comes from.  A static build inlines the manifest and the PDFs; a served
   build names the URLs they can be fetched from, and a stream that says when
   they changed.  The whole difference between the two is spent in
   loadManifest and pdfBytes below; the reading code is written once. */
var BOOT = window.__IP__ || { mode: "static", manifest: {}, pdfs: {} };

var M = null;                        // the manifest, once it has been read
var TEX, BY, LEAN, LINKS, DOCS;
var DOC, DOCPOS;                     // id -> document, and its place in reading order
var DECL, FILE;                      // "File::name" -> decl, "File" -> file record
var BYNAME, FULL;                    // a written name, and a Lean one, -> decl key
var BY_DECL, BY_FILE;                // citations per declaration, and per module
var USES, USEDBY;                    // the reference structure among declarations
var HAS;                             // labels that exist, per document
var DOCSTAT, LOCATED;

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function why(e) { return (e && e.message) ? e.message : String(e); }

/* =========================================================================
   the manifest, and the indexes read off it
   ========================================================================= */

/* Every index here is derived from one manifest, and in a live session the
   manifest is replaced whole.  Building them in a function rather than at
   load time is what lets a rebuild be a re-read instead of a page reload —
   and an index left behind from the previous generation would be worse than
   no index at all, because it would answer. */
function ingest(m) {
  M = m;
  TEX = m.tex || {}; BY = m.by_item || {}; LEAN = m.lean || []; LINKS = m.links || [];

  /* The document set comes from the manifest; this file names no document.
     DOCS is in document order, which is also the order items sort in. */
  DOCS = m.docs || [];
  DOC = {}; DOCPOS = {};
  DOCS.forEach(function (d, i) { DOC[d.id] = d; DOCPOS[d.id] = i; });

  DECL = {}; FILE = {};
  LEAN.forEach(function (f) {
    FILE[f.name] = f;
    (f.decls || []).forEach(function (d) { DECL[f.name + "::" + d.name] = d; });
  });

  /* The two ways a name in the machine page becomes somewhere to go.

     `FULL` is the elaborated answer and is only there when the build ran Lean:
     the compiler resolved `Store.update` to a constant, and the manifest says
     which declaration of this build defines it.  `BYNAME` is the fallback and
     is what the source says — every declaration under the name it was written
     with, kept per module because a name that occurs in two modules is
     ambiguous everywhere except inside one of them. */
  FULL = m.lean_defs || {};
  BYNAME = {};
  LEAN.forEach(function (f) {
    (f.decls || []).forEach(function (d) {
      (BYNAME[d.name] = BYNAME[d.name] || []).push(f.name + "::" + d.name);
    });
  });

  /* the citations grouped by the lean declaration that makes them, and
     counted per module for the module rows */
  BY_DECL = {}; BY_FILE = {};
  LINKS.forEach(function (l) {
    var k = l.file + "::" + (l.decl || "⟨module⟩");
    (BY_DECL[k] = BY_DECL[k] || []).push(l);
    BY_FILE[l.file] = (BY_FILE[l.file] || 0) + 1;
  });

  /* the reference structure among Lean declarations.  `uses` — what a
     declaration names in its own code — is in the manifest; what uses it
     exists only as the sum of every other declaration's, so it is inverted
     here. */
  USES = {}; USEDBY = {};
  LEAN.forEach(function (f) {
    (f.decls || []).forEach(function (d) {
      var k = f.name + "::" + d.name;
      USES[k] = d.uses || [];
      USES[k].forEach(function (t) { (USEDBY[t] = USEDBY[t] || []).push(k); });
    });
  });

  /* labels that exist, per document — for xref resolution */
  HAS = {};
  Object.keys(TEX).forEach(function (k) { HAS[k] = true; });

  LOCATED = {};                      // placements are cached per document
  expand = {};                       // a new manifest, a new set of neighbours
  DOCSTAT = docStats();
}

/* A name as the source writes it, resolved to a declaration — the machine
   page's own `findLabel`.  Preferring the module being read is the whole of
   the rule: `update` means this module's `update` when this module has one,
   and a name held by two other modules is a genuine ambiguity that is dropped
   rather than guessed at.  Same rule the `uses` graph is built with, and the
   same caveat: this is a name match, not elaboration. */
function findDecl(name, inFile) {
  var c = BYNAME[name];
  if (!c || !c.length) return null;
  if (inFile) {
    for (var i = 0; i < c.length; i++) {
      if (c[i].indexOf(inFile + "::") === 0) return c[i];
    }
  }
  return c.length === 1 ? c[0] : null;
}

/* resolve a bare label against the documents, preferring one of them */
function findLabel(label, prefer) {
  if (prefer && HAS[prefer + "::" + label]) return prefer + "::" + label;
  for (var i = 0; i < DOCS.length; i++) {
    var k = DOCS[i].id + "::" + label;
    if (HAS[k]) return k;
  }
  return null;
}

/* ---- fetching ---------------------------------------------------------- */

var RAW = null;                      // the manifest text last ingested, live only

/* Resolves to the manifest — or to null when a rebuild left it byte for byte
   the same.  A generation is bumped by any successful build, including one
   that only touched a file nothing in the correspondence reads; re-rendering
   for that would cost the reader a flicker and tell them nothing. */
function loadManifest() {
  // carried, or named — the mode says which is expected, the payload decides
  if (BOOT.manifest) return Promise.resolve(BOOT.manifest);
  return fetch(BOOT.manifest_url, { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error("manifest — " + r.status + " " + r.statusText);
    return r.text();
  }).then(function (t) {
    if (t === RAW) return null;
    RAW = t;
    return JSON.parse(t);
  });
}

/* The compiled document, as bytes, whichever build this is.  Memoised because
   a selection re-opens the document it is already reading; the entry is what
   `forget` drops when a rebuild says the PDF itself moved. */
var BYTES = {};                      // id -> Promise<Uint8Array>

function pdfBytes(id) {
  if (BYTES[id]) return BYTES[id];
  var b64 = BOOT.pdfs && BOOT.pdfs[id];
  var p;
  if (b64) {
    p = new Promise(function (ok) {
      ok(Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); }));
    });
  } else if (BOOT.pdf_url) {
    // a static build can also be a folder rather than one file, and then the
    // documents sit beside the page instead of inside it
    p = fetch(BOOT.pdf_url + id + ".pdf", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(id + ".pdf — " + r.status + " " + r.statusText);
      return r.arrayBuffer();
    }).then(function (b) { return new Uint8Array(b); });
  } else {
    p = Promise.reject(new Error("this build says nothing about where " + id + ".pdf is"));
  }
  // a failure is not an answer worth keeping: in a live session the server may
  // simply have been mid-build, and the next selection should ask again
  p = p.catch(function (e) { delete BYTES[id]; throw e; });
  BYTES[id] = p;
  return p;
}

/* The one place the paper pane is fed.  Opening a document is slow enough to
   need saying so (a live server may still be inside latexmk) and can fail
   outright (the run may have produced no PDF at all).  It resolves to whether
   the document is on screen, because a caller that goes on to band an item
   would otherwise be banding the previous document. */
function openPDF(id, items) {
  var slow = setTimeout(function () { note("opening " + id + ".pdf…"); }, 400);
  return pdfBytes(id).then(function (bytes) {
    return PDFView.load(id, bytes, items);
  }).then(function () {
    clearTimeout(slow); note("");
    return true;
  }).catch(function (e) {
    clearTimeout(slow);
    note(id + ".pdf could not be opened — " + why(e), "err");
    return false;
  });
}

/* =========================================================================
   state
   ========================================================================= */

/* `sel` is the focused rail row, and `mode` is only which of the two indexes
   it belongs to — the key says that for itself, so nothing sets it directly. */
var state = { mode: "paper", sel: null, q: "", proof: false,
              all: false, marked: [], clean: false };

var $ = function (s) { return document.querySelector(s); };
var railBody, rhead, verso, vhead, rscroll, vscroll, noteEl, liveEl;

/* ---- what the viewer is doing ------------------------------------------ */

/* One strip, fixed to the frame rather than put inside a pane: the pane may
   itself be the thing that failed to load.  A failure stays until something
   replaces it — a viewer that swallowed the reason a document is missing
   would leave the reader looking at the previous one and believing it. */
var noteT = null;
function note(msg, cls) {
  if (!noteEl) return;
  clearTimeout(noteT);
  noteEl.className = "note" + (cls ? " " + cls : "");
  noteEl.textContent = msg || "";
  noteEl.style.display = msg ? "block" : "none";
  if (msg && cls !== "err") noteT = setTimeout(function () { note(""); }, 7000);
}

function itemsOrdered() {
  return Object.keys(TEX).map(function (k) { return [k, TEX[k]]; })
    .filter(function (e) { return e[1].kind !== "section" && e[1].kind !== "subsection"; })
    .sort(function (a, b) {
      if (a[1].doc !== b[1].doc) return DOCPOS[a[1].doc] - DOCPOS[b[1].doc];
      return a[1].order - b[1].order;
    });
}

var KINDSHORT = { theorem: "thm", lemma: "lem", definition: "def", proposition: "prop",
                  corollary: "cor", remark: "rem", example: "ex", fact: "fact",
                  conjecture: "conj", assumption: "assm", anchor: "part" };

/* what each document holds, for its row in the index: labelled statements, and
   how many of them the formalization cites */
function docStats() {
  var out = {};
  DOCS.forEach(function (d) { out[d.id] = { items: 0, linked: 0 }; });
  itemsOrdered().forEach(function (e) {
    var s = out[e[1].doc];
    if (!s) return;
    s.items++;
    if ((BY[e[0]] || []).length) s.linked++;
  });
  return out;
}

/* =========================================================================
   the index
   =========================================================================

   Two indexes, one tree.  They used to be tabs — one visible at a time, and
   the mode was something you set *before* you were allowed to look — and the
   grouping each of them already had was flattened into headings above runs of
   rows.  That grouping is a hierarchy: a statement sits in a section of a
   document, a declaration in a module in a directory.  So the two are roots
   of one tree that folds, the groups are its levels, and picking a row is
   what says which index you are reading in.  Fold the one you are not using
   away and it stays folded; the other still opens at whatever you last
   selected.

   Notes is the written side and Lean is the machine side, and between them
   they already carry both source trees — which is why there is no third index
   of the files as such.  For that to be true rather than nearly true, a row
   that stands for a *file* opens it: a document row opens the whole PDF, a
   module row the whole module, neither banded because nothing was selected
   inside them.  That is what keeps a module citing nothing, or a document
   nothing cites, from falling out of the reader altogether — they are listed
   where they belong, and they open. */

var fold = {}, qfold = {};           // node id -> collapsed, once the reader says so
var PARENT = {};                     // key -> the nodes above it, outermost first
var NODES = {};                      // node id -> node, as last rendered
var TMP = {};                        // rows that exist only while selected

/* A node is a place in the tree.  Some places are also things — a document, a
   module — and those carry a `key` and can be selected like a leaf; `hit` is
   whether the node's own name answers the filter, which is what lets a search
   for a file name find the file and not only what is inside it. */
function tnode(id, label, cls, key, hit) {
  return { id: id, label: label, cls: cls, key: key || "", hit: hit !== false,
           kids: [], ix: null, n: 0, has: false };
}

function tleaf(key, kd, nm, ct, has, sel, cls) {
  return { leaf: true, key: key, kd: kd, nm: nm, ct: ct, has: has, sel: sel, cls: cls || "" };
}

/* find or make the child node: the tree is built by walking the rows once, in
   the order the index puts them, and every row deepens it where it has to */
function child(parent, id, label, cls, key, hit) {
  var ix = parent.ix || (parent.ix = {});
  if (!ix[id]) { ix[id] = tnode(id, label, cls, key, hit); parent.kids.push(ix[id]); }
  return ix[id];
}

/* the directories of a source path, as nodes.  A formalization's directory is
   the first thing that says what a module is for, so the tree is the one on
   disk.  Inside a directory the manifest's order is kept, which is import
   order: alphabetical order is the file system's, and it says nothing about
   how the development is built up. */
function dirOf(parent, prefix, path) {
  var cut = path.lastIndexOf("/");
  if (cut < 0) return parent;
  var id = prefix, at = parent;
  path.slice(0, cut).split("/").forEach(function (seg) {
    id += "/" + seg;
    at = child(at, id, seg, "dir");
  });
  return at;
}

function baseOf(path) { return path.slice(path.lastIndexOf("/") + 1); }

/* ---- the two roots ----------------------------------------------------- */

/* document, section, subsection, statement — the divisions the paper itself
   is written in */
function paperRoot(q) {
  var root = tnode("paper", "Notes", "root");
  // the documents first and in reading order, so that one holding no labelled
  // statement at all is still a row: an empty document is a fact about the
  // project, and an index that hides it answers the wrong question
  DOCS.forEach(function (d) {
    var hay = (d.id + " " + d.title + " " + (d.main || "")).toLowerCase();
    // the document by its id, not its title: the title is a line long, it is
    // in the bar above the page it names, and the id is what every citation
    // to this document is written with
    child(root, "paper/" + d.id, d.id, "doc", "doc::" + d.id,
          !q || hay.indexOf(q) >= 0);
  });
  /* An anchor is a *part* of a statement, so it hangs under it rather than
     beside it: `def:aeval` holds `arith` and `bool`, and `arith` holds the
     three equations of its display.  The nesting is read off the path, which
     is what the path was for. */
  var parts = {};
  var rows = itemsOrdered();
  rows.forEach(function (e) {
    if (e[1].kind !== "anchor") return;
    var pk = e[1].doc + "::" + e[1].parent;
    (parts[pk] = parts[pk] || []).push(e);
  });

  function hay(it, key) {
    return (it.doc + " " + it.label + " " + it.title + " " + it.section + " " +
            it.subsection + " " +
            (BY[key] || []).map(function (l) { return l.file + " " + (l.decl || ""); })
              .join(" ")).toLowerCase();
  }
  function matches(key, it) {
    if (!q) return true;
    if (hay(it, key).indexOf(q) >= 0) return true;
    return (parts[key] || []).some(function (s) { return matches(s[0], s[1]); });
  }
  function itemRow(key, it) {
    var ct = (BY[key] || []).length;
    var badge = KINDSHORT[it.kind] || it.kind.slice(0, 4);
    var nm = it.title || it.label;
    var sub = (parts[key] || []).filter(function (s) {
      return !q || hay(s[1], s[0]).indexOf(q) >= 0 || hay(it, key).indexOf(q) >= 0;
    });
    // a statement's title is prose, not an identifier
    if (!sub.length)
      return tleaf(key, badge, nm, ct || "·", ct > 0, state.sel === key, "txt");
    var nd = tnode("i/" + key, nm, "itm txt", key, true);
    nd.kd = badge;
    nd.own = ct;
    sub.forEach(function (s) { nd.kids.push(itemRow(s[0], s[1])); });
    return nd;
  }

  rows.forEach(function (e) {
    var key = e[0], it = e[1];
    if (it.kind === "anchor") return;          // reached through its statement
    if (!matches(key, it)) return;
    var at = child(root, "paper/" + it.doc, it.doc, "doc", "doc::" + it.doc);
    if (it.section) at = child(at, at.id + "/" + it.section, it.section, "sec");
    if (it.subsection) at = child(at, at.id + "/" + it.subsection, it.subsection, "sec");
    at.kids.push(itemRow(key, it));
  });
  return root;
}

/* directory, module, declaration — every module, and under it the
   declarations that carry a citation.  A module citing nothing has nothing
   under it and is still a row: it is part of the development, and the gap is
   the thing this reader exists to show. */
function leanRoot(q) {
  var root = tnode("lean", "Lean", "root");
  LEAN.forEach(function (f) {
    var p = f.path || f.name + ".lean";
    var at = child(dirOf(root, "lean", p), "lean#" + f.name, baseOf(p), "file",
                   "mod::" + f.name, !q || p.toLowerCase().indexOf(q) >= 0);
    var rows = [];
    var mk = f.name + "::⟨module⟩";
    if (BY_DECL[mk]) rows.push(["⟨module⟩", BY_DECL[mk].length, mk]);
    f.decls.forEach(function (d) {
      var k = f.name + "::" + d.name;
      // a declaration reached by following a reference has no citations of
      // its own; it is still where the reader is, so the rail says so
      if (BY_DECL[k]) rows.push([d.name, BY_DECL[k].length, k]);
      else if (state.sel === k) rows.push([d.name, 0, k, 1]);
    });
    rows = rows.filter(function (r) {
      if (!q) return true;
      var cited = (BY_DECL[r[2]] || []).map(function (l) { return l.label; }).join(" ");
      return (f.name + " " + r[0] + " " + cited).toLowerCase().indexOf(q) >= 0;
    });
    rows.forEach(function (r) {
      if (r[3]) TMP[r[2]] = 1;
      at.kids.push(tleaf(r[2], r[0] === "⟨module⟩" ? "mod" : "decl", r[0],
                         r[1] || "·", r[1] > 0, state.sel === r[2]));
    });
  });
  return root;
}

/* ---- counting, and the way back ---------------------------------------- */

/* Leaf counts, and the path down to everything selectable: a selection that
   arrives from somewhere else — a chip in a header bar, a deep link, a
   rebuild — has to be able to unfold its own way back into view.

   Empty nodes are dropped here rather than guarded against at every push: a
   filter matching nothing in a directory should not leave the directory
   behind.  Whether to keep a node is not the same question as how much is
   under it — a file whose own name answered the filter is itself the match,
   and it stays with nothing under it — so `keep` is carried separately from
   the count, and a directory holding one such file stays for it. */
function tally(nd, above) {
  var here = above.concat([nd.id]), kids = [];
  nd.n = 0; nd.has = false;
  if (nd.key) PARENT[nd.key] = above;
  nd.kids.forEach(function (k) {
    if (!k.leaf) {
      tally(k, here);
      if (!k.keep) return;
    } else {
      PARENT[k.key] = here;
    }
    nd.n += k.leaf ? 1 : k.n;
    if (k.has) nd.has = true;
    kids.push(k);
  });
  nd.kids = kids;
  nd.keep = kids.length > 0 || !!(nd.key && nd.hit);
}

function railRoots(q) {
  var roots = [paperRoot(q), leanRoot(q)];
  roots.forEach(function (r) { tally(r, []); });
  return roots;
}

/* ---- folding ----------------------------------------------------------- */

/* A filter is a second opinion about what should be visible, and it should not
   spend the folding the reader did: while one is typed the tree answers to
   `qfold`, which is dropped when the filter is. */
function foldMap() { return state.q ? qfold : fold; }

function isOpen(nd) {
  var m = foldMap();
  if (nd.id in m) return !m[nd.id];
  if (state.q) return true;
  // the index you are reading in is the one that is open
  return nd.cls === "root" ? nd.id === state.mode : true;
}

function toggleFold(id) {
  var nd = NODES[id];
  if (!nd) return;
  var shut = isOpen(nd);
  foldMap()[id] = shut;
  setFold(id, !shut);
}

/* Fold or unfold in the DOM.  The rail is not rebuilt for it: the rows are
   already there, and the only thing that changes is whether their box is
   shown. */
function setFold(id, open) {
  var row = railBody.querySelector('[data-nd="' + id + '"]');
  var box = railBody.querySelector('[data-kids="' + id + '"]');
  if (row) row.classList.toggle("open", open);
  if (box) box.classList.toggle("hid", !open);
}

/* unfold everything above a key, so that what is selected can be seen */
function reveal(key) {
  (PARENT[key] || []).forEach(function (id) { foldMap()[id] = false; });
}

/* Move the selection without rebuilding.  Clicking the index used to redraw
   it, which replayed the staggered entrance of every row; what actually
   changes is one class, and — when the row is inside something folded — the
   boxes above it. */
function syncRail(key) {
  var row = railBody.querySelector('[data-key="' + key + '"]');
  // a key with no row of its own: the Lean index grows one for a declaration
  // that carries no citation only while it is selected, so that has to build
  if (!row) { buildRail(); return; }
  (PARENT[key] || []).forEach(function (id) {
    foldMap()[id] = false;
    setFold(id, true);
  });
  railBody.querySelectorAll(".row.sel").forEach(function (el) {
    el.classList.remove("sel");
  });
  row.classList.add("sel");
  railBody.querySelectorAll(".row.root").forEach(function (el) {
    el.classList.toggle("cur", el.dataset.nd === state.mode);
  });
  // the transient row of a previous selection is not part of the index
  railBody.querySelectorAll('[data-tmp="1"]').forEach(function (el) {
    if (el !== row) el.remove();
  });
  row.scrollIntoView({ block: "nearest" });
}

/* ---- rail -------------------------------------------------------------- */

function delay(ctr) { return "animation-delay:" + Math.min(ctr.n++ * 8, 260) + "ms"; }

/* A node that is only a place folds when you click it, and the whole row is
   the target.  A node that is also a file opens when you click it, and then
   folding is what the twisty is for — the two things a file row can do are
   worth one small target each rather than one ambiguous one. */
function nodeHTML(nd, depth, ctr) {
  NODES[nd.id] = nd;
  var open = isOpen(nd);
  var h = '<div class="row nd ' + nd.cls + (open ? " open" : "") + (nd.has ? " has" : "") +
    (nd.cls === "root" && nd.id === state.mode ? " cur" : "") +
    (nd.key && state.sel === nd.key ? " sel" : "") +
    (nd.kids.length ? "" : " bare") +
    '" data-nd="' + esc(nd.id) + '"' +
    (nd.key ? ' data-key="' + esc(nd.key) + '" data-open="' + esc(nd.id) + '"'
            : ' data-fold="' + esc(nd.id) + '"') +
    ' style="--d:' + depth + ";" + delay(ctr) + '">' +
    // a file with nothing under it draws no twisty and swallows no click: the
    // whole row is the file, because folding it would fold nothing
    '<span class="tw"' + (nd.key && nd.kids.length ? ' data-fold="' + esc(nd.id) + '"' : "") +
    "></span>" +
    (nd.kd ? '<span class="kd">' + esc(nd.kd) + "</span>" : "") +
    '<span class="nm">' + esc(nd.label) + "</span>" +
    '<span class="ct">' + (nd.own || nd.n) + "</span></div>";
  if (!nd.kids.length) return h;
  // Children live in a box of their own so that folding is a class on that
  // box.  Rendered flat, folding meant rebuilding the rail, and rebuilding it
  // replayed every row's entrance animation — the index appeared to reload
  // whenever it was touched.
  h += '<div class="kids' + (open ? "" : " hid") + '" data-kids="' + esc(nd.id) + '">';
  nd.kids.forEach(function (k) {
    h += k.leaf ? leafHTML(k, depth + 1, ctr) : nodeHTML(k, depth + 1, ctr);
  });
  return h + "</div>";
}

function leafHTML(k, depth, ctr) {
  return '<div class="row itm' + (k.cls ? " " + k.cls : "") + (k.has ? " has" : "") +
    (k.sel ? " sel" : "") + '" data-key="' + esc(k.key) + '"' +
    (TMP[k.key] ? ' data-tmp="1"' : "") +
    ' style="--d:' + depth + ";" + delay(ctr) + '">' +
    // the kind badge stands where a node's twisty stands: a leaf has nothing
    // to fold, and the rail is 268px wide
    '<span class="kd">' + esc(k.kd) + "</span>" +
    '<span class="nm">' + esc(k.nm) + "</span>" +
    '<span class="ct">' + esc(k.ct) + "</span></div>";
}

function buildRail(show) {
  if (!M) return;
  PARENT = {}; NODES = {}; TMP = {};
  var roots = railRoots(state.q.toLowerCase());
  if (show !== false) reveal(state.sel);
  var ctr = { n: 0 }, html = "";
  roots.forEach(function (r) {
    // an index a filter found nothing in is not worth a line of its own; one
    // that is simply empty in this build still is, or the reader would be
    // looking for an index that never appears
    if (state.q && !r.keep) return;
    html += nodeHTML(r, 0, ctr);
  });
  railBody.innerHTML = html || '<div class="norow">no match</div>';
  railBody.querySelectorAll("[data-fold]").forEach(function (el) {
    el.onclick = function (ev) { ev.stopPropagation(); toggleFold(el.dataset.fold); };
  });
  railBody.querySelectorAll("[data-key]").forEach(function (el) {
    el.onclick = function () {
      // opening a file shows what is in it: the row unfolds rather than
      // opening a page whose contents the reader is left to guess at
      if (el.dataset.open) foldMap()[el.dataset.open] = false;
      select(el.dataset.key);
    };
  });
}

/* ---- the paper page ---------------------------------------------------- */

/* every placed item of a document, so a followed PDF link can be named */
function located(doc) {
  if (!LOCATED[doc]) {
    LOCATED[doc] = Object.keys(TEX)
      .filter(function (k) { return TEX[k].doc === doc && TEX[k].rect; })
      .map(function (k) { return { key: k, rect: TEX[k].rect }; });
  }
  return LOCATED[doc];
}

/* ---- the formalized overlay -------------------------------------------- */

/* The reading modes answer "where is this one item".  This answers the
   question asked before that one: how much of the paper has been mechanized at
   all.  Every located item with a Lean counterpart is marked in the page at
   once, and a mark is clickable — so the paper itself becomes the index into
   the machine side, and the gaps are visible as gaps rather than as absences
   from a list.  The item being read is left to its own band. */
function allMarks(doc) {
  if (!state.all) return [];
  return located(doc).filter(function (e) {
    return (BY[e.key] || []).length && state.marked.indexOf(e.key) < 0;
  }).map(function (e) {
    var n = BY[e.key].length, it = TEX[e.key];
    return { key: e.key, rect: e.rect,
             title: it.kind + " " + it.label +
                    (it.title ? " — " + it.title : "") +
                    " · " + n + " citation" + (n === 1 ? "" : "s") };
  });
}

function toggleAll(on) {
  state.all = on === undefined ? !state.all : on;
  $("#allbtn").classList.toggle("on", state.all);
  PDFView.repaintMarks();
}

/* ---- clean ------------------------------------------------------------- */

/* Everything the viewer says *about* the two documents — the index, the two
   header bars, the reference rows — put away, leaving the documents and the
   marks on them.  Apparatus is what you need while deciding what to read and
   what is in the way once you are reading it.
   The rail stays in the DOM, so `j`/`k` still walk the selection with it
   hidden; the PDF is re-laid out because the pane it fits itself to just
   changed width. */
function toggleClean(on) {
  state.clean = on === undefined ? !state.clean : on;
  $("#app").classList.toggle("clean", state.clean);
  $("#cleanbtn").classList.toggle("on", state.clean);
  requestAnimationFrame(function () { PDFView.resize(); });
}

/* ---- reference rows ---------------------------------------------------- */

/* A reference has a direction, and the two directions answer different
   questions: what a statement rests on, and what rests on it.  They are shown
   as separate rows rather than one undifferentiated list of neighbours. */

var CHIPCAP = 12;
var expand = {};                     // row -> the reader asked for all of it

/* one labelled row.  `items` are {key, text, cls} and `more` names what is
   being held back, so a shortened row says so instead of just ending. */
function chipRow(label, items, attr, row, more) {
  if (!items.length && !more) return "";
  var h = '<div class="chips"><i>' + esc(label) + "</i>";
  items.forEach(function (c) {
    h += '<span class="chip' + (c.cls ? " " + c.cls : "") + '"' +
         (c.key ? " " + attr + '="' + esc(c.key) + '"' : "") + ">" + esc(c.text) + "</span>";
  });
  if (more) h += '<span class="chip more" data-more="' + row + '">' + esc(more) + "</span>";
  return h + "</div>";
}

/* a plain row, cut at a length the head can carry */
function capped(items, row) {
  return (expand[row] || items.length <= CHIPCAP)
    ? { items: items, more: "" }
    : { items: items.slice(0, CHIPCAP), more: "+" + (items.length - CHIPCAP) };
}

var ZOOMTOOLS = '<button class="rbtn" data-zoom="0.9">&minus;</button>' +
                '<button class="rbtn" data-zoom="1.1">+</button>' +
                '<button class="rbtn" data-zoom="fit">fit</button>';

function wireZoom(root) {
  root.querySelectorAll("[data-zoom]").forEach(function (b) {
    b.onclick = function () {
      var z = b.dataset.zoom;
      if (z === "fit") PDFView.refit(); else PDFView.zoom(+z);
    };
  });
}

/* the bar above the PDF: where you are, what it cites, how to read it */
function paperHead(keys, focus) {
  var it = TEX[keys[focus]];
  if (!it) return "";
  var h = '<div class="crumb"><span>' + esc(it.doc + " · " + DOC[it.doc].title) +
          "</span>";
  if (it.section) h += "<i>/</i><span>" + esc(it.section) + "</span>";
  if (it.subsection) h += "<i>/</i><span>" + esc(it.subsection) + "</span>";
  h += '<span class="rtools">';
  if (it.proof_rect) {
    h += '<button class="rbtn' + (state.proof ? " on" : "") + '" id="proofbtn">' +
         "with proof</button>";
  }
  h += ZOOMTOOLS + "</span></div>";

  h += '<div class="rid"><span class="lbl">' + esc(it.kind) + " — " + esc(it.label) +
       '</span><span class="src">' + esc(it.doc + "/" + it.file) + ":" + it.line +
       "</span></div>";

  /* when several items are marked at once, the siblings — so every mark in the
     scroll is reachable by name — and then the item's own references, each
     direction on its own row */
  var marked = [];
  keys.forEach(function (k, i) {
    if (i === focus || !TEX[k]) return;
    marked.push({ key: k, text: TEX[k].label, cls: "on" });
  });
  var cites = [];
  (it.refs || []).forEach(function (l) {
    var k = findLabel(l, it.doc);
    if (!k || keys.indexOf(k) >= 0) return;
    // a section is a real reference but not a place the viewer can go: only
    // labelled statements are placed in the PDF.  Named, not offered.
    cites.push(TEX[k].rect ? { key: k, text: l } : { key: "", text: l, cls: "dead" });
  });
  var by = [];
  (it.cited_by || []).forEach(function (k) {
    if (TEX[k] && keys.indexOf(k) < 0) by.push({ key: k, text: TEX[k].label });
  });

  var rows = [["marked", marked, "pmarked"], ["cites", cites, "pcites"],
              ["cited by", by, "pcitedby"]];
  rows.forEach(function (r) {
    var c = capped(r[1], r[2]);
    h += chipRow(r[0], c.items, "data-go", r[2], c.more);
  });
  return h;
}

function paperHeadShow(keys, focus) {
  rhead.innerHTML = paperHead(keys, focus);
  wire(rhead);
  wireZoom(rhead);
  var pb = rhead.querySelector("#proofbtn");
  if (pb) pb.onclick = function () { state.proof = !state.proof; paperShow(keys, focus); };
  // opening a cut row re-renders the bar only: the page must not jump because
  // the reader asked to see more names
  rhead.querySelectorAll("[data-more]").forEach(function (el) {
    el.onclick = function () { expand[el.dataset.more] = true; paperHeadShow(keys, focus); };
  });
}

/* put the marks in the scroll and bring the focused one into view.  It
   resolves when the page is on screen, so a caller that has a scroll position
   to put back knows when there is something to put it back into. */
function paperShow(keys, focus) {
  var it = TEX[keys[focus]];
  if (!it) return Promise.resolve();
  state.marked = keys;               // these carry their own band; no overlay
  paperHeadShow(keys, focus);

  /* only the focused document can be shown at once */
  var same = keys.filter(function (k) { return TEX[k] && TEX[k].doc === it.doc; });
  /* An anchor measured by the marked build covers its real regions, which for
     a wrapped span is more than one; drawing only the bounding box would put
     the highlight over two neighbours it does not name.  The tint travels with
     each region, so three parts of one line read as three. */
  var rects = [], idx = 0;
  same.forEach(function (k) {
    var t = TEX[k];
    if (k === keys[focus]) idx = rects.length;
    var use = (state.proof && t.proof_rect) ? [t.proof_rect]
              : (t.rects && t.rects.length ? t.rects : [t.rect]);
    use.forEach(function (r) {
      // the level travels with the region: a part is coloured as a part
      if (r) rects.push(t.kind === "anchor" ? Object.assign({ part: 1 }, r) : r);
    });
  });

  return openPDF(it.doc, located(it.doc)).then(function (ok) {
    if (!ok) return;
    PDFView.show(rects.filter(Boolean), idx);
    PDFView.repaintMarks();
  });
}

/* ---- the machine page -------------------------------------------------- */

/* Where a citation lives: the declaration it belongs to, docstring included,
   or — when it is module prose, which no declaration owns — the comment block
   that does the citing, one band per block.

   Never the hull of several.  `lem:one-sided` is named in StepLemmas' header
   and again at a section break six hundred lines down; those are two places,
   and the file between them cites nothing. */
function leanRanges(leanKey, links) {
  var d = DECL[leanKey];
  if (d) return [{ from: d.doc_line || d.line, to: d.end_line }];
  var seen = {}, out = [];
  (links || []).forEach(function (l) {
    var r = { from: l.block_from || l.line, to: l.block_to || l.line };
    var id = r.from + ":" + r.to;
    if (seen[id]) return;
    seen[id] = 1;
    out.push(r);
  });
  return out.sort(function (a, b) { return a.from - b.from; });
}

/* the bar above the file: what cites this, and where else it is cited */
function leanHead(keys, focus, groups, total) {
  var parts = keys[focus].split("::"), fname = parts[0], dname = parts[1];
  var d = DECL[keys[focus]];
  var files = {}; keys.forEach(function (k) { files[k.split("::")[0]] = 1; });
  var nf = Object.keys(files).length;

  var h = "<b>" + total + "</b> citation" + (total > 1 ? "s" : "") +
          " · <b>" + keys.length + "</b> declaration" + (keys.length > 1 ? "s" : "") +
          " · " + nf + " file" + (nf > 1 ? "s" : "");
  h += '<span class="vid"><span class="k">' + (d ? d.kind : "module") + "</span>" +
       '<span class="n">' + esc(dname) + "</span>";
  if (d && d.has_sorry) h += '<span class="srrtag">sorry</span>';
  if (d && d.section) h += '<span class="k">' + esc(d.section) + "</span>";
  var at = d ? d.line : (leanRanges(keys[focus], groups[keys[focus]])[0] || {}).from;
  h += '<span class="loc">' + esc(fname) + ".lean:" + (at || "?") + "</span></span>";

  /* a declaration name as a chip, qualified when it lives in another module */
  function declChip(k) {
    var p = k.split("::");
    return { key: k, text: (p[0] === fname ? "" : p[0] + ".") + p[1] };
  }

  /* A proof rests on a hundred names, nearly all of them plumbing: `CqState`
     alone is used by 152 declarations.  What this reader is following is the
     correspondence, so a row shows the neighbours that carry a citation of
     their own — the formalized statements this one rests on, and those that
     rest on it.  The rest are counted and one click away, never dropped. */
  function refRow(label, list, row) {
    var linked = [], rest = [];
    list.forEach(function (k) { (BY_DECL[k] ? linked : rest).push(k); });
    if (expand[row]) {
      return chipRow(label, linked.map(declChip).concat(rest.map(function (k) {
        var c = declChip(k); c.cls = "dim"; return c;
      })), "data-use", row, "");
    }
    return chipRow(label, linked.map(declChip), "data-use", row,
                   rest.length ? "+" + rest.length + " uncited" : "");
  }

  var also = [];
  keys.forEach(function (k, i) { if (i !== focus) also.push(declChip(k)); });
  var c = capped(also, "lalso");
  h += chipRow("also", c.items, "data-decl", "lalso", c.more);
  // the same two directions as the paper side, in the machine's own terms
  h += refRow("uses", USES[keys[focus]] || [], "luses");
  h += refRow("used by", USEDBY[keys[focus]] || [], "lusedby");
  return h;
}

function leanHeadShow(keys, focus, groups, total) {
  vhead.innerHTML = leanHead(keys, focus, groups, total);
  vhead.querySelectorAll("[data-decl]").forEach(function (el) {
    el.onclick = function () { leanShow(keys, keys.indexOf(el.dataset.decl), groups, total); };
  });
  vhead.querySelectorAll("[data-use]").forEach(function (el) {
    el.onclick = function () { select(el.dataset.use); };
  });
  vhead.querySelectorAll("[data-more]").forEach(function (el) {
    el.onclick = function () {
      expand[el.dataset.more] = true;
      leanHeadShow(keys, focus, groups, total);
    };
  });
}

/* show one module, banding every cited declaration it holds */
function leanShow(keys, focus, groups, total) {
  var fname = keys[focus].split("::")[0];
  leanHeadShow(keys, focus, groups, total);

  var same = keys.filter(function (k) { return k.split("::")[0] === fname; });
  LeanView.load(fname, FILE[fname].text, FILE[fname].sem, M.lean_strs);
  /* one key can hold several bands, so which of them is the focused one is
     carried on the band rather than being an index into a parallel list */
  var bands = [];
  same.forEach(function (k) {
    leanRanges(k, groups[k]).forEach(function (r) {
      r.on = k === keys[focus];
      bands.push(r);
    });
  });
  LeanView.show(bands);
  wire(verso);
}

function selectPaper(key) {
  var it = TEX[key];
  if (!it) return Promise.resolve();
  var opened = paperShow([key], 0);

  var links = BY[key] || [];
  var groups = {};
  links.forEach(function (l) {
    var k = l.file + "::" + (l.decl || "⟨module⟩");
    (groups[k] = groups[k] || []).push(l);
  });
  var keys = Object.keys(groups).sort();

  if (!keys.length) {
    vhead.innerHTML = "no Lean counterpart";
    verso.innerHTML = '<div class="pad"><div class="empty">' +
      "<b>" + esc(it.label) + "</b> is not cited anywhere in the Lean sources.<br><br>" +
      "Either it is out of the mechanization scope, or the citation is missing.<br>" +
      "Both are findings: this pane is the gap report." +
      "</div></div>";
    LeanView.forget();
    return opened;
  }
  leanShow(keys, 0, groups, links.length);
  return opened;
}

function selectLean(key) {
  if (!BY_DECL[key] && !DECL[key]) return Promise.resolve();
  var links = BY_DECL[key] || [];
  var groups = {}; groups[key] = links;
  leanShow([key], 0, groups, links.length);

  /* every paper item this declaration cites is marked at once; the first
     decides which document the scroll shows */
  var cited = [];
  links.forEach(function (l) {
    if (cited.indexOf(l.key) < 0 && TEX[l.key] && TEX[l.key].rect) cited.push(l.key);
  });
  if (!cited.length) {
    rhead.innerHTML = '<div class="crumb"><span>no paper counterpart</span></div>';
    state.marked = [];
    PDFView.clear();
    PDFView.repaintMarks();
    return Promise.resolve();
  }
  return paperShow(cited, 0);
}

/* ---- a whole file ------------------------------------------------------ */

/* The rest of this file answers "where is this one statement, or this one
   declaration".  A file row asks something simpler: show me this, all of it.
   One page moves and the other is left alone — nothing was selected *inside*
   the file, so there is nothing for the other page to answer with, and the
   pair on screen becomes whatever the reader put there.  That pairing is the
   one thing the correspondence cannot arrange for them. */

function docFileHead(id) {
  var d = DOC[id], s = DOCSTAT[id];
  var h = '<div class="crumb"><span>' + esc(id + " · " + d.title) + "</span>" +
          '<span class="rtools">' + ZOOMTOOLS + "</span></div>";
  h += '<div class="rid"><span class="lbl">document</span><span class="src">' +
       '<span id="pdfpn"></span>' + esc(d.main || "") + " · " + s.items +
       " statements, " + s.linked + " with a Lean counterpart</span></div>";
  return h;
}

function moduleFileHead(name) {
  var f = FILE[name];
  var nd = f.decls.length, nc = BY_FILE[name] || 0;
  var srr = f.decls.filter(function (d) { return d.has_sorry; }).length;
  var h = "<b>" + f.lines.toLocaleString() + "</b> lines · <b>" + nd + "</b> declaration" +
          (nd === 1 ? "" : "s") + " · <b>" + nc + "</b> citation" + (nc === 1 ? "" : "s");
  h += '<span class="vid"><span class="k">module</span><span class="n">' + esc(name) + "</span>";
  if (srr) h += '<span class="srrtag">' + srr + " sorry</span>";
  h += '<span class="loc">lean/' + esc(f.path || name + ".lean") + "</span></span>";

  /* what the module is built on: the edges the index is ordered by, walkable */
  var imp = (f.imports || []).filter(function (m) { return FILE[m]; });
  if (imp.length) {
    h += '<div class="chips"><i>imports</i>' + imp.map(function (m) {
      return '<span class="chip" data-mod="' + esc(m) + '">' + esc(m) + "</span>";
    }).join("") + "</div>";
  }
  return h;
}

/* what the left page was last asked for — not the same as what it is showing,
   which is only true once the PDF has been parsed, and not the same as the
   selection either, since a document can be opened beside a selection made on
   the other side */
var ASKED = null;

function showDocument(id) {
  if (!DOC[id]) return Promise.resolve();
  var moved = PDFView.doc() !== id;
  state.marked = [];
  ASKED = id;
  rhead.innerHTML = docFileHead(id);
  wireZoom(rhead);
  return openPDF(id, located(id)).then(function (ok) {
    if (!ok || ASKED !== id) return;
    PDFView.clear();                       // a file is open, no item is selected
    PDFView.repaintMarks();
    if (moved) PDFView.top();
    var pn = rhead.querySelector("#pdfpn");
    if (pn) pn.textContent = PDFView.pages() + " pages · ";
  });
}

function showModule(name) {
  if (!FILE[name]) return;
  var moved = LeanView.file() !== name;
  vhead.innerHTML = moduleFileHead(name);
  vhead.querySelectorAll("[data-mod]").forEach(function (el) {
    el.onclick = function () { select("mod::" + el.dataset.mod); };
  });
  LeanView.load(name, FILE[name].text, FILE[name].sem, M.lean_strs);
  LeanView.clear();
  if (moved) LeanView.top();
  wire(verso);
}

/* ---- selecting --------------------------------------------------------- */

/* The key says which index it belongs to, so nothing has to be put into a mode
   before it can be selected: a chip in a header bar, a deep link and a row of
   the tree all arrive here, and the mode follows what was picked. */
function select(key) {
  if (!M) return Promise.resolve();
  var m = modeOf(key);
  if (m) state.mode = m;
  state.sel = key;
  expand = {};                       // a new selection, a new set of neighbours
  var opened;
  if (key.indexOf("doc::") === 0) opened = showDocument(key.slice(5));
  else if (key.indexOf("mod::") === 0) showModule(key.slice(5));
  else opened = state.mode === "paper" ? selectPaper(key) : selectLean(key);
  wire(verso);
  syncRail(key);
  location.hash = encodeURIComponent(key);
  return opened || Promise.resolve();
}

function wire(root) {
  root.querySelectorAll("[data-go]").forEach(function (el) {
    el.onclick = function (ev) {
      ev.stopPropagation();
      if (TEX[el.dataset.go]) select(el.dataset.go);
    };
  });
  root.querySelectorAll(".fold").forEach(function (b) {
    b.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      var hid = b.previousElementSibling;
      hid.style.display = hid.style.display === "none" ? "block" : "none";
      b.textContent = hid.style.display === "none"
        ? "show " + hid.textContent.split("\n").length + " more lines" : "collapse";
    };
  });
}

/* ---- modes ------------------------------------------------------------- */

/* which index a key belongs to.  A statement is keyed by its document and
   label, a declaration by its module and name, and a whole file says so in
   front — so the key spaces are disjoint and a deep link picks its own index.
   The `doc::`/`mod::` forms are checked against the manifest rather than
   trusted, since a document could be called `doc` and own a label. */
function modeOf(k) {
  if (!k) return null;
  if (k.indexOf("doc::") === 0 && DOC[k.slice(5)]) return "paper";
  if (k.indexOf("mod::") === 0 && FILE[k.slice(5)]) return "lean";
  if (TEX[k]) return "paper";
  if (BY_DECL[k] || DECL[k]) return "lean";
  return null;
}

/* ---- the first entry of a mode ----------------------------------------- */

/* Asked when the key that was being read is not in the manifest any more.
   The index already answers this — it is everything reachable in the current
   mode, in the order the mode puts it — so it is asked rather than a second
   ordering being written here.  The tree it is asked of is the unfiltered
   one: what is folded away, or filtered out, is still in the build.

   A leaf is preferred to a file row: a statement or a declaration drives both
   pages, and a build should not open onto one page and an empty other. */
function firstKey() {
  var root = null;
  railRoots("").forEach(function (r) { if (r.id === state.mode) root = r; });
  var found = null, file = null;
  (function walk(nd) {
    if (nd.key && !file) file = nd.key;
    nd.kids.forEach(function (k) {
      if (found) return;
      if (k.leaf) found = k.key; else walk(k);
    });
  })(root || { kids: [] });
  return found || file;
}

/* =========================================================================
   live
   ========================================================================= */

/* A served session is a moving target: the author edits, the server rebuilds,
   and the page follows.  What the stream carries is only a generation number;
   the manifest is re-fetched, because the difference that matters is between
   two whole manifests and the server should not have to describe it. */

var GEN = null, STAMP = "", ES = null, BAD = false, BUSY = false;

/* a LaTeX error runs for a page and says what it has to say in the first
   lines; the terminal that ran the build has the rest */
function cut(s, n) { s = String(s); return s.length > n ? s.slice(0, n) + "…" : s; }

/* The lamp answers two questions, and they are not the same question.

   *Is this page following the sources?* — connecting, live, rebuilding,
   elaborating, offline.  Only a served session has this one, and it is the
   text.

   *Is the project in good order?* — every citation resolving, or dangling
   ones, or a build that failed outright.  That is true of a published folder
   as much as of a live session, and it is the colour of the dot.

   Squeezing both into one channel was the old shape and it lost: a live
   session with three dangling citations was as green as one with none, and
   "everything is fine" is exactly what a reader must not be told when a
   statement has been renamed on one side and not the other. */
function health() {
  if (BAD) {
    return { cls: "bad",
             why: "the last build failed — this page is the one before it" };
  }
  if (!M) return { cls: "idle", why: "" };

  var s = M.stats || {}, sem = s.sem || {}, warn = [];
  if (s.unresolved) {
    warn.push(s.unresolved + " dangling citation" +
              (s.unresolved === 1 ? "" : "s") + ": something is named that no " +
              "document holds, so one side was renamed and the other was not");
  }
  if (s.tex_items && !s.located) {
    warn.push("no statement could be placed on a page — the documents were " +
              "not compiled, or -synctex=1 was dropped");
  }
  if (sem.on && sem.failed) {
    warn.push("elaboration was asked for and did not run: " + sem.failed);
  }
  if (warn.length) return { cls: "warn", why: warn.join(" · ") };
  return { cls: "ok", why: "every citation resolves" };
}

function liveMark(cls, text) {
  if (!liveEl) return;
  var h = health();
  liveEl.className = "live " + cls;
  liveEl.innerHTML = '<i class="' + h.cls + '"></i>' +
                     esc(text + (STAMP ? " · " + STAMP : ""));
  // the colour is not self-explanatory, and this page has one way of saying
  // what a thing means
  if (h.why) liveEl.setAttribute("data-tip", h.why);
  else liveEl.removeAttribute("data-tip");
}

/* A published folder has no connection to report, so its lamp reports the one
   thing it does have: whether the correspondence in it holds.  It says so even
   when the answer is yes — a lamp that appears only on bad news is a lamp a
   reader cannot trust the absence of, and cannot learn to read before the day
   it matters. */
var STATIC_WORD = { bad: "failed", warn: "warning", ok: "ok", idle: "…" };

function markHealth() {
  if (BOOT.mode === "live" || !liveEl) return;
  var h = health();
  liveEl.style.display = "flex";
  liveMark(h.cls, STATIC_WORD[h.cls] || "ok");
}

function stamped() {
  var d = new Date();
  STAMP = ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
  /* Not necessarily "live".  The elaborated pass runs behind this one and its
     "started" event arrives while this manifest is still being fetched, so a
     re-render that unconditionally said `live` would announce that the page
     was up to date while Lean was still several seconds from saying what the
     types are.  The flag outlives the fetch; the generation that carries the
     elaborated manifest is what clears it. */
  liveMark(BUSY ? "wait" : "on", BUSY ? "elaborating" : "live");
}

/* everything that says where the reader is, and would otherwise be spent by a
   re-render: the mode and its selection, the filter, the two toggles, both
   scroll positions, and the zoom */
function snapshot() {
  return { mode: state.mode, sel: state.sel, q: state.q, all: state.all,
           clean: state.clean, proof: state.proof,
           pdf: rscroll ? rscroll.scrollTop : 0, lean: vscroll ? vscroll.scrollTop : 0,
           scale: PDFView.scale(), fit: PDFView.fitting() };
}

/* A rebuild is not a navigation.  The one thing that can be gone is the key
   itself — the author deleted the theorem, or renamed the module — and that
   is said out loud and stepped back from, never thrown. */
function restore(s) {
  state.q = s.q; state.proof = s.proof;
  state.mode = s.mode;
  if (state.all !== s.all) toggleAll(s.all);
  if (state.clean !== s.clean) toggleClean(s.clean);

  var key = s.sel, lost = "";
  if (modeOf(key) !== state.mode) {
    state.sel = null;
    var fallback = firstKey();
    if (!fallback) {
      note("this build holds nothing to read in " + state.mode + " mode", "err");
      return Promise.resolve();
    }
    lost = (key ? key + " is gone from the rebuilt manifest" : "nothing was selected") +
           " — showing " + fallback + " instead";
    key = fallback;
  }

  var opened = select(key);
  return Promise.resolve(opened).then(function () {
    /* after the layout the new manifest asked for, not before it: the pages
       are what the scroll offsets are measured against.  Selecting scrolled
       to the band the reader was already looking at, which is close but not
       where they left the page. */
    requestAnimationFrame(function () {
      if (!s.fit) PDFView.setScale(s.scale);
      if (rscroll) rscroll.scrollTop = s.pdf;
      if (vscroll) vscroll.scrollTop = s.lean;
      // nothing is cleared here: if opening the rebuilt document failed, that
      // note is the last true thing said about this pane
      if (lost) note(lost, "warn");
      stamped();
    });
  });
}

function refresh() {
  liveMark("wait", "rebuilding");
  return loadManifest().then(function (m) {
    if (!m) { stamped(); return; }   // the rebuild moved nothing this page reads
    var was = snapshot(), revs = {};
    DOCS.forEach(function (d) { revs[d.id] = d.rev; });
    ingest(m);
    markHealth();
    /* Only a document whose bytes moved is dropped.  A Lean edit rebuilds the
       manifest without touching a PDF, and re-parsing it would blank the page
       the reader is looking at to arrive at the same page. */
    Object.keys(revs).forEach(function (id) {
      if (DOC[id] && DOC[id].rev === revs[id]) return;
      delete BYTES[id];
      PDFView.forget(id);
    });
    renderStats();
    return restore(was);
  }).catch(function (e) {
    note("the rebuild could not be read — " + why(e), "err");
    liveMark("off", "stale");
  });
}

function connect() {
  liveMark("wait", "connecting");
  ES = new EventSource(BOOT.events_url);
  ES.onopen = function () { liveMark("on", "live"); };
  // EventSource reconnects on its own; saying the connection is gone is the
  // whole job here, because a page that stopped following looks identical to
  // one that is up to date
  ES.onerror = function () { liveMark("off", "offline"); };
  ES.onmessage = function (ev) {
    var d = null;
    try { d = JSON.parse(ev.data); } catch (err) { return; }
    if (!d) return;
    /* A failed build is published with the generation unchanged: the server
       goes on serving the last one that worked, and this event is the only
       way the page can learn that what it shows is no longer what is on disk.
       Saying so is the whole point — the alternative is a reader wondering
       why their edit did not arrive. */
    if (d.ok === false) {
      BAD = true;
      liveMark("bad", "build failed");
      note(cut(d.error || "the build failed", 400), "err");
      return;
    }
    if (BAD) { BAD = false; note(""); }
    /* Lean has started on the pass behind this one.  Not a new generation —
       nothing to re-fetch — but the reader is owed the difference between
       "your edit landed" and "the types on it are still being computed". */
    if (d.busy === "elaborate") { BUSY = true; liveMark("wait", "elaborating"); return; }
    if (typeof d.gen !== "number") return;
    if (d.gen === GEN) { liveMark("on", "live"); return; }
    GEN = d.gen;
    BUSY = false;              // a new generation is a pass that finished
    refresh();
  };
}

/* =========================================================================
   the archive
   ========================================================================= */

/* download.js is loaded before this file and holds no data of its own: it
   reads the manifest and the PDFs through here, so exactly one place knows
   how this build was made. */
var bridge = {
  boot: BOOT,
  manifest: function () { return M; },
  pdfBytes: pdfBytes,
};
window.Interproof = bridge;

function wireDownload() {
  var btn = $("#dlbtn");
  if (!btn || !window.Download) return;
  /* The button reports into its own label rather than replacing its contents:
     it is an icon now, and an icon that turns into the word "Packing" and
     back is a button that vanished while you were watching it. */
  var lbl = btn.querySelector(".lbl"), label = lbl ? lbl.textContent : "";
  function say(t) { if (lbl) lbl.textContent = t; }
  function done() { btn.disabled = false; btn.classList.remove("busy"); say(label); }
  btn.onclick = function () {
    if (btn.disabled || !M) return;
    btn.disabled = true;
    btn.classList.add("busy");
    say("Packing");
    Download.build(bridge, function (n, total) {
      say("Packing " + Math.round(n / total * 100) + "%");
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = Download.filename(bridge);
      document.body.appendChild(a);
      a.click();
      a.remove();
      // revoking in the same turn cancels the download in some browsers: the
      // click starts a read of the object, it does not finish one
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      done();
    }).catch(function (e) {
      note("the archive could not be built — " + why(e), "err");
      done();
    });
  };
}

/* ---- boot -------------------------------------------------------------- */

function renderStats() {
  var s = M.stats || {};
  $("#stats").innerHTML =
    '<div class="stat acc"><b>' + (s.links || 0) + "</b>links</div>" +
    '<div class="stat"><b>' + (s.unresolved || 0) + "</b>dangling</div>";
}

/* A file row moves one page and leaves the other alone, which is what reading
   wants — but a page arrived at by deep link would then open with one half
   blank, and a blank half says nothing at all.  So the first thing shown is
   made to be two things. */
function fillPanes() {
  var opened = Promise.resolve();
  if (!PDFView.doc() && DOCS[0]) opened = showDocument(DOCS[0].id);
  if (!LeanView.file() && LEAN[0]) showModule(LEAN[0].name);
  return opened;
}

/* the hash decides the mode, and the mode decides what opens when it does not */
function start(key) {
  state.mode = modeOf(key) || "paper";
  if (!modeOf(key)) key = firstKey();
  if (!key) {
    note("this build holds no items to read", "err");
    return Promise.resolve();
  }
  return Promise.resolve(select(key)).then(fillPanes);
}

/* ---- help -------------------------------------------------------------- */

/* A reader arriving at a published artifact has the page and nothing else: no
   README, no repository, often no idea that the two panes are linked by
   citations somebody wrote in the Lean sources.  So the page explains itself,
   and it does it with *this* project's own numbers and its own citations —
   a generic help text would leave the one question a newcomer actually has,
   "what am I looking at here", answered somewhere they cannot reach. */

function sample() {
  for (var i = 0; i < LINKS.length; i++) {
    if (LINKS[i].context) return LINKS[i];
  }
  return null;
}

function helpCitation(l) {
  if (!l) return "";
  var c = l.context.length > 150 ? l.context.slice(0, 150) + "…" : l.context;
  return '<div class="hsample"><code>' + esc(c) + "</code><i>" +
         esc(l.file) + ".lean:" + l.line + " &rarr; " + esc(l.key) + "</i></div>";
}

/* Which of the two things a hover is claiming.  The difference is not a
   detail: one is the type Lean computed, the other is the text somebody typed,
   and a reader deciding whether to trust a signature has to be told which they
   are looking at.  So the page says it about *this* build rather than in a
   manual somewhere. */
function helpCode() {
  var s = (M.stats && M.stats.sem) || {};
  if (s.on && !s.failed) {
    var h = "<p>This build was <b>elaborated</b>: " + (s.modules || 0) + " of " +
      (s.of || 0) + " modules went through Lean, so the colouring is Lean's " +
      "own grammar, a hover is the <i>elaborated</i> type or signature, and a " +
      "jump follows what the compiler resolved.</p>";
    if (s.states) {
      h += "<p>It also carries <b>" + s.states + " proof states</b> — the one " +
        "thing on this page that is in neither source. The <b>line numbers " +
        "in amber</b> are the lines that have one; hover a tactic and you see " +
        "the state it <i>left</i>. Hover a case arrow for that branch's " +
        "obligation, and the step that closes it reports no goals left. What " +
        "a step was applied <i>to</i> is the state after the line above it.</p>";
    }
    return h;
  }
  return "<p>This build read the formal sources as <b>text</b>. The machine " +
    "page still links names to the declarations that carry them, and a hover " +
    "shows a declaration <i>as it is written</i> — but that is a name match, " +
    "not elaboration: it cannot see through <code>open</code>, and a local " +
    "binder sharing a declaration's name reads as the declaration. Building " +
    "with <code>--elaborate</code> replaces all of it with what Lean knows.</p>";
}

function helpHTML() {
  var s = M.stats, docs = DOCS.map(function (d) { return d.title; }).join(" · ");
  var h = '<button class="hclose" id="helpclose">close &nbsp;esc</button>';
  h += "<h2>" + esc((M.project && M.project.title) || "Interproof") + "</h2>";
  h += "<p>The left page is the <b>compiled PDF</b> of " + esc(docs) +
       " — the typeset document itself, not a re-rendering of its source. " +
       "The right page is the formalization, as the file on disk. " +
       "They are linked by the citations already written in the formal " +
       "sources: a comment that names a statement of the paper is what puts " +
       "the two on screen together.</p>";

  h += "<h3>what you can click</h3><ul>" +
       "<li>A row of the index on the left — a statement, a declaration, or a " +
       "<b>document or module row</b>, which opens that file whole.</li>" +
       "<li>The <b>triangle</b> on a document or module row folds it instead " +
       "of opening it.</li>" +
       "<li>Every <b>name in a box</b> in the two bars above the pages: they " +
       "are the references, and each one goes there.</li>" +
       "<li>A <b>citation inside the Lean source</b> — the underlined labels " +
       "in the comments — and a <b>\\Cref link inside the PDF</b>.</li>" +
       "<li>Every <b>green mark</b> in the paper while <b>Formalized</b> is " +
       "on, which is that statement's way into the formalization.</li>" +
       "<li>Any <b>name in the Lean source</b> that lights up under the " +
       "pointer: hovering says what it is, clicking goes to where it is " +
       "defined, and every other occurrence of it is marked while you are " +
       "on it.</li>" +
       "<li>Any <b>tactic on an amber-numbered line</b>, which shows the " +
       "proof state that tactic left.</li>" +
       "</ul>" + helpCode();

  h += "<h3>keys</h3><table class='hkeys'>" +
       row("a", "<b>Formalized</b>: mark every statement with a counterpart, at once") +
       row("c", "<b>Clean</b>: put the apparatus away, leaving the two documents") +
       row("?", "this page") +
       row("esc", "close this, or leave Clean") +
       "</table>";

  h += "<h3>the two indexes</h3>" +
       "<p>They are the two roots of the tree on the left, and it folds. You " +
       "do not switch between them: picking a row is what says which one you " +
       "are reading in, and the root it belongs to is marked. A row that " +
       "stands for a <i>file</i> — a document, a module — opens it whole, " +
       "with nothing banded; click its triangle to fold it instead.</p><ul>" +
       "<li><b>Notes</b> — document, section, statement. Pick a statement; " +
       "the right page opens the module that cites it, scrolled to the " +
       "declaration and banded.</li>" +
       "<li><b>Lean</b> — directory, module, declaration, and under each " +
       "module the declarations that carry a citation. Pick one; the paper " +
       "marks every statement it claims to be. Modules are in <i>import " +
       "order</i>, so the tree reads as the development is built up — and a " +
       "module that cites nothing is still listed, because that gap is what " +
       "this reader exists to show.</li></ul>";

  h += "<h3>how the link is made</h3>" +
       "<p>A comment in the formal sources names a statement of the paper by " +
       "its <code>\\label</code>. That is the whole protocol, and this is one " +
       "of them, read from this project's own sources:</p>" +
       helpCitation(sample()) +
       "<p>Nothing is annotated in the paper, and nothing is verified: a " +
       "citation says a declaration <i>claims</i> to be a statement. The two " +
       "texts are put side by side so you can check that in a second.</p>";

  h += "<h3>this run</h3><table class='hkeys'>" +
       row(s.links + "", "citations, reaching " + s.linked_items +
           " distinct statements") +
       row(s.tex_items + "", "statements in " + DOCS.length + " document" +
           (DOCS.length === 1 ? "" : "s") + ", " + s.located + " placed on a page") +
       row(s.lean_decls + "", "declarations over " + s.lean_lines.toLocaleString() +
           " lines in " + s.lean_files + " modules") +
       row(s.tex_refs + " / " + s.decl_refs, "cross-references within the paper " +
           "and within the formalization") +
       row(s.unresolved + "", s.unresolved
           ? "<b class='bad'>dangling citations</b> — they name something no " +
             "document holds, which means one side was renamed and the other " +
             "was not"
           : "dangling citations: every citation resolves") +
       "</table>";

  if (s.unresolved) {
    var seen = {};
    (M.unresolved || []).forEach(function (u) {
      (seen[u.label] = seen[u.label] || []).push(u.file + ".lean:" + u.line);
    });
    h += "<ul class='bad'>";
    Object.keys(seen).sort().forEach(function (k) {
      h += "<li><code>" + esc(k) + "</code> — " + esc(seen[k].slice(0, 4).join(", ")) +
           "</li>";
    });
    h += "</ul>";
  }

  h += "<h3>taking it with you</h3>" +
       "<p><b>Download</b>, top right, packs this page, the PDFs, the LaTeX and " +
       "the formal sources, and the configuration that produced them, into one " +
       "archive. Built by <code>" + esc(M.tool || "interproof") + "</code>" +
       (M.generated ? " on " + esc(M.generated.slice(0, 10)) : "") + ".</p>";
  return h;
}

function row(k, v) {
  return "<tr><td><span class='kbd'>" + esc(k) + "</span></td><td>" + v + "</td></tr>";
}

function toggleHelp(on) {
  var el = $("#help");
  var show = on === undefined ? el.hidden : on;
  if (show && M) el.querySelector("#helpbody").innerHTML = helpHTML();
  el.hidden = !show || !M;
  $("#helpbtn").classList.toggle("on", !el.hidden);
  var c = el.querySelector("#helpclose");
  if (c) c.onclick = function () { toggleHelp(false); };
}

function boot() {
  railBody = $("#railbody"); rhead = $("#rhead"); vhead = $("#vhead");
  verso = $("#leanpane"); noteEl = $("#note"); liveEl = $("#live");
  rscroll = $("#pdfscroll"); vscroll = $("#leanscroll");
  /* Everything the machine page can ask of the build.  It knows how to draw a
     module and nothing about what is in one, which is what lets the same pane
     render an elaborated overlay and a tokenized guess without knowing which
     it was handed. */
  LeanView.init(verso, vscroll, {
    // asked for, not passed: `init` runs before the manifest has been fetched
    prefixes: function () { return (M && M.grammar && M.grammar.label_prefixes) || []; },
    docs: function () { return DOCS.map(function (d) { return d.id; }); },
    label: function (l, prefer) { return findLabel(l, prefer); },
    decl: function (name, inFile) { return findDecl(name, inFile); },
    full: function (name) { return FULL[name] || null; },
    info: function (key) {
      var d = DECL[key];
      return d ? { kind: d.kind, name: d.name, signature: d.signature,
                   doc: d.doc, file: d.file, line: d.line } : null;
    },
    go: function (key) { if (modeOf(key)) select(key); },
  });
  PDFView.init($("#pdfpages"), rscroll, function (key) { select(key); }, allMarks);

  $("#cleanbtn").onclick = function () { toggleClean(); };
  $("#allbtn").onclick = function () { toggleAll(); };
  $("#helpbtn").onclick = function () { toggleHelp(); };
  $("#help").onclick = function (e) { if (e.target === $("#help")) toggleHelp(false); };
  // a new filter is a new tree, and it starts unfolded: what the reader folded
  // away is about the index, not about this search
  function filter(q) { state.q = q; qfold = {}; buildRail(false); }
  $("#search").oninput = function (e) { filter(e.target.value); };

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT") {
      if (e.key === "Escape") { e.target.value = ""; filter(""); e.target.blur(); }
      return;
    }
    if (e.key === "?") toggleHelp();
    else if (e.key === "a") toggleAll();
    else if (e.key === "c") toggleClean();
    // one escape, one thing put away: the sheet is on top, so it goes first
    else if (e.key === "Escape") {
      if (!$("#help").hidden) toggleHelp(false); else toggleClean(false);
    }
  });

  /* deep links stay live: changing only the hash does not reload the page */
  window.addEventListener("hashchange", function () {
    var k = decodeURIComponent((location.hash || "").slice(1));
    if (!k || k === state.sel || !modeOf(k)) return;
    select(k);
  });

  wireDownload();
  if (BOOT.mode === "live") { liveEl.style.display = "flex"; liveMark("wait", "connecting"); }

  /* Nothing above this point needed the manifest, and nothing below runs
     without it.  A build that cannot be read is the one failure this viewer
     cannot work around, so it is stated rather than left as an empty frame. */
  note("reading the manifest…");
  loadManifest().then(function (m) {
    ingest(m);
    note("");
    renderStats();
    markHealth();
    var opened = start(decodeURIComponent((location.hash || "").slice(1)));
    if (BOOT.mode === "live") connect();
    return opened;
  }, function (e) {
    // the two failures are told apart, because they are fixed in different
    // places: one is the build, the other is this file
    note("the manifest could not be read — " + why(e), "err");
    if (BOOT.mode === "live") liveMark("off", "no manifest");
  }).catch(function (e) {
    note("this build could not be opened — " + why(e), "err");
  });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

})();
