/* =========================================================================
   Interproof — the paper page, as the paper

   A continuous scroll of the compiled PDF.  Selecting an item scrolls to
   the rectangle synctex recorded for it and lays a highlight over it, so
   what you read is the typeset document, not a re-render of its source.

   Pages are rendered on demand and cached per scale; the placeholder holds
   its true aspect ratio from the start, so scroll position never jumps as
   neighbours come in.
   ========================================================================= */
(function () {
"use strict";

var lib = null;                 // the pdf.js module, imported once
var docs = {};                  // name -> { pdf, pages[], viewports[] }
var cur = null;                 // name of the loaded document
var scale = 1;                  // css px per pdf point
var fit = true;                 // track the pane width until the reader zooms
var host, scroller;             // .pdfpages, its scrolling ancestor
var onPick = null;              // called with a label when a PDF link is followed
var seq = 0;                    // load generation, so a stale load cannot paint

/* ---- pdf.js boot ------------------------------------------------------- */

function blobUrl(id, type) {
  var el = document.getElementById(id);
  return URL.createObjectURL(new Blob([el.textContent], { type: type }));
}

function boot() {
  if (lib) return Promise.resolve(lib);
  return import(blobUrl("pdfjs-lib", "text/javascript")).then(function (m) {
    var worker = blobUrl("pdfjs-worker", "text/javascript");
    // A blob: worker inherits the opaque `file://` origin and is refused, and
    // pdf.js hangs rather than falling back.  Served over http it is fine, so
    // ask for the real worker only where one can exist.
    if (location.protocol === "file:") {
      m.GlobalWorkerOptions.workerSrc = worker;      // main-thread fake worker
      m.GlobalWorkerOptions.workerPort = null;
    } else {
      m.GlobalWorkerOptions.workerPort = new Worker(worker, { type: "module" });
    }
    lib = m;
    return m;
  });
}

/* ---- page rendering ---------------------------------------------------- */

function fitScale(vp1) {
  var pad = 34;
  return Math.max(0.35, (scroller.clientWidth - pad * 2) / vp1.width);
}

function layout() {
  var d = docs[cur];
  if (!d) return;
  if (fit) scale = fitScale(d.viewports[0]);
  host.querySelectorAll(".pg").forEach(function (pg, i) {
    var vp = d.viewports[i];
    pg.style.width = Math.round(vp.width * scale) + "px";
    pg.style.height = Math.round(vp.height * scale) + "px";
    if (pg.dataset.scale && +pg.dataset.scale !== scale) draw(pg, i);
  });
}

function draw(pg, i) {
  var d = docs[cur], mine = seq;
  if (pg.dataset.busy === "1") return;
  pg.dataset.busy = "1";
  d.pdf.getPage(i + 1).then(function (page) {
    if (mine !== seq) return;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var vp = page.getViewport({ scale: scale * dpr });
    var cv = pg.querySelector("canvas") || pg.appendChild(document.createElement("canvas"));
    cv.width = Math.round(vp.width);
    cv.height = Math.round(vp.height);
    return page.render({ canvasContext: cv.getContext("2d"), viewport: vp }).promise
      .then(function () {
        if (mine !== seq) return;
        pg.dataset.scale = scale;
        pg.classList.add("ready");
        return links(page, pg);
      });
  }).catch(function () { /* a cancelled render is not an error worth showing */ })
    .then(function () { pg.dataset.busy = "0"; });
}

/* internal \Cref links, where the document was built with hyperref */
function links(page, pg) {
  if (pg.dataset.links === "1" || !onPick) return;
  pg.dataset.links = "1";
  return page.getAnnotations({ intent: "display" }).then(function (as) {
    var d = docs[cur];
    as.forEach(function (a) {
      if (a.subtype !== "Link" || !a.dest || !a.rect) return;
      var vp = d.viewports[pg.dataset.i];
      var r = vp.convertToViewportRectangle(a.rect);
      var el = document.createElement("a");
      el.className = "plink";
      el.dataset.dest = typeof a.dest === "string" ? a.dest : "";
      el.style.left = (Math.min(r[0], r[2]) / vp.width * 100) + "%";
      el.style.top = (Math.min(r[1], r[3]) / vp.height * 100) + "%";
      el.style.width = (Math.abs(r[2] - r[0]) / vp.width * 100) + "%";
      el.style.height = (Math.abs(r[3] - r[1]) / vp.height * 100) + "%";
      el.onclick = function (ev) { ev.preventDefault(); jump(a.dest); };
      pg.appendChild(el);
    });
  }).catch(function () {});
}

/* a PDF destination -> { key, page, y }; key is null for a section or equation */
function resolve(dest) {
  var d = docs[cur];
  var p = typeof dest === "string" ? d.pdf.getDestination(dest) : Promise.resolve(dest);
  return Promise.resolve(p).then(function (ex) {
    if (!ex) return null;
    return d.pdf.getPageIndex(ex[0]).then(function (idx) {
      var page = idx + 1, h = d.viewports[idx].height;
      var y = h - (typeof ex[3] === "number" ? ex[3] : 0);
      // hyperref anchors a destination at the paragraph break just *above* the
      // block, so the item starting right below the anchor is the match.
      // Containment is only the fallback: an item continuing onto this page
      // spans it from the top edge and would otherwise swallow every anchor.
      var near = null, gap = 44, holds = null;
      (d.items || []).forEach(function (e) {
        var r = e.rect;
        if (!r || r.page > page || r.end_page < page) return;
        if (r.page === page && r.top >= y - 8 && r.top - y < gap) {
          gap = r.top - y; near = e.key;
        }
        var top = r.page === page ? r.top : 0;
        var bot = r.end_page === page ? r.bottom : h;
        if (y >= top - 6 && y <= bot + 6) holds = e.key;
      });
      return { key: near || holds, page: page, y: y };
    });
  }).catch(function () { return null; });
}

/* follow an internal link: name the item if there is one, else just go there */
function jump(dest) {
  return resolve(dest).then(function (hit) {
    if (!hit) return;
    if (hit.key && onPick) return onPick(hit.key);
    var pg = host.querySelector('.pg[data-i="' + (hit.page - 1) + '"]');
    if (!pg) return;
    var probe = document.createElement("div");
    probe.style.cssText = "position:absolute;left:0;width:1px;height:1px;top:" +
      (hit.y / docs[cur].viewports[hit.page - 1].height * 100) + "%";
    pg.appendChild(probe);
    scrollTo(probe);
    probe.remove();
  });
}

/* ---- loading ----------------------------------------------------------- */

var io = null;

function observe() {
  if (io) io.disconnect();
  io = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      var pg = e.target;
      if (!pg.dataset.scale) draw(pg, +pg.dataset.i);
    });
  }, { root: scroller, rootMargin: "220% 0px" });
  host.querySelectorAll(".pg").forEach(function (pg) { io.observe(pg); });
}

