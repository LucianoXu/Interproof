/* =========================================================================
   Interproof viewer
   ========================================================================= */
(function () {
"use strict";

var M = window.__MANIFEST__;
var TEX = M.tex, BY = M.by_item, LEAN = M.lean, LINKS = M.links;
var PDFS = window.__PDFS__;          // doc -> the compiled PDF, base64

/* The document set comes from the manifest; this file names no document.
   DOCS is in document order, which is also the order items sort in. */
var DOCS = M.docs;
var DOC = {}, DOCPOS = {};
DOCS.forEach(function (d, i) { DOC[d.id] = d; DOCPOS[d.id] = i; });

/* resolve a bare label against the documents, preferring one of them */
function findLabel(label, prefer) {
  if (prefer && HAS[prefer + "::" + label]) return prefer + "::" + label;
  for (var i = 0; i < DOCS.length; i++) {
    var k = DOCS[i].id + "::" + label;
    if (HAS[k]) return k;
  }
  return null;
}

/* ---- lean index -------------------------------------------------------- */
var DECL = {};                       // "File::name" -> decl
var FILE = {};                       // "File" -> file record
LEAN.forEach(function (f) {
  FILE[f.name] = f;
  f.decls.forEach(function (d) { DECL[f.name + "::" + d.name] = d; });
});

/* citations grouped by lean declaration, and per module, for the file index */
var BY_DECL = {};                    // "File::name" (or "File::⟨module⟩") -> links
var BY_FILE = {};                    // "File" -> citation count
LINKS.forEach(function (l) {
  var k = l.file + "::" + (l.decl || "⟨module⟩");
  (BY_DECL[k] = BY_DECL[k] || []).push(l);
  BY_FILE[l.file] = (BY_FILE[l.file] || 0) + 1;
});

/* the reference structure among Lean declarations.  `uses` — what a
   declaration names in its own code — is in the manifest; what uses it exists
   only as the sum of every other declaration's, so it is inverted here. */
var USES = {}, USEDBY = {};
LEAN.forEach(function (f) {
  f.decls.forEach(function (d) {
    var k = f.name + "::" + d.name;
    USES[k] = d.uses || [];
    USES[k].forEach(function (t) { (USEDBY[t] = USEDBY[t] || []).push(k); });
  });
});

/* labels that exist, per document — for xref resolution */
var HAS = {};
Object.keys(TEX).forEach(function (k) { HAS[k] = true; });

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* =========================================================================
   state
   ========================================================================= */

/* `sel` is the focused rail row.  The file index opens two things at once —
   one document, one module — so it keeps its own pair; both stay marked in
   the rail, and `sel` only says which of them was touched last. */
var state = { mode: "paper", sel: null, q: "", proof: false, fdoc: null, ffile: null,
              all: false, marked: [], clean: false };

var $ = function (s) { return document.querySelector(s); };
var railBody, rhead, verso, vhead;

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
                  conjecture: "conj", assumption: "assm" };

/* what each document holds, for the file index: labelled items, and how many
   of them a Lean module cites */
var DOCSTAT = {};
DOCS.forEach(function (d) { DOCSTAT[d.id] = { items: 0, linked: 0 }; });
itemsOrdered().forEach(function (e) {
  var s = DOCSTAT[e[1].doc];
  if (!s) return;
  s.items++;
  if ((BY[e[0]] || []).length) s.linked++;
});

/* the Lean sources by directory — the file index mirrors the tree rather than
   flattening it, because in a formalization the directory is the first thing
   that says what a module is for.  Inside a directory the manifest's order is
   kept, which is import order: alphabetical order is the file system's, and it
   says nothing about how the development is built up. */
function leanTree() {
  var byDir = {}, dirs = [];
  LEAN.forEach(function (f) {
    var p = f.path || f.name + ".lean";
    var cut = p.lastIndexOf("/");
    var dir = cut < 0 ? "" : p.slice(0, cut);
    if (!byDir[dir]) { byDir[dir] = []; dirs.push(dir); }
    byDir[dir].push({ file: f, base: p.slice(cut + 1), depth: dir ? dir.split("/").length : 0 });
  });
  return dirs.map(function (d) { return { dir: d, files: byDir[d] }; });
}

/* ---- rail -------------------------------------------------------------- */

function buildRail() {
  var q = state.q.toLowerCase();
  var html = "", n = 0;

  if (state.mode === "paper") {
    var lastGrp = null;
    itemsOrdered().forEach(function (e) {
      var key = e[0], it = e[1];
      var hay = (it.label + " " + it.title + " " + it.section + " " + it.subsection).toLowerCase();
      var leanHay = (BY[key] || []).map(function (l) { return l.file + " " + (l.decl || ""); }).join(" ").toLowerCase();
      if (q && hay.indexOf(q) < 0 && leanHay.indexOf(q) < 0) return;
      var grp = it.doc.toUpperCase() + " · " + (it.section || "");
      if (grp !== lastGrp) { html += '<div class="grp">' + esc(grp) + "</div>"; lastGrp = grp; }
      var ct = (BY[key] || []).length;
      html += '<div class="itm' + (ct ? " has" : "") + (state.sel === key ? " sel" : "") +
        '" data-key="' + key + '" style="animation-delay:' + Math.min(n * 8, 260) + 'ms">' +
        '<div class="kd">' + (KINDSHORT[it.kind] || it.kind.slice(0, 4)) + "</div>" +
        '<div class="nm">' + esc(it.title || it.label) + "</div>" +
        '<div class="ct">' + (ct || "·") + "</div></div>";
      n++;
    });
  } else if (state.mode === "files") {
    /* one row per source file: the documents flat, the modules as they sit
       on disk.  Nothing here depends on the correspondence — this is the
       index for a reader who knows what file they want. */
    var frow = function (key, kd, nm, ct, has, pad) {
      var open = key === "paper::" + state.fdoc || key === "lean::" + state.ffile;
      html += '<div class="itm file' + (has ? " has" : "") + (open ? " sel" : "") +
        '" data-key="' + esc(key) + '" style="animation-delay:' + Math.min(n * 8, 260) + 'ms">' +
        '<div class="kd">' + esc(kd) + "</div>" +
        '<div class="nm"' + (pad ? ' style="padding-left:' + pad + 'px"' : "") + ">" +
        esc(nm) + "</div>" +
        '<div class="ct">' + esc(ct) + "</div></div>";
      n++;
    };

    var docs = DOCS.filter(function (d) {
      return !q || (d.id + " " + d.title + " " + (d.main || "")).toLowerCase().indexOf(q) >= 0;
    });
    if (docs.length) {
      html += '<div class="grp">papers</div>';
      docs.forEach(function (d) {
        var s = DOCSTAT[d.id];
        frow("paper::" + d.id, d.id, d.title, s.items, s.linked > 0, 0);
      });
    }
    leanTree().forEach(function (g) {
      var files = g.files.filter(function (r) {
        return !q || (r.file.path || r.file.name).toLowerCase().indexOf(q) >= 0;
      });
      if (!files.length) return;
      var sep = ' <span class="dim">/</span> ';
      html += '<div class="grp">lean' +
        (g.dir ? sep + esc(g.dir).split("/").join(sep) : "") + "</div>";
      files.forEach(function (r) {
        frow("lean::" + r.file.name, "lean", r.base,
             r.file.lines.toLocaleString(), (BY_FILE[r.file.name] || 0) > 0, r.depth * 10);
      });
    });
  } else {
    LEAN.forEach(function (f) {
      var rows = [];
      var mk = f.name + "::⟨module⟩";
      if (BY_DECL[mk]) rows.push(["⟨module⟩", BY_DECL[mk].length, mk]);
      f.decls.forEach(function (d) {
        var k = f.name + "::" + d.name;
        // a declaration reached by following a reference has no citations of
        // its own; it is still where the reader is, so the rail says so
        if (BY_DECL[k]) rows.push([d.name, BY_DECL[k].length, k]);
        else if (state.sel === k) rows.push([d.name, 0, k]);
      });
      rows = rows.filter(function (r) {
        if (!q) return true;
        var cited = (BY_DECL[r[2]] || []).map(function (l) { return l.label; }).join(" ");
        return (f.name + " " + r[0] + " " + cited).toLowerCase().indexOf(q) >= 0;
      });
      if (!rows.length) return;
      html += '<div class="grp">' + esc(f.name) + ".lean · " + f.lines + " lines</div>";
      rows.forEach(function (r) {
        html += '<div class="itm' + (r[1] ? " has" : "") + (state.sel === r[2] ? " sel" : "") +
          '" data-key="' + r[2] + '" style="animation-delay:' + Math.min(n * 8, 260) + 'ms">' +
          '<div class="kd">' + (r[0] === "⟨module⟩" ? "mod" : "decl") + "</div>" +
          '<div class="nm">' + esc(r[0]) + "</div>" +
          '<div class="ct">' + (r[1] || "·") + "</div></div>";
        n++;
      });
    });
  }
  railBody.innerHTML = html || '<div class="grp">no match</div>';
  railBody.querySelectorAll(".itm").forEach(function (el) {
    el.onclick = function () { select(el.dataset.key); };
  });
}

/* ---- the paper page ---------------------------------------------------- */

/* every placed item of a document, so a followed PDF link can be named */
var LOCATED = {};
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

/* put the marks in the scroll and bring the focused one into view */
function paperShow(keys, focus) {
  var it = TEX[keys[focus]];
  if (!it) return;
  state.marked = keys;               // these carry their own band; no overlay
  paperHeadShow(keys, focus);

  /* only the focused document can be shown at once */
  var same = keys.filter(function (k) { return TEX[k] && TEX[k].doc === it.doc; });
  var rects = same.map(function (k) {
    var t = TEX[k];
    return (state.proof && t.proof_rect) ? t.proof_rect : t.rect;
  });
  var idx = same.indexOf(keys[focus]);

  PDFView.load(it.doc, PDFS[it.doc], located(it.doc)).then(function () {
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
    el.onclick = function () {
      if (state.mode !== "lean") { state.mode = "lean"; syncModes(); }
      select(el.dataset.use);
    };
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
  LeanView.load(fname, FILE[fname].text);
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
  paperShow([key], 0);

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
    return;
  }
  leanShow(keys, 0, groups, links.length);
}

function selectLean(key) {
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
    return;
  }
  paperShow(cited, 0);
}

/* ---- the file index ---------------------------------------------------- */

/* The two directional modes each drive both pages from one selection.  This
   one drives one page at a time: pick a document, the left page opens it whole;
   pick a module, the right page opens that.  Nothing is banded, because nothing
   was selected — and the pair on screen is whatever the reader put there, which
   is the one thing the correspondence cannot arrange for them. */

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

function showDocument(id) {
  var moved = PDFView.doc() !== id;
  state.fdoc = id;
  state.marked = [];
  rhead.innerHTML = docFileHead(id);
  wireZoom(rhead);
  PDFView.load(id, PDFS[id], located(id)).then(function () {
    if (state.mode !== "files" || state.fdoc !== id) return;
    PDFView.clear();                       // a file is open, no item is selected
    PDFView.repaintMarks();
    if (moved) PDFView.top();
    var pn = rhead.querySelector("#pdfpn");
    if (pn) pn.textContent = PDFView.pages() + " pages · ";
  });
}

function showModule(name) {
  var moved = LeanView.file() !== name;
  state.ffile = name;
  vhead.innerHTML = moduleFileHead(name);
  vhead.querySelectorAll("[data-mod]").forEach(function (el) {
    el.onclick = function () { select("lean::" + el.dataset.mod); };
  });
  LeanView.load(name, FILE[name].text);
  LeanView.clear();
  if (moved) LeanView.top();
  wire(verso);
}

function selectFiles(key) {
  var cut = key.indexOf("::");
  var what = key.slice(0, cut), id = key.slice(cut + 2);
  if (what === "paper") showDocument(id); else showModule(id);
}

/* entering the mode moves no scroll position: whatever the two pages were
   showing is what the index opens on, unless a key names one of them */
function enterFiles(key) {
  var want = key ? key.slice(0, key.indexOf("::")) : "";
  var id = key ? key.slice(key.indexOf("::") + 2) : "";
  state.fdoc = (want === "paper" ? id : null) || state.fdoc || PDFView.doc() || DOCS[0].id;
  state.ffile = (want === "lean" ? id : null) || state.ffile || LeanView.file() || LEAN[0].name;
  showDocument(state.fdoc);
  showModule(state.ffile);
  state.sel = key || "paper::" + state.fdoc;
  buildRail();
  location.hash = encodeURIComponent(state.sel);
}

function select(key) {
  state.sel = key;
  expand = {};                       // a new selection, a new set of neighbours
  if (state.mode === "paper") selectPaper(key);
  else if (state.mode === "files") selectFiles(key);
  else selectLean(key);
  wire(verso);
  buildRail();
  location.hash = encodeURIComponent(key);
  var sel = railBody.querySelector('.itm[data-key="' + key + '"]');
  if (sel) sel.scrollIntoView({ block: "nearest" });
}

function wire(root) {
  root.querySelectorAll("[data-go]").forEach(function (el) {
    el.onclick = function (ev) {
      ev.stopPropagation();
      var k = el.dataset.go;
      if (!TEX[k]) return;
      if (state.mode !== "paper") { state.mode = "paper"; syncModes(); }
      select(k);
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

function syncModes() {
  document.querySelectorAll(".modes button").forEach(function (b) {
    b.classList.toggle("on", b.dataset.mode === state.mode);
  });
}

function setMode(m) {
  if (state.mode === m) return;
  state.mode = m;
  syncModes();
  if (m === "files") { enterFiles(null); return; }
  buildRail();
  var first = railBody.querySelector(".itm");
  if (first) select(first.dataset.key);
}

/* which index a key belongs to — the file index prefixes its own, so the three
   key spaces stay disjoint and a deep link picks its own tab */
function modeOf(k) {
  if (!k) return null;
  var cut = k.indexOf("::");
  var head = cut < 0 ? "" : k.slice(0, cut), rest = k.slice(cut + 2);
  if (head === "paper" && DOC[rest]) return "files";
  if (head === "lean" && FILE[rest]) return "files";
  if (TEX[k]) return "paper";
  if (BY_DECL[k] || DECL[k]) return "lean";
  return null;
}

/* ---- boot -------------------------------------------------------------- */

function boot() {
  railBody = $("#railbody"); rhead = $("#rhead"); vhead = $("#vhead");
  verso = $("#leanpane");
  LeanView.init(verso, $("#leanscroll"), function (label) { return findLabel(label); });
  PDFView.init($("#pdfpages"), $("#pdfscroll"), function (key) {
    if (state.mode !== "paper") { state.mode = "paper"; syncModes(); }
    select(key);
  }, allMarks);

  $("#stats").innerHTML =
    '<div class="stat acc"><b>' + M.stats.links + "</b>links</div>" +
    '<div class="stat"><b>' + M.stats.unresolved + "</b>dangling</div>";

  document.querySelectorAll(".modes button").forEach(function (b) {
    b.onclick = function () { setMode(b.dataset.mode); };
  });
  $("#cleanbtn").onclick = function () { toggleClean(); };
  $("#allbtn").onclick = function () { toggleAll(); };
  $("#search").oninput = function (e) { state.q = e.target.value; buildRail(); };

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT") {
      if (e.key === "Escape") { e.target.value = ""; state.q = ""; buildRail(); e.target.blur(); }
      return;
    }
    // asking to filter is asking for the rail back
    if (e.key === "/") { e.preventDefault(); toggleClean(false); $("#search").focus(); }
    else if (e.key === "a") toggleAll();
    else if (e.key === "c") toggleClean();
    else if (e.key === "Escape") toggleClean(false);
    else if (e.key === "j" || e.key === "k") {
      var all = [].slice.call(railBody.querySelectorAll(".itm"));
      var i = all.findIndex(function (el) { return el.classList.contains("sel"); });
      var nx = all[Math.max(0, Math.min(all.length - 1, i + (e.key === "j" ? 1 : -1)))];
      if (nx) select(nx.dataset.key);
    }
  });

  /* deep links stay live: changing only the hash does not reload the page */
  window.addEventListener("hashchange", function () {
    var k = decodeURIComponent((location.hash || "").slice(1));
    if (!k || k === state.sel) return;
    var m = modeOf(k);
    if (!m) return;
    if (state.mode !== m) {
      state.mode = m; syncModes();
      if (m === "files") { enterFiles(k); return; }
    }
    select(k);
  });

  var start = decodeURIComponent((location.hash || "").slice(1));
  state.mode = modeOf(start) || "paper";
  syncModes();
  if (state.mode === "files") { enterFiles(start); return; }
  buildRail();
  if (!modeOf(start)) start = itemsOrdered()[0][0];
  select(start);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

})();
