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

/* citations grouped by lean declaration */
var BY_DECL = {};                    // "File::name" (or "File::⟨module⟩") -> links
LINKS.forEach(function (l) {
  var k = l.file + "::" + (l.decl || "⟨module⟩");
  (BY_DECL[k] = BY_DECL[k] || []).push(l);
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

var state = { mode: "paper", sel: null, q: "", proof: false };

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
  } else {
    LEAN.forEach(function (f) {
      var rows = [];
      var mk = f.name + "::⟨module⟩";
      if (BY_DECL[mk]) rows.push(["⟨module⟩", BY_DECL[mk].length, mk]);
      f.decls.forEach(function (d) {
        var k = f.name + "::" + d.name;
        if (BY_DECL[k]) rows.push([d.name, BY_DECL[k].length, k]);
      });
      rows = rows.filter(function (r) {
        if (!q) return true;
        var cited = BY_DECL[r[2]].map(function (l) { return l.label; }).join(" ");
        return (f.name + " " + r[0] + " " + cited).toLowerCase().indexOf(q) >= 0;
      });
      if (!rows.length) return;
      html += '<div class="grp">' + esc(f.name) + ".lean · " + f.lines + " lines</div>";
      rows.forEach(function (r) {
        html += '<div class="itm has' + (state.sel === r[2] ? " sel" : "") +
          '" data-key="' + r[2] + '" style="animation-delay:' + Math.min(n * 8, 260) + 'ms">' +
          '<div class="kd">' + (r[0] === "⟨module⟩" ? "mod" : "decl") + "</div>" +
          '<div class="nm">' + esc(r[0]) + "</div>" +
          '<div class="ct">' + r[1] + "</div></div>";
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
  h += '<button class="rbtn" data-zoom="0.9">&minus;</button>' +
       '<button class="rbtn" data-zoom="1.1">+</button>' +
       '<button class="rbtn" data-zoom="fit">fit</button></span></div>';

  h += '<div class="rid"><span class="lbl">' + esc(it.kind) + " — " + esc(it.label) +
       '</span><span class="src">' + esc(it.doc + "/" + it.file) + ":" + it.line +
       "</span></div>";

  /* items this one cross-references, and — when several are marked at once —
     the siblings, so the marks in the scroll are all reachable by name */
  var chips = "";
  keys.forEach(function (k, i) {
    if (i === focus || !TEX[k]) return;
    chips += '<span class="chip on" data-go="' + k + '">' + esc(TEX[k].label) + "</span>";
  });
  (it.refs || []).forEach(function (l) {
    var k = findLabel(l, it.doc);
    if (k && keys.indexOf(k) < 0) chips += '<span class="chip" data-go="' + k + '">' + esc(l) + "</span>";
  });
  if (chips) h += '<div class="chips"><i>cites</i>' + chips + "</div>";
  return h;
}

/* put the marks in the scroll and bring the focused one into view */
function paperShow(keys, focus) {
  var it = TEX[keys[focus]];
  if (!it) return;
  rhead.innerHTML = paperHead(keys, focus);
  wire(rhead);
  rhead.querySelectorAll("[data-zoom]").forEach(function (b) {
    b.onclick = function () {
      var z = b.dataset.zoom;
      if (z === "fit") PDFView.refit(); else PDFView.zoom(+z);
    };
  });
  var pb = rhead.querySelector("#proofbtn");
  if (pb) pb.onclick = function () { state.proof = !state.proof; paperShow(keys, focus); };

  /* only the focused document can be shown at once */
  var same = keys.filter(function (k) { return TEX[k] && TEX[k].doc === it.doc; });
  var rects = same.map(function (k) {
    var t = TEX[k];
    return (state.proof && t.proof_rect) ? t.proof_rect : t.rect;
  });
  var idx = same.indexOf(keys[focus]);

  PDFView.load(it.doc, PDFS[it.doc], located(it.doc)).then(function () {
    PDFView.show(rects.filter(Boolean), idx);
  });
}

/* ---- the machine page -------------------------------------------------- */

/* the lines a citation occupies: the declaration it belongs to, docstring
   included, or the citing line itself when the citation is module prose */
function leanRange(leanKey, links) {
  var d = DECL[leanKey];
  if (d) return { from: d.doc_line || d.line, to: d.end_line };
  var ls = links.map(function (l) { return l.line; });
  return { from: Math.min.apply(null, ls), to: Math.max.apply(null, ls) };
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
  h += '<span class="loc">' + esc(fname) + ".lean:" +
       (d ? d.line : leanRange(keys[focus], groups[keys[focus]]).from) + "</span></span>";

  var chips = "";
  keys.forEach(function (k, i) {
    if (i === focus) return;
    var p = k.split("::");
    chips += '<span class="chip" data-decl="' + esc(k) + '">' +
             (p[0] === fname ? "" : esc(p[0]) + ".") + esc(p[1]) + "</span>";
  });
  if (chips) h += '<div class="chips"><i>also</i>' + chips + "</div>";
  return h;
}

/* show one module, banding every cited declaration it holds */
function leanShow(keys, focus, groups, total) {
  var fname = keys[focus].split("::")[0];
  vhead.innerHTML = leanHead(keys, focus, groups, total);
  vhead.querySelectorAll("[data-decl]").forEach(function (el) {
    el.onclick = function () { leanShow(keys, keys.indexOf(el.dataset.decl), groups, total); };
  });

  var same = keys.filter(function (k) { return k.split("::")[0] === fname; });
  LeanView.load(fname, FILE[fname].text);
  LeanView.show(same.map(function (k) { return leanRange(k, groups[k]); }),
                same.indexOf(keys[focus]));
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
    PDFView.clear();
    return;
  }
  paperShow(cited, 0);
}

function select(key) {
  state.sel = key;
  if (state.mode === "paper") selectPaper(key); else selectLean(key);
  wire(verso);
  buildRail();
  location.hash = encodeURIComponent(key);
  var sel = railBody.querySelector(".itm.sel");
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

/* ---- coverage ---------------------------------------------------------- */

function buildCoverage() {
  var files = LEAN.map(function (f) { return f.name; });
  var rows = itemsOrdered();
  var h = '<div class="inner"><h2>Correspondence coverage</h2>';
  h += '<div class="sub">' + M.stats.links + " citations harvested from " + M.stats.lean_lines.toLocaleString() +
       " lines of Lean across " + M.stats.lean_files + " modules · " +
       M.stats.tex_items + " labelled items in the two documents · " +
       M.stats.unresolved + " dangling references<br>" +
       "each column is a Lean module, in import order</div>";
  h += '<div class="covgrid"><div></div><div class="colhead">' +
       files.map(function (f) { return "<span><b>" + esc(f) + "</b></span>"; }).join("") +
       "</div>";
  var curDoc = null;
  rows.forEach(function (e) {
    var key = e[0], it = e[1];
    if (it.doc !== curDoc) {
      curDoc = it.doc;
      h += '<div class="rl" style="color:var(--amber);font-size:10px;letter-spacing:.12em;text-transform:uppercase">' +
           esc(curDoc + " — " + DOC[curDoc].short) + "</div><div></div>";
    }
    var links = BY[key] || [];
    var per = {}; links.forEach(function (l) { per[l.file] = (per[l.file] || 0) + 1; });
    h += '<div class="rl' + (links.length ? "" : " no") + '" data-go2="' + key + '">' + esc(it.label) + "</div>";
    h += '<div class="covbar">';
    files.forEach(function (f) {
      var c = per[f] || 0;
      h += '<div class="cell' + (c ? (c > 2 ? " f" : " f lo") : "") + '" title="' + f + ": " + c + '"></div>';
    });
    h += '<div style="font-family:var(--mono);font-size:10px;color:var(--machine-dim);margin-left:10px">' +
         (links.length || "") + "</div></div>";
  });
  h += "</div>";

  var gaps = rows.filter(function (e) { return !(BY[e[0]] || []).length; });
  h += '<div class="gap"><h3>' + gaps.length + " items with no Lean counterpart</h3><ul>";
  gaps.forEach(function (e) {
    h += '<li data-go2="' + e[0] + '"><span>' + e[1].doc + "</span>" + esc(e[1].label) +
         '<span style="margin-left:auto">' + esc(e[1].title) + "</span></li>";
  });
  h += "</ul></div>";

  h += '<div class="covlegend">' +
    '<span><i style="background:var(--amber)"></i>3+ citations in that module</span>' +
    '<span><i style="background:rgba(221,139,60,.42)"></i>1–2 citations</span>' +
    '<span><i style="background:var(--machine-3)"></i>none</span></div>';
  h += "</div>";
  $("#cov").innerHTML = h;
  $("#cov").querySelectorAll("[data-go2]").forEach(function (el) {
    el.onclick = function () {
      toggleCov(false);
      if (state.mode !== "paper") { state.mode = "paper"; syncModes(); }
      select(el.dataset.go2);
    };
  });
}

function toggleCov(on) {
  var c = $("#cov");
  var want = on === undefined ? !c.classList.contains("on") : on;
  c.classList.toggle("on", want);
  $("#covbtn").classList.toggle("on", want);
  if (want && !c.dataset.built) { buildCoverage(); c.dataset.built = "1"; }
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
  buildRail();
  var first = railBody.querySelector(".itm");
  if (first) select(first.dataset.key);
}

/* ---- boot -------------------------------------------------------------- */

function boot() {
  railBody = $("#railbody"); rhead = $("#rhead"); vhead = $("#vhead");
  verso = $("#leanpane");
  LeanView.init(verso, $("#leanscroll"), function (label) { return findLabel(label); });
  PDFView.init($("#pdfpages"), $("#pdfscroll"), function (key) {
    if (state.mode !== "paper") { state.mode = "paper"; syncModes(); }
    select(key);
  });

  $("#stats").innerHTML =
    '<div class="stat"><b>' + M.stats.tex_items + "</b>items</div>" +
    '<div class="stat"><b>' + M.stats.lean_decls + "</b>lean decls</div>" +
    '<div class="stat acc"><b>' + M.stats.links + "</b>links</div>" +
    '<div class="stat"><b>' + M.stats.unresolved + "</b>dangling</div>";

  document.querySelectorAll(".modes button").forEach(function (b) {
    b.onclick = function () { setMode(b.dataset.mode); };
  });
  $("#covbtn").onclick = function () { toggleCov(); };
  $("#search").oninput = function (e) { state.q = e.target.value; buildRail(); };

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT") {
      if (e.key === "Escape") { e.target.value = ""; state.q = ""; buildRail(); e.target.blur(); }
      return;
    }
    if (e.key === "/") { e.preventDefault(); $("#search").focus(); }
    else if (e.key === "g") toggleCov();
    else if (e.key === "Escape") toggleCov(false);
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
    var m = TEX[k] ? "paper" : (BY_DECL[k] ? "lean" : null);
    if (!m) return;
    if (state.mode !== m) { state.mode = m; syncModes(); }
    select(k);
  });

  syncModes();
  buildRail();
  var start = decodeURIComponent((location.hash || "").slice(1));
  if (!TEX[start]) start = itemsOrdered()[0][0];
  select(start);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

})();
