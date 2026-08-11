/* =========================================================================
   Interproof — the archive

   The page hands back everything it was made from: the compiled documents,
   the LaTeX and the Lean they were compiled from, the correspondence between
   them, the configuration that describes the project, and the viewer itself.
   A reader who was sent a link keeps a working copy of the whole thing; an
   author who lost the build tree can rebuild it.

   The zip is written here rather than asked of a server, because in the
   static build there is no server, and in the live build there is one that
   need not exist tomorrow.
   ========================================================================= */
(function () {
"use strict";

/* ---- zip, stored ------------------------------------------------------- */

/* Method 0, no deflate.  What goes in is PDFs, which are already compressed,
   and text, which is a few hundred kilobytes against several megabytes of
   them: compressing would move the total by a percent or two, and the price
   is a compression library in a page that has no build step.

   Every entry takes the same DOS timestamp — 1980-01-01 00:00, the earliest
   the format can express.  The archive is then a function of the build alone,
   so the same build downloaded twice is byte for byte the same file, and two
   archives can be compared with `cmp`.  What is lost is the moment of
   download, which the manifest inside dates better anyway. */

var DOS_DATE = 0x21, DOS_TIME = 0;      // 1980-01-01, 00:00:00
var UTF8_NAME = 0x0800;                 // general purpose bit 11
var VERSION = 20;                       // 2.0: the floor for a stored entry

var CRCT = null;
function crcTable() {
  if (CRCT) return CRCT;
  CRCT = new Uint32Array(256);
  for (var n = 0; n < 256; n++) {
    var c = n;
    for (var k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    CRCT[n] = c >>> 0;
  }
  return CRCT;
}

function crc32(bytes) {
  var t = crcTable(), c = 0xffffffff;
  for (var i = 0; i < bytes.length; i++) c = t[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

var enc = new TextEncoder();
function bytes(s) { return enc.encode(s); }
function unb64(s) { return Uint8Array.from(atob(s), function (c) { return c.charCodeAt(0); }); }

/* files: [{ name, data: Uint8Array }], written in the order given.

   Sizes and offsets are laid out before a byte is written, because every one
   of them appears twice — once in the local header and once in the central
   directory — and an extractor believes the directory.  Computing the layout
   first is what keeps the two from being able to disagree. */
function zip(files) {
  var LOCAL = 30, CENTRAL = 46, EOCD = 22;
  var recs = files.map(function (f) {
    var name = bytes(f.name);
    return { name: name, data: f.data, crc: crc32(f.data), off: 0 };
  });
  var body = 0, dir = 0;
  recs.forEach(function (r) {
    r.off = body;
    body += LOCAL + r.name.length + r.data.length;
    dir += CENTRAL + r.name.length;
  });
  // zip64 is a second set of headers for the same fields; nothing this viewer
  // packs approaches four gigabytes, so the limit is refused rather than met
  if (body + dir + EOCD > 0xfffffffe) throw new Error("archive too large for zip32");

  var buf = new Uint8Array(body + dir + EOCD);
  var view = new DataView(buf.buffer);
  var p = 0;
  function u16(v) { view.setUint16(p, v, true); p += 2; }
  function u32(v) { view.setUint32(p, v >>> 0, true); p += 4; }
  function raw(b) { buf.set(b, p); p += b.length; }

  recs.forEach(function (r) {
    u32(0x04034b50); u16(VERSION); u16(UTF8_NAME); u16(0);
    u16(DOS_TIME); u16(DOS_DATE);
    u32(r.crc); u32(r.data.length); u32(r.data.length);
    u16(r.name.length); u16(0);
    raw(r.name); raw(r.data);
  });

  var cdAt = p;
  recs.forEach(function (r) {
    u32(0x02014b50); u16(VERSION); u16(VERSION); u16(UTF8_NAME); u16(0);
    u16(DOS_TIME); u16(DOS_DATE);
    u32(r.crc); u32(r.data.length); u32(r.data.length);
    u16(r.name.length); u16(0); u16(0);      // name, extra, comment
    u16(0); u16(0); u32(0);                  // disk, internal attrs, external attrs
    u32(r.off);
    raw(r.name);
  });
  var cdSize = p - cdAt;

  u32(0x06054b50); u16(0); u16(0);
  u16(recs.length); u16(recs.length);
  u32(cdSize); u32(cdAt); u16(0);
  return new Blob([buf], { type: "application/zip" });
}

/* ---- what goes in ------------------------------------------------------ */

/* An entry name is a path someone will extract onto their disk.  Manifest
   paths are already relative to the project root, so this is a guard against
   one being absolute or reaching upwards, not a translation. */
function safe(path) {
  return String(path).split("/").filter(function (s) {
    return s && s !== "." && s !== "..";
  }).join("/");
}

/* Two entries under one name is legal and unreadable: extractors disagree
   about which of them wins, and some refuse the archive outright.  The first
   is kept, so the order the archive is assembled in decides. */
function dedupe(files) {
  var seen = {};
  return files.filter(function (f) {
    if (!f.name || seen[f.name]) return false;
    seen[f.name] = 1;
    return true;
  });
}

function slug(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 60) || "interproof";
}

/* The project's name, for the file the reader ends up with.  The manifest
   carries it; the page's own title is the fallback, because the template puts
   the same name there and a build old enough to lack the field still has it. */
function title(ctx) {
  var M = (ctx.manifest && ctx.manifest()) || {};
  var p = M.project || {};
  return p.title || M.title ||
    ((document.title || "").split("—").pop() || "").trim() || "interproof";
}

/* Everything the viewer wrote into the page after it loaded: the panes it
   rendered, the state a button is in, the sheet somebody left open.  None of
   it belongs in an archive — the DOM is a session, and what is being packed is
   a document. */
var TRANSIENT = ["#railbody", "#rhead", "#vhead", "#leanpane", "#pdfpages",
                 "#note", "#stats", "#helpbody", "#live"];

/* The page itself, so the archive opens as a page and not as a data dump.
   A static build is already whole in the DOM — the PDFs included, as base64 —
   and its own markup is the shortest way back to it.  A live build is a
   template a server filled in, so the server is asked for it again.

   The DOM is taken as a clone with the session wiped off it.  Serialising it
   as it stands captures the moment of the click: the download button frozen
   mid-word, a half-scrolled document, whatever was selected.  The page it
   reopens as would then be a screenshot of somebody else's reading. */
function page(ctx) {
  if (ctx.boot && ctx.boot.mode === "live") {
    return fetch("./").then(function (r) {
      if (!r.ok) throw new Error("index — " + r.status + " " + r.statusText);
      return r.text();
    });
  }
  var root = document.documentElement.cloneNode(true);
  TRANSIENT.forEach(function (sel) {
    var el = root.querySelector(sel);
    if (el) el.innerHTML = "";
  });
  var help = root.querySelector("#help");
  if (help) help.setAttribute("hidden", "");
  root.querySelectorAll("button").forEach(function (b) {
    b.classList.remove("on");
    b.disabled = false;
  });
  var dl = root.querySelector("#dlbtn");
  if (dl) dl.textContent = "Download";
  var q = root.querySelector("#search");
  if (q) q.removeAttribute("value");
  root.querySelectorAll(".modes button").forEach(function (b, i) {
    if (i === 0) b.classList.add("on");           // the mode the page opens in
  });
  return Promise.resolve("<!doctype html>\n" + root.outerHTML);
}

function readme(ctx) {
  var M = ctx.manifest() || {};
  var live = !!(ctx.boot && ctx.boot.mode === "live");
  var docs = (M.docs || []).map(function (d) {
    return "  - `pdf/" + d.id + ".pdf` — " + (d.title || d.id) +
           (d.main ? ", compiled from `sources/" + d.main + "`" : "");
  }).join("\n");

  var open = live
    ? ["`index.html` reads `manifest.json` and `pdf/` from the directory beside it, so",
       "the directory has to be served rather than opened: a browser refuses to fetch a",
       "sibling file over `file://`.  Anything will do —",
       "",
       "    python3 -m http.server",
       "",
       "and open the address it prints.  The rebuild stream this page came from is not",
       "in the archive; the viewer will say `offline` in the top bar and stay readable."
      ].join("\n")
    : ["Open `index.html` in a browser.  It carries the manifest, the documents and the",
       "viewer inside itself and asks the network for nothing, so it works from a file",
       "system, from a memory stick, or from behind whatever a corporate proxy is doing."
      ].join("\n");

  var absent = (M.assets || []).filter(function (a) { return !a.b64; })
    .map(function (a) { return "- `sources/" + a.path + "`"; });
  var gap = absent.length ? [
    "",
    "## What is not here",
    "",
    "The page carried what it could.  These files the documents include were too",
    "large for it, and a rebuild needs them put back where the paths say:",
    "",
    absent.join("\n"),
  ].join("\n") : "";

  return [
    "# " + title(ctx) + " — an Interproof archive",
    "",
    "A paper and its Lean formalization, read side by side, together with",
    "everything the pairing was computed from.",
    "",
    "## Reading it",
    "",
    open,
    "",
    "## What is here",
    "",
    "- `index.html` — the viewer.",
    "- `manifest.json` — the correspondence itself: every labelled statement in the",
    "  documents, every declaration in the Lean sources, and every citation that ties",
    "  one to the other, with the page rectangles and line spans they occupy.",
    "- `pdf/` — the compiled documents.",
    docs,
    "- `sources/` — the LaTeX and the Lean the build ran on, laid out exactly as they",
    "  sit in the project" + (M.lean_root ? "; the Lean root is `sources/" + M.lean_root + "`" : "") + ".",
    "- `interproof.toml` — the configuration: which documents there are, where their",
    "  sources are, and which directory holds the formalization.",
    gap,
    "",
    "## Rebuilding it",
    "",
    "The archive is a project, not a report.  The configuration names paths relative",
    "to the project root, and `sources/` is that root, so it goes back in there:",
    "",
    "    cp interproof.toml sources/",
    "    cd sources",
    "    interproof build",
    "",
    "That recompiles the documents with latexmk, re-reads the Lean, and writes this",
    "page again.  A TeX installation is what it needs; nothing here depends on the",
    "machine the archive was made on.",
    "",
  ].join("\n");
}

/* ---- api --------------------------------------------------------------- */

/* `ctx` is the viewer's bridge — { boot, manifest(), pdfBytes(id) }.  It is
   an argument rather than a global read so that the packer can be run, and
   the archive it writes opened by a real unzip, outside a browser. */
function build(ctx, onprogress) {
  ctx = ctx || window.Interproof;
  var M = ctx && ctx.manifest && ctx.manifest();
  if (!M) return Promise.reject(new Error("the manifest has not been read yet"));

  var ids = (M.docs || []).map(function (d) { return d.id; });
  var total = ids.length + 1, n = 0;
  function step(v) { n++; if (onprogress) onprogress(n, total); return v; }

  var jobs = [page(ctx).then(step)].concat(ids.map(function (id) {
    return ctx.pdfBytes(id).then(step);
  }));

  // one document missing is a broken archive, not a smaller one: it fails
  // here, where the reader is still looking at the button they pressed
  return Promise.all(jobs).then(function (got) {
    var out = [
      { name: "README.md", data: bytes(readme(ctx)) },
      { name: "index.html", data: bytes(got[0]) },
      { name: "manifest.json", data: bytes(JSON.stringify(M)) },
    ];
    if (M.config) out.push({ name: "interproof.toml", data: bytes(M.config) });
    ids.forEach(function (id, i) {
      out.push({ name: "pdf/" + safe(id) + ".pdf", data: got[i + 1] });
    });
    (M.sources || []).forEach(function (s) {
      out.push({ name: safe("sources/" + s.path), data: bytes(s.text || "") });
    });
    /* Figures and the like.  The page carries the small ones and only names
       the ones it declined to carry, so the archive hands back what it was
       given and the README says what is missing — a `sources/` that will not
       compile for want of a plot has to say so somewhere. */
    (M.assets || []).forEach(function (a) {
      if (a.b64) out.push({ name: safe("sources/" + a.path), data: unb64(a.b64) });
    });
    /* The Lean modules are keyed by their path under the Lean root, and the
       root is itself a path under the project root: the archive puts them
       back where the configuration expects to find them, or a rebuild would
       have to be told a new layout. */
    var root = safe(M.lean_root || "lean");
    (M.lean || []).forEach(function (f) {
      var rel = f.path || (f.name + ".lean");
      out.push({ name: safe("sources/" + root + "/" + rel), data: bytes(f.text || "") });
    });
    return zip(dedupe(out));
  });
}

window.Download = {
  build: build,
  filename: function (ctx) { return slug(title(ctx || window.Interproof)) + "-interproof.zip"; },
};

})();
