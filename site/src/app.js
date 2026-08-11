/* =========================================================================
   Interproof viewer
   ========================================================================= */
(function () {
"use strict";

var M = window.__MANIFEST__;
var TEX = M.tex, BY = M.by_item, LEAN = M.lean, LINKS = M.links;
var PDFS = window.__PDFS__;          // doc -> the compiled PDF, base64

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
   Lean syntax highlighting + citation linkification
   ========================================================================= */

var KW = new Set(("theorem lemma def abbrev instance structure inductive class deriving " +
  "where by fun let have show from calc match with do if then else at " +
  "namespace end section variable variables open universe noncomputable private protected " +
  "partial unsafe scoped local attribute set_option import example mutual return " +
  "exact apply intro intros refine rintro rcases obtain cases induction constructor " +
  "simp simpa rw rwa subst omega ring linarith nlinarith norm_num positivity decide " +
  "rfl trivial exists use ext funext congr gcongr push_cast field_simp " +
  "unfold dsimp change conv first all_goals any_goals repeat try focus " +
  "classical this fin_cases interval_cases specialize contrapose by_cases by_contra " +
  "left right constructor infer_instance assumption").split(/\s+/));

var IDCH = /[A-Za-z0-9_'!?À-ɏͰ-Ͽᴀ-ᵿ₀-ₜ℀-⅏\ud835]/;

function leanCite(text, escaped) {
  /* link `P3:lem:cm`, `note, lem:closure`, bare `thm:interaction` */
  return text.replace(/\b(thm|lem|def|prop|cor|rem|sec|sub|app):([A-Za-z0-9][A-Za-z0-9\-_]*)/g,
    function (whole, kind, name) {
      var lbl = kind + ":" + name.replace(/\.$/, "");
      var cm = lbl.match(/^(.*)\.(\d+)$/); if (cm) lbl = cm[1];
      var key = HAS["P3::" + lbl] ? "P3::" + lbl : (HAS["note::" + lbl] ? "note::" + lbl : null);
      if (!key) return whole;
      return '<span class="' + (escaped ? "citec" : "cite") + '" data-go="' + key + '">' + whole + "</span>";
    });
}

function highlightLean(code) {
  var out = "", i = 0, n = code.length;
  function push(cls, txt) { out += '<span class="' + cls + '">' + txt + "</span>"; }
  while (i < n) {
    var c = code[i];
    if (c === "/" && code[i + 1] === "-") {
      var d = 0, j = i;
      while (j < n) {
        if (code[j] === "/" && code[j + 1] === "-") { d++; j += 2; }
        else if (code[j] === "-" && code[j + 1] === "/") { d--; j += 2; if (!d) break; }
        else j++;
      }
      push("cm", leanCite(esc(code.slice(i, j)), true)); i = j; continue;
    }
    if (c === "-" && code[i + 1] === "-" && (i === 0 || /[\s(\[]/.test(code[i - 1]))) {
      var e = code.indexOf("\n", i); e = e < 0 ? n : e;
      push("cm", leanCite(esc(code.slice(i, e)), true)); i = e; continue;
    }
    if (c === '"') {
      var k = i + 1;
      while (k < n) { if (code[k] === "\\") { k += 2; continue; } if (code[k] === '"') { k++; break; } k++; }
      push("st", esc(code.slice(i, k))); i = k; continue;
    }
    if (c === "@" && code[i + 1] === "[") {
      var q = code.indexOf("]", i); q = q < 0 ? n : q + 1;
      push("at", esc(code.slice(i, q))); i = q; continue;
    }
    if (IDCH.test(c) && !/[0-9]/.test(c)) {
      var p = i; while (p < n && IDCH.test(code[p])) p++;
      var w = code.slice(i, p);
      if (w === "sorry") push("srr", w);
      else if (KW.has(w)) {
        push("kw", w);
        /* declaration name right after a declaration keyword */
        if (/^(theorem|lemma|def|abbrev|structure|inductive|instance|class)$/.test(w)) {
          var r = p; while (r < n && code[r] === " ") r++;
          var t = r; while (t < n && IDCH.test(code[t])) t++;
          if (t > r) { out += code.slice(p, r); push("nm2", esc(code.slice(r, t))); p = t; }
        }
      }
      else out += esc(w);
      i = p; continue;
    }
    if (/[0-9]/.test(c)) { var z = i; while (z < n && /[0-9.]/.test(code[z])) z++; push("num", code.slice(i, z)); i = z; continue; }
    out += esc(c); i++;
  }
  return out;
}

/* lean docstrings are prose with markdown-ish accents */
function docToHtml(doc) {
  if (!doc) return "";
  var s = esc(doc);
  s = s.replace(/`([^`\n]+)`/g, function (_, c) { return "<code>" + c + "</code>"; });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  s = leanCite(s, false);
  return s.split(/\n\s*\n/).map(function (p) { return "<p>" + p.trim().replace(/\n/g, " ") + "</p>"; }).join("");
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
      if (a[1].doc !== b[1].doc) return a[1].doc === "P3" ? -1 : 1;
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
      var grp = (it.doc === "P3" ? "P3 · " : "NOTE · ") + (it.section || "");
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

var DOCNAME = { P3: "P3 · EasyPQC on a Concrete Semantics",
                note: "note · Quantum Procedure Call Semantics" };

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
  var h = '<div class="crumb"><span>' + DOCNAME[it.doc] + "</span>";
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
       '</span><span class="src">' + esc(it.file) + ":" + it.line + "</span></div>";

  /* items this one cross-references, and — when several are marked at once —
     the siblings, so the marks in the scroll are all reachable by name */
  var chips = "";
  keys.forEach(function (k, i) {
    if (i === focus || !TEX[k]) return;
    chips += '<span class="chip on" data-go="' + k + '">' + esc(TEX[k].label) + "</span>";
  });
  (it.refs || []).forEach(function (l) {
    var k = HAS[it.doc + "::" + l] ? it.doc + "::" + l
          : (HAS[(it.doc === "P3" ? "note" : "P3") + "::" + l]
             ? (it.doc === "P3" ? "note" : "P3") + "::" + l : null);
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

function declCard(leanKey, links, open) {
  var parts = leanKey.split("::"), fname = parts[0], dname = parts[1];
  var d = DECL[leanKey];
  var f = FILE[fname];
  var lines = links.map(function (l) { return l.line; }).sort(function (a, b) { return a - b; });
  var h = '<details class="decl focus"' + (open ? " open" : "") + ">";
  h += '<summary class="dh"><span class="k">' + (d ? d.kind : "module") + "</span>";
  h += '<span class="n">' + esc(dname) + "</span>";
  if (d && d.has_sorry) h += '<span class="why" style="color:#e06c6c;border-color:#7a3030">sorry</span>';
  if (d && d.section) h += '<span class="k">' + esc(d.section) + "</span>";
  h += '<span class="loc">' + esc(fname) + ".lean:" + (d ? d.line : lines[0]) + "</span></summary>";

  if (d && d.doc) h += '<div class="doc">' + docToHtml(d.doc) + "</div>";
  else if (!d) h += '<div class="doc">' + docToHtml(f ? f.module_doc : "") + "</div>";

  var code = d ? d.code : "";
  if (code) {
    var arr = code.split("\n");
    var CUT = 18;
    if (arr.length > CUT) {
      h += '<pre class="code">' + highlightLean(arr.slice(0, CUT).join("\n")) + "</pre>";
      h += '<pre class="code hid" style="display:none">' + highlightLean(arr.slice(CUT).join("\n")) + "</pre>";
      h += '<button class="fold">show ' + (arr.length - CUT) + " more lines</button>";
    } else {
      h += '<pre class="code">' + highlightLean(code) + "</pre>";
    }
  }
  h += "</details>";
  return h;
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
  var files = {}; keys.forEach(function (k) { files[k.split("::")[0]] = 1; });

  vhead.innerHTML = links.length
    ? "<b>" + links.length + "</b> citation" + (links.length > 1 ? "s" : "") +
      " · <b>" + keys.length + "</b> declaration" + (keys.length > 1 ? "s" : "") +
      " · " + Object.keys(files).length + " file" + (Object.keys(files).length > 1 ? "s" : "")
    : "no Lean counterpart";

  if (!keys.length) {
    verso.innerHTML = '<div class="pad"><div class="empty" style="color:var(--machine-dim)">' +
      "<b style=\"color:var(--amber)\">" + esc(it.label) + "</b> is not cited anywhere in the Lean sources.<br><br>" +
      "Either it is out of the mechanization scope, or the citation is missing.<br>" +
      "Both are findings: this pane is the gap report." +
      "</div></div>";
    return;
  }
  var h = '<div class="pad">';
  keys.forEach(function (k, i) {
    h += declCard(k, groups[k], i === 0);
  });
  h += "</div>";
  verso.innerHTML = h;
  wire(verso);
}

function selectLean(key) {
  var links = BY_DECL[key] || [];
  verso.innerHTML = '<div class="pad">' + declCard(key, links, true) + "</div>";
  vhead.innerHTML = "<b>" + key.split("::")[0] + ".lean</b> · " +
    links.length + " citation" + (links.length > 1 ? "s" : "");

  /* every paper item this declaration cites is marked at once; the first
     decides which of the two documents the scroll shows */
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
  verso.parentElement.scrollTop = 0;
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
           (curDoc === "P3" ? "P3 — easypqc" : "note — semantics") + "</div><div></div>";
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
  railBody = $("#railbody"); rhead = $("#rhead"); verso = $("#verso"); vhead = $("#vhead");
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
  if (!TEX[start]) start = "P3::thm:interaction";
  if (!TEX[start]) start = itemsOrdered()[0][0];
  select(start);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();

})();
