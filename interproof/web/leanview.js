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

   ---------------------------------------------------------------------------
   Two ways to know what a name is, and the pane reads whichever it was given.

   *The overlay.*  When the build elaborated the formalization, every module
   arrives with a token list: where each token is, what Lean's own grammar
   calls it, the type or signature it has, the constant it refers to and the
   identity it shares with its other occurrences.  Then the colouring is
   Lean's, a hover is the elaborated type, and a jump goes where the compiler
   says the name was defined.

   *The source.*  With no overlay this file falls back to what it always did —
   a tokenizer, and names matched against the declarations this build parsed.
   A hover then shows the signature *as written*, which is a weaker claim
   honestly made, and a jump follows a name match, which can be wrong in the
   same way `uses` can be wrong.  Both paths render the same DOM, so
   everything below the renderer is written once.
   ========================================================================= */
(function () {
"use strict";

var FILES = {};                 // name -> { text, html, lines, sem }
var cur = null, shown = null, lh = 0, top0 = 0;  // what is drawn, and its metrics
var host, scroller, api = {};   // #leanpane, its scrolling ancestor, the lookups
var SEM = null;                 // the overlay of the file on screen, if any
var BIND = [];                  // occurrence identities, interned per file

var KW = new Set(("theorem lemma def abbrev instance structure inductive class deriving " +
  "where by fun let have show from calc match with do if then else at " +
  "namespace end section variable variables open universe noncomputable private protected " +
  "partial unsafe scoped local attribute set_option import example mutual return " +
  "exact apply intro intros refine rintro rcases obtain cases induction constructor " +
  "simp simpa rw rwa subst omega ring linarith nlinarith norm_num positivity decide " +
  "rfl trivial exists use ext funext congr gcongr push_cast field_simp " +
  "unfold dsimp change conv first all_goals any_goals repeat try focus " +
  "classical fin_cases interval_cases specialize contrapose by_cases by_contra " +
  "left right infer_instance assumption").split(/\s+/));

var IDCH = /[A-Za-z0-9_'!?À-ɏͰ-Ͽᴀ-ᵿ₀-ₜ℀-⅏\ud835]/;

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function attr(s) { return esc(String(s)).replace(/"/g, "&quot;"); }

/* citations inside comments become links, in either the label or `Doc:label` form */
function cite(text) {
  return text.replace(/\b(thm|lem|def|prop|cor|rem|sec|sub|app):([A-Za-z0-9][A-Za-z0-9\-_]*)/g,
    function (whole, kind, name) {
      var lbl = kind + ":" + name.replace(/\.$/, "");
      var cm = lbl.match(/^(.*)\.(\d+)$/);
      if (cm) lbl = cm[1];
      var key = api.label && api.label(lbl);
      return key ? '<span class="citec" data-go="' + attr(key) + '">' + whole + "</span>" : whole;
    });
}

/* A docstring is prose with code in it, and Lean writes that code in
   backticks.  Only the backticks are read: a docstring is shown in a card a
   few lines tall, and the rest of Markdown would be a renderer this page does
   not need to carry. */
function ticks(text) {
  return text.replace(/`([^`\n]+)`/g, '<code>$1</code>');
}

/* =========================================================================
   the source path — a tokenizer, and names matched against this build
   ========================================================================= */

/* A tokenizer, not a parser: enough to tell comment from code from binder.
   Spans are closed at every newline so the result can be split into lines. */
function highlight(code, mod) {
  var out = "", i = 0, n = code.length;
  function push(cls, txt, extra) {
    out += txt.split("\n").map(function (t) {
      return t ? '<span class="' + cls + '"' + (extra || "") + ">" + t + "</span>" : "";
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
      } else {
        /* The one thing the source path can still answer: is this the name of
           something this build parsed?  It is a name match and it is wrong in
           the ways a name match is wrong — a local binder shadowing a lemma
           reads as the lemma — which is why the card it opens shows the
           declaration *as written* rather than claiming a type. */
        var key = api.decl && api.decl(w, mod);
        if (key) push("ref", esc(w), ' data-def="' + attr(key) + '"');
        else out += esc(w);
      }
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

/* =========================================================================
   the elaborated path — the overlay, rendered
   ========================================================================= */

/* The overlay is a flat run of `line, col, len, attr`, in source order, with
   columns and lengths in UTF-16 units — which is what a JavaScript string is
   indexed in, so nothing here has to measure anything.  It is flat because it
   is the one part of a manifest that grows with the size of the
   formalization; four numbers a token rather than an object a token is the
   difference between a page that inlines and one that does not. */

/* A token may cover several lines — a block comment is one token — and the
   pane is rendered a line at a time, so the run is first cut at the line
   boundaries.  The pieces of one token keep its index, so hovering any of
   them still finds the whole. */
function pieces(lines, sem) {
  var by = [], t = sem.toks || [];
  for (var i = 0; i < t.length; i += 4) {
    var ln = t[i], col = t[i + 1], len = t[i + 2], a = t[i + 3];
    while (len > 0 && ln >= 1 && ln <= lines.length) {
      var take = Math.min(len, Math.max(0, lines[ln - 1].length - col));
      if (take > 0) (by[ln] = by[ln] || []).push([col, take, a, i]);
      len -= take + 1;                 // the newline this line ends with
      ln++;
      col = 0;
    }
  }
  return by;
}

/* Every class SubVerso gives a token is kept as it gives it — a stylesheet
   written for Verso's output styles this pane too — and the ones this reader
   adds say what it can *do* with the token rather than what it is. */
function tokenHTML(src, col, len, a, id, sem) {
  var at = sem.attrs[a] || {};
  var body = esc(src.slice(col, col + len));
  var cls = at.c || "unknown";
  var extra = ' data-t="' + id + '"';

  if (cls.indexOf("comment") >= 0 || cls === "doc-comment") body = cite(body);
  if (at.b) {
    var b = BIND.indexOf(at.b);
    if (b < 0) { BIND.push(at.b); b = BIND.length - 1; }
    extra += ' data-b="' + b + '"';
  }
  if (at.h || at.d) extra += ' data-i="' + a + '"';
  var key = at.n && api.full && api.full(at.n);
  if (key && !at.def) { cls += " ref"; extra += ' data-def="' + attr(key) + '"'; }
  else if (at.def) cls += " isdef";

  return '<span class="' + attr(cls) + '"' + extra + ">" + body + "</span>";
}

function renderSem(lines, sem) {
  var by = pieces(lines, sem), out = [];
  for (var ln = 1; ln <= lines.length; ln++) {
    var src = lines[ln - 1], row = by[ln], at = 0, buf = "";
    if (row) {
      row.sort(function (x, y) { return x[0] - y[0]; });
      for (var k = 0; k < row.length; k++) {
        var col = row[k][0], len = row[k][1];
        // a token the previous one already covered: the first one wins, which
        // keeps a stray overlap from duplicating the text of the line
        if (col < at) continue;
        buf += esc(src.slice(at, col));
        buf += tokenHTML(src, col, len, row[k][2], row[k][3], sem);
        at = col + len;
      }
    }
    out.push(buf + esc(src.slice(at)));
  }
  return out.join("\n");
}

/* =========================================================================
   the card
   ========================================================================= */

/* Fixed to the viewport rather than placed in the pane: the pane scrolls and
   clips, and a card that scrolls with the text it describes is a card that
   leaves the screen while you are reading it.

   It is deliberately not a tooltip.  A signature is several lines of code, a
   docstring is prose, and both are things a reader wants to select and copy —
   so the pointer may enter the card, and it closes on leaving rather than on
   any movement at all. */

var card = null, showT = null, hideT = null, held = null;

function cardEl() {
  if (!card) {
    card = document.createElement("div");
    card.className = "hcard";
    card.hidden = true;
    card.addEventListener("mouseenter", function () { clearTimeout(hideT); });
    card.addEventListener("mouseleave", schedHide);
    card.addEventListener("click", function (ev) {
      var el = ev.target.closest("[data-go],[data-def]");
      if (!el) return;
      ev.stopPropagation();
      hideCard();
      if (el.dataset.go && api.label) api.go(el.dataset.go);
      else if (el.dataset.def) api.go(el.dataset.def);
    });
    document.body.appendChild(card);
  }
  return card;
}

/* what a hover has to say about one token, from whichever side knows */
function cardHTML(el) {
  var h = "", sig = "", doc = "", where = "", key = el.dataset.def || "";

  if (SEM && el.dataset.i !== undefined) {
    var at = SEM.attrs[+el.dataset.i] || {};
    sig = at.h || "";
    doc = at.d || "";
  }
  if (!sig && !doc && key && api.info) {
    /* the source path, and the honest wording for it: this is the declaration
       as it is written in the module, not a type anything computed */
    var d = api.info(key);
    if (d) {
      sig = d.signature || (d.kind + " " + d.name);
      doc = d.doc || "";
    }
  }
  if (key && api.info) {
    var t = api.info(key);
    if (t) where = t.file + ".lean:" + t.line;
  }

  if (!sig && !doc && !where) return "";
  if (sig) h += '<pre class="hsig">' + esc(sig) + "</pre>";
  if (doc) h += '<div class="hdoc">' + cite(ticks(esc(doc))) + "</div>";
  if (where) {
    h += '<div class="hwhere" data-def="' + attr(key) + '">' + esc(where) + "</div>";
  }
  return h;
}

function showCard(el) {
  var h = cardHTML(el);
  if (!h) return;
  var c = cardEl();
  c.innerHTML = h;
  c.hidden = false;
  held = el;

  /* below the token, and above it when there is no room below — the same
     rule an editor uses, for the same reason */
  var r = el.getBoundingClientRect();
  c.style.left = "0px"; c.style.top = "0px";
  var w = c.offsetWidth, hh = c.offsetHeight;
  var left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
  var top = (r.bottom + hh + 10 <= window.innerHeight)
    ? r.bottom + 6
    : Math.max(8, r.top - hh - 6);
  c.style.left = left + "px";
  c.style.top = top + "px";
}

function hideCard() {
  clearTimeout(showT); clearTimeout(hideT);
  held = null;
  if (card) { card.hidden = true; card.innerHTML = ""; }
}

function schedHide() {
  clearTimeout(hideT);
  hideT = setTimeout(hideCard, 220);
}

/* =========================================================================
   what the pointer is on
   ========================================================================= */

/* Every occurrence of the thing under the pointer, marked at once.  It is the
   question an editor answers with the same gesture, and it is the one a
   reader of an unfamiliar proof asks constantly: this `h` — is it the
   hypothesis from four lines up, or a different binder with the same name? */
function markOccurrences(b) {
  var src = host && host.querySelector(".lsrc");
  if (!src) return;
  src.querySelectorAll(".occ").forEach(function (e) { e.classList.remove("occ"); });
  if (b === undefined || b === null) return;
  src.querySelectorAll('[data-b="' + b + '"]').forEach(function (e) {
    e.classList.add("occ");
  });
}

function wire() {
  var src = host.querySelector(".lsrc");
  if (!src) return;

  src.addEventListener("mouseover", function (ev) {
    var el = ev.target.closest("[data-t],[data-def]");
    if (!el) return;
    markOccurrences(el.dataset.b);
    if (el === held) { clearTimeout(hideT); return; }
    clearTimeout(showT); clearTimeout(hideT);
    // the same wait an editor uses: long enough that crossing the file does
    // not flash a card per token, short enough to feel like an answer
    showT = setTimeout(function () { showCard(el); }, 320);
  });

  src.addEventListener("mouseout", function (ev) {
    var el = ev.target.closest("[data-t],[data-def]");
    if (!el) return;
    clearTimeout(showT);
    if (!ev.relatedTarget || !ev.relatedTarget.closest || !ev.relatedTarget.closest(".lsrc")) {
      markOccurrences(null);
    }
    if (held) schedHide();
  });

  src.addEventListener("click", function (ev) {
    var el = ev.target.closest("[data-go],[data-def]");
    if (!el) return;
    // a click that ended a selection is a copy, not a navigation
    var sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    ev.preventDefault();
    ev.stopPropagation();
    hideCard();
    if (el.dataset.go) api.go(el.dataset.go);
    else if (el.dataset.def) api.go(el.dataset.def);
  });
}

/* ---- rendering --------------------------------------------------------- */

function load(name, text, sem) {
  sem = sem || null;
  var f = FILES[name];
  /* Keyed on what was rendered, not on the module's name.  Two things move
     under a cache keyed by name alone: a live session replaces the manifest
     whole, so the text may be newer than the render; and a build may have
     gained or lost its overlay, so the same text may have to be drawn a
     different way.  Both show up as a pane that answers with the old page. */
  if (!f || f.text !== text || f.sem !== sem) {
    BIND = [];
    var rich = !!(sem && sem.toks && sem.toks.length);
    var html = rich ? renderSem(text.split("\n"), sem) : highlight(text, name);
    f = FILES[name] = { text: text, sem: sem, rich: rich, bind: BIND,
                        html: html, lines: text.split("\n").length };
  }
  if (cur === name && shown === f && host.querySelector(".lsrc")) return;
  cur = name;
  shown = f;
  SEM = f.sem;
  BIND = f.bind;
  var gut = [];
  for (var i = 1; i <= f.lines; i++) gut.push(i);
  host.innerHTML =
    '<pre class="lgut">' + gut.join("\n") + "</pre>" +
    '<pre class="lsrc' + (f.rich ? " sem" : "") + '">' + f.html + "</pre>" +
    '<div class="bands"></div>';
  var g = host.querySelector(".lgut");
  lh = g.getBoundingClientRect().height / f.lines;     // measured, not assumed
  // `.bands` is inset from the pane's *padding box*, but line 1 begins after
  // the pane's top padding; without this the whole column reads a line high
  top0 = g.offsetTop;
  hideCard();
  wire();
}

function clear() {
  var b = host.querySelector(".bands");
  if (b) b.innerHTML = "";
}

/* ranges are 1-based inclusive line spans; `on` is the one being read, and
   there may be more than one of them — a citation in module prose can name the
   same item from two separate blocks */
function show(ranges) {
  var b = host.querySelector(".bands");
  if (!b || !lh) return;
  b.innerHTML = "";
  var first = null;
  ranges.forEach(function (r) {
    var el = document.createElement("div");
    el.className = "lband " + (r.on ? "on" : "off");
    el.style.top = (top0 + (r.from - 1) * lh) + "px";
    el.style.height = ((r.to - r.from + 1) * lh) + "px";
    b.appendChild(el);
    if (r.on && !first) first = el;
  });
  if (!first) first = b.firstChild;
  if (first) scrollTo(first);
}

function scrollTo(el) {
  var r = el.getBoundingClientRect(), s = scroller.getBoundingClientRect();
  var y = Math.max(0, scroller.scrollTop + (r.top - s.top) - scroller.clientHeight * 0.22);
  var near = Math.abs(y - scroller.scrollTop) < scroller.clientHeight * 2;
  scroller.scrollTo({ top: y, behavior: near ? "smooth" : "auto" });
}

window.LeanView = {
  /* `opts` is every question this pane can ask of the build: how to resolve a
     citation, a written name and a fully qualified one, what a declaration
     says, and where to go when one is picked. */
  init: function (hostEl, scrollEl, opts) {
    host = hostEl; scroller = scrollEl;
    api = opts || {};
    if (!api.go) api.go = function () {};
    scrollEl.addEventListener("scroll", hideCard, { passive: true });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && card && !card.hidden) hideCard();
    });
  },
  load: load,
  show: show,
  clear: clear,
  top: function () { scroller.scrollTo({ top: 0 }); },
  /* the pane was given over to something else; re-render on the next load */
  forget: function () { cur = null; shown = null; hideCard(); },
  file: function () { return cur; },
};

})();
