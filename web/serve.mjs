// Serve web/dist the way GitHub Pages does, for trying the site and for the tests.
//
//   node serve.mjs [--port 8000] [--dir dist]
//
// The site appears at http://localhost:PORT/vms-lse-pascal/ with no special
// headers, like Pages, so the cross-origin-isolation service worker is used
// exactly as on the live site.

import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const port = Number(opt("--port", process.env.PORT || 8000));
const root = resolve(opt("--dir", new URL("./dist", import.meta.url).pathname));
const base = "/vms-lse-pascal/";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
  ".zip": "application/zip",
  ".woff2": "font/woff2",
};

createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/" || url.pathname === base.slice(0, -1)) {
    res.writeHead(301, { Location: base });
    res.end();
    return;
  }
  if (!url.pathname.startsWith(base)) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  let rel = decodeURIComponent(url.pathname.slice(base.length)) || "index.html";
  if (rel.endsWith("/")) rel += "index.html";
  const file = normalize(join(root, rel));
  let stat;
  try {
    stat = file.startsWith(root) ? statSync(file) : null;
  } catch {
    stat = null;
  }
  if (!stat || !stat.isFile()) {
    res.writeHead(404);
    res.end("not found");
    return;
  }
  // Pages answers a reload's revalidation with 304 Not Modified.
  const etag = `"${Math.floor(stat.mtimeMs).toString(16)}-${stat.size.toString(16)}"`;
  const lastModified = new Date(Math.floor(stat.mtimeMs / 1000) * 1000).toUTCString();
  const cache = { ETag: etag, "Last-Modified": lastModified, "Cache-Control": "max-age=600" };
  const since = Date.parse(req.headers["if-modified-since"] || "");
  const fresh = req.headers["if-none-match"]
    ? req.headers["if-none-match"].split(",").some((tag) => tag.trim() === etag)
    : since >= Date.parse(lastModified);
  if (fresh) {
    res.writeHead(304, cache);
    res.end();
    return;
  }
  res.writeHead(200, {
    "Content-Type": TYPES[extname(file)] || "application/octet-stream",
    "Content-Length": stat.size,
    ...cache,
  });
  createReadStream(file).pipe(res);
}).listen(port, () => {
  console.log(`LSE web: http://localhost:${port}${base}`);
});