function load(name, url, items) {
  if (cur === name) { docs[cur].items = items; return Promise.resolve(); }
  var mine = ++seq;
  return boot().then(function (m) {
    if (docs[name]) return docs[name];
    var bytes = Uint8Array.from(atob(url), function (c) { return c.charCodeAt(0); });
    return m.getDocument({ data: bytes }).promise.then(function (pdf) {
      var jobs = [];
      for (var i = 1; i <= pdf.numPages; i++) jobs.push(pdf.getPage(i));
      return Promise.all(jobs).then(function (pages) {
        docs[name] = {
          pdf: pdf,
          viewports: pages.map(function (p) { return p.getViewport({ scale: 1 }); }),
        };
        return docs[name];
      });
    });
  }).then(function (d) {
    if (mine !== seq) return;
    cur = name;
    d.items = items;
    host.innerHTML = d.viewports.map(function (_, i) {
      return '<div class="pg" data-i="' + i + '"><div class="pn">' + (i + 1) + "</div></div>";
    }).join("");
    layout();
    observe();
  });
}

/* ---- marking and scrolling --------------------------------------------- */

function clear() {
  host.querySelectorAll(".mark").forEach(function (el) { el.remove(); });
}

/* one band per page the item spans */
function band(rect, cls) {
  var d = docs[cur], out = [];
  for (var p = rect.page; p <= rect.end_page; p++) {
    var pg = host.querySelector('.pg[data-i="' + (p - 1) + '"]');
    if (!pg) continue;
    var vp = d.viewports[p - 1];
    var top = p === rect.page ? rect.top : 0;
    var bot = p === rect.end_page ? rect.bottom : vp.height;
    var el = document.createElement("div");
    el.className = "mark " + cls;
    el.style.left = ((rect.x - 7) / vp.width * 100) + "%";
    el.style.width = ((rect.w + 14) / vp.width * 100) + "%";
    el.style.top = ((top - 4) / vp.height * 100) + "%";
    el.style.height = ((bot - top + 8) / vp.height * 100) + "%";
    pg.appendChild(el);
    out.push(el);
  }
  return out;
}

function show(rects, focus) {
  if (!cur) return;
  clear();
  var first = null;
  rects.forEach(function (r, i) {
    var els = band(r, i === focus ? "on" : "off");
    if (els[0] && (i === focus || !first)) first = els[0];
    // the page being jumped to is drawn outright; waiting for the observer to
    // notice it would show the reader a blank sheet at the moment of arrival
    for (var p = r.page; p <= r.end_page; p++) {
      var pg = host.querySelector('.pg[data-i="' + (p - 1) + '"]');
      if (pg && !pg.dataset.scale) draw(pg, p - 1);
    }
  });
  if (first) scrollTo(first);
}

function scrollTo(el) {
  // measured, not accumulated: the page's offsetParent is the pane, not the
  // scrolling box, so offsetTop would be off by the header
  var r = el.getBoundingClientRect(), s = scroller.getBoundingClientRect();
  var y = Math.max(0, scroller.scrollTop + (r.top - s.top) - scroller.clientHeight * 0.16);
  // gliding is orientation when the target is nearby and a long blur when it
  // is nine pages away
  var near = Math.abs(y - scroller.scrollTop) < scroller.clientHeight * 2;
  scroller.scrollTo({ top: y, behavior: near ? "smooth" : "auto" });
}

/* ---- api --------------------------------------------------------------- */

var resizeT = null;
window.addEventListener("resize", function () {
  clearTimeout(resizeT);
  resizeT = setTimeout(function () { if (fit) layout(); }, 160);
});

window.PDFView = {
  init: function (hostEl, scrollEl, pick) { host = hostEl; scroller = scrollEl; onPick = pick; },
  load: load,
  show: show,
  clear: clear,
  zoom: function (mult) {
    if (!cur) return;
    fit = false;
    scale = Math.max(0.4, Math.min(3, scale * mult));
    layout();
  },
  refit: function () { fit = true; layout(); },
  resolve: resolve,
  scale: function () { return scale; },
  doc: function () { return cur; },
};

})();
