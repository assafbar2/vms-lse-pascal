// Runs LSE (Python, in Pyodide) off the page's main thread.
//
// Keys reach this worker through a SharedArrayBuffer ring when the page is
// cross-origin isolated, so a running Pascal program can wait in READLN
// (Atomics.wait) the way it waits for a terminal. Without
// SharedArrayBuffer, keys arrive as messages and READLN sees end of input.
//
// Ring layout (written by main.js): ctrl[0] = units written, ctrl[1] =
// units read. Each key chunk is a header -(1 + ms since the previous chunk)
// followed by its UTF-16 code units. A header with no units only wakes the
// worker (used for Ctrl-C while a program runs).

import { loadPyodide } from "./vendor/pyodide/pyodide.mjs";

const BUILD_ID = "__BUILD_ID__";
const HOME = "/home/lse";
const APP_DIR = "/app";

let py = null;
let session = null;
let ring = null;
let interruptBuffer = null;
let timer = 0;
let syncTimer = 0;
let syncing = false;
let syncAgain = false;
let persistent = false;

function post(type, fields = {}) {
  self.postMessage({ type, ...fields });
}

function readRing(timeoutMs) {
  const { ctrl, data } = ring;
  let w = Atomics.load(ctrl, 0);
  let r = Atomics.load(ctrl, 1);
  if (w === r && timeoutMs > 0) {
    Atomics.wait(ctrl, 0, w, timeoutMs);
    w = Atomics.load(ctrl, 0);
  }
  const chunks = [];
  let current = null;
  const size = data.length;
  while (r < w) {
    const v = data[r % size];
    r += 1;
    if (v < 0) {
      current = [(-v - 1) / 1000, ""];
      chunks.push(current);
    } else {
      if (current === null) {
        current = [0, ""];
        chunks.push(current);
      }
      current[1] += String.fromCharCode(v);
    }
  }
  Atomics.store(ctrl, 1, r);
  return chunks;
}

const bridge = {
  can_block: false,
  write(text) {
    post("out", { text });
  },
  event(kind, value) {
    post("event", { kind, value });
  },
  wait_input(timeoutMs) {
    return ring ? readRing(timeoutMs) : [];
  },
  interrupted() {
    if (!interruptBuffer) return false;
    if (Atomics.load(interruptBuffer, 0) !== 0) {
      Atomics.store(interruptBuffer, 0, 0);
      return true;
    }
    return false;
  },
};

function schedule(delay) {
  clearTimeout(timer);
  if (typeof delay === "number" && delay >= 0) {
    timer = setTimeout(() => call(() => session.timer()), delay);
  }
}

function call(fn) {
  if (!session) return;
  let delay;
  try {
    delay = fn();
  } catch (err) {
    console.error(err);
    post("event", { kind: "error", value: String(err && err.message ? err.message : err) });
  }
  schedule(delay);
  scheduleSync();
}

function syncfs(populate) {
  return new Promise((resolve, reject) => {
    py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve()));
  });
}

function scheduleSync(delay = 400) {
  if (!persistent) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(flushFiles, delay);
}

async function flushFiles() {
  if (!persistent) return;
  if (syncing) {
    syncAgain = true;
    return;
  }
  syncing = true;
  try {
    await syncfs(false);
  } catch (err) {
    console.warn("could not save files to IndexedDB", err);
  } finally {
    syncing = false;
    if (syncAgain) {
      syncAgain = false;
      scheduleSync(0);
    }
  }
}

async function mountHome() {
  py.FS.mkdirTree(HOME);
  try {
    py.FS.mount(py.FS.filesystems.IDBFS, {}, HOME);
    await syncfs(true);
    persistent = true;
  } catch (err) {
    console.warn("IndexedDB is not available; files last until the page is closed", err);
    post("event", { kind: "storage", value: "memory" });
  }
}

async function start(msg) {
  const status = (text) => post("status", { text });
  if (msg.ring) {
    ring = { ctrl: new Int32Array(msg.ring.ctrl), data: new Int32Array(msg.ring.data) };
    interruptBuffer = new Int32Array(msg.interrupt);
    bridge.can_block = true;
  }
  status("Loading Python (Pyodide)...");
  const indexURL = new URL("./vendor/pyodide/", import.meta.url).href;
  py = await loadPyodide({
    indexURL,
    stdout: (line) => console.log(line),
    stderr: (line) => console.warn(line),
    env: { HOME },
  });
  if (interruptBuffer) py.setInterruptBuffer(interruptBuffer);
  status("Loading LSE...");
  const response = await fetch(new URL(`./app.zip?v=${BUILD_ID}`, import.meta.url));
  if (!response.ok) throw new Error(`app.zip: HTTP ${response.status}`);
  py.unpackArchive(await response.arrayBuffer(), "zip", { extractDir: APP_DIR });
  status("Opening your files...");
  await mountHome();
  py.runPython(`import sys; sys.path.insert(0, ${JSON.stringify(APP_DIR)})`);
  const lseWeb = py.pyimport("lse_web");
  session = lseWeb.create(bridge, msg.rows, msg.cols, HOME, py.toPy(msg.args || []), APP_DIR);
  post("ready", { blocking: bridge.can_block, persistent });
  const early = pending.splice(0);
  call(() => session.pump());
  for (const m of early) handle(m);
}

// messages that arrive while Python is still loading
const pending = [];

self.onmessage = (event) => {
  const msg = event.data;
  if (!session && msg.type !== "init") {
    pending.push(msg);
    return;
  }
  handle(msg);
};

function handle(msg) {
  switch (msg.type) {
    case "init":
      start(msg).catch((err) => {
        console.error(err);
        post("fatal", { text: String(err && err.message ? err.message : err) });
      });
      break;
    case "wake":
      call(() => session.pump());
      break;
    case "keys":
      call(() => session.pump(py.toPy(msg.chunks)));
      break;
    case "resize":
      call(() => {
        session.resize(msg.rows, msg.cols);
        return session.next_delay();
      });
      break;
    case "flush":
      flushFiles();
      break;
    default:
      break;
  }
}
