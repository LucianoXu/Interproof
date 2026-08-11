/* =========================================================================
   Interproof — the machine page, as the module

   The counterpart of the PDF pane: the whole `.lean` file scrolled and
   banded, rather than the declaration cut out of it.  A slice answers "what
   does this say"; only the file answers "where in the module does it sit,
   and what is around it" — which is most of what reading an unfamiliar
   formalization consists of.

   Lines never wrap, so a line's position is `(n - 1) x lineHeight` and a band
   is arithmetic rather than layout.  The height is measured once per render
   instead of being duplicated from the stylesheet.
   ========================================================================= */
(function () {
"use strict";

var FILES = {};                 // name -> { text, lines }
var cur = null, lh = 0, top0 = 0;   // line height, and where line 1 starts
var host, scroller, resolve;    // #leanpane, its scrolling ancestor, label -> key

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

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* citations inside comments become links, in either the label or `Doc:label` form */
function cite(text) {
  return text.replace(/\b(thm|lem|def|prop|cor|rem|sec|sub|app):([A-Za-z0-9][A-Za-z0-9\-_]*)/g,
    function (whole, kind, name) {
      var lbl = kind + ":" + name.replace(/\.$/, "");
      var cm = lbl.match(/^(.*)\.(\d+)$/);
      if (cm) lbl = cm[1];
      var key = resolve && resolve(lbl);
      return key ? '<span class="citec" data-go="' + key + '">' + whole + "</span>" : whole;
    });
}

/* A tokenizer, not a parser: enough to tell comment from code from binder.
   Spans are closed at every newline so the result can be split into lines. */
function highlight(code) {
  var out = "", i = 0, n = code.length;
  function push(cls, txt) {
    out += txt.split("\n").map(function (t) {
      return t ? '<span class="' + cls + '">' + t + "</span>" : "";
    }).join("\n");
  }
  while (i < n) {
    var c = code[i];
    if (c === "/" && code[i + 1] === "-") {
      var d = 0, j = i;
      while (j < n) {
        if (code[j] === "/" && code[j + 1] === "-") { d++; j += 2; }
        else if (code[j] === "-" && code[j + 1] === "/") { d--; j += 2; if (!d) break; }
        else j++;
      }
      push("cm", cite(esc(code.slice(i, j)))); i = j; continue;
    }
    if (c === "-" && code[i + 1] === "-" && (i === 0 || /[\s(\[]/.test(code[i - 1]))) {
      var e = code.indexOf("\n", i); e = e < 0 ? n : e;
      push("cm", cite(esc(code.slice(i, e)))); i = e; continue;
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
        if (/^(theorem|lemma|def|abbrev|structure|inductive|instance|class)$/.test(w)) {
          var r = p; while (r < n && code[r] === " ") r++;
          var t = r; while (t < n && IDCH.test(code[t])) t++;
          if (t > r) { out += code.slice(p, r); push("nm2", esc(code.slice(r, t))); p = t; }
        }
      } else out += esc(w);
      i = p; continue;
    }
    if (/[0-9]/.test(c)) {
      var z = i; while (z < n && /[0-9.]/.test(code[z])) z++;
      push("num", code.slice(i, z)); i = z; continue;
    }
    out += esc(c); i++;
  }
  return out;
}

/* ---- rendering --------------------------------------------------------- */

function load(name, text) {
  if (cur === name) return;
  cur = name;
  var f = FILES[name] || (FILES[name] = { html: highlight(text), lines: text.split("\n").length });
  var gut = [];
  for (var i = 1; i <= f.lines; i++) gut.push(i);
  host.innerHTML =
    '<pre class="lgut">' + gut.join("\n") + "</pre>" +
    '<pre class="lsrc">' + f.html + "</pre>" +
    '<div class="bands"></div>';
  var g = host.querySelector(".lgut");
  lh = g.getBoundingClientRect().height / f.lines;     // measured, not assumed
  // `.bands` is inset from the pane's *padding box*, but line 1 begins after
  // the pane's top padding; without this the whole column reads a line high
  top0 = g.offsetTop;
}

function clear() {
  var b = host.querySelector(".bands");
  if (b) b.innerHTML = "";
}

/* ranges are 1-based inclusive line spans */
function show(ranges, focus) {
  var b = host.querySelector(".bands");
  if (!b || !lh) return;
  b.innerHTML = "";
  var first = null;
  ranges.forEach(function (r, i) {
    var el = document.createElement("div");
    el.className = "lband " + (i === focus ? "on" : "off");
    el.style.top = (top0 + (r.from - 1) * lh) + "px";
    el.style.height = ((r.to - r.from + 1) * lh) + "px";
    b.appendChild(el);
    if (i === focus || !first) first = el;
  });
  if (first) scrollTo(first);
}

function scrollTo(el) {
  var r = el.getBoundingClientRect(), s = scroller.getBoundingClientRect();
  var y = Math.max(0, scroller.scrollTop + (r.top - s.top) - scroller.clientHeight * 0.22);
  var near = Math.abs(y - scroller.scrollTop) < scroller.clientHeight * 2;
  scroller.scrollTo({ top: y, behavior: near ? "smooth" : "auto" });
}

window.LeanView = {
  init: function (hostEl, scrollEl, resolver) {
    host = hostEl; scroller = scrollEl; resolve = resolver;
  },
  load: load,
  show: show,
  clear: clear,
  /* the pane was given over to something else; re-render on the next load */
  forget: function () { cur = null; },
  file: function () { return cur; },
};

})();
