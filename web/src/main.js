// The page: an xterm.js terminal showing LSE, which runs in worker.js.

import { Terminal } from "./vendor/xterm/xterm.mjs?v=__BUILD_ID__";
import { FitAddon } from "./vendor/xterm/addon-fit.mjs?v=__BUILD_ID__";
import { WebglAddon } from "./vendor/xterm/addon-webgl.mjs?v=__BUILD_ID__";
import { keyInput } from "./keys.js?v=__BUILD_ID__";

const BUILD_ID = "__BUILD_ID__";
const STORE = "vms-lse-pascal:";
const HOME_DB = "/home/lse"; // IDBFS names its IndexedDB database after the mount point
const MIN_COLS = 80;
const MIN_ROWS = 24;
const FONT_NAME = "VT323";
const FONT_FAMILY = `"${FONT_NAME}", "DejaVu Sans Mono", Menlo, Consolas, monospace`;
const MAX_FIT_FONT = 30;
const RING_UNITS = 1 << 16;
const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "AltGraph", "Meta", "CapsLock", "Fn"]);

// The colours of lse.themes (xterm 256-colour palette entries 250, 214, 40).
const THEMES = {
  VT220: { fg: "#bcbcbc", glow: "200, 200, 200" },
  AMBER: { fg: "#ffaf00", glow: "255, 175, 0" },
  GREEN: { fg: "#00d700", glow: "0, 215, 0" },
};

const params = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);

const state = {
  ready: false,
  mode: "edit",
  modified: false,
  blocking: false,
  persistent: false,
  outputs: 0,
  reads: 0,
  readyStatus: ["", ""],
};

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.dataset.kind = kind;
}

async function ensureIsolation() {
  const flag = STORE + "coi-reload";
  if (window.crossOriginIsolated) {
    sessionStorage.removeItem(flag);
    navigator.serviceWorker?.register("./sw.js", { scope: "./" }).catch(() => {});
    return true;
  }
  if (!("serviceWorker" in navigator) || !window.isSecureContext || params.has("no-sw")) {
    return false;
  }
  const giveUp = (ms) => new Promise((_, reject) => {
    setTimeout(() => reject(new Error("the service worker did not start")), ms);
  });
  try {
    await Promise.race([navigator.serviceWorker.register("./sw.js", { scope: "./" }), giveUp(5000)]);
    if (sessionStorage.getItem(flag)) return false;
    await Promise.race([navigator.serviceWorker.ready, giveUp(5000)]);
    sessionStorage.setItem(flag, "1");
    location.reload();
    return new Promise(() => {});
  } catch (err) {
    console.warn("service worker unavailable:", err);
    return false;
  }
}

async function loadFont() {
  try {
    await Promise.race([
      document.fonts.load(`20px "${FONT_NAME}"`),
      new Promise((resolve) => setTimeout(resolve, 3000)),
    ]);
  } catch (err) {
    console.warn("font:", err);
  }
}

function sizeSetting() {
  const value = params.get("size") || localStorage.getItem(STORE + "size") || "fit";
  const m = /^(\d+)x(\d+)$/.exec(value);
  if (m) {
    return { value, cols: Math.max(MIN_COLS, +m[1]), rows: Math.max(MIN_ROWS, +m[2]) };
  }
  return { value: "fit", cols: MIN_COLS, rows: MIN_ROWS };
}

function launchArgs() {
  const args = [];
  const seed = params.get("seed");
  if (seed && /^-?\d+$/.test(seed)) args.push("--seed", seed);
  const theme = (params.get("theme") || "").toUpperCase();
  if (THEMES[theme]) args.push("--theme", theme);
  return args;
}

async function main() {
  const blocking = (await ensureIsolation()) && typeof SharedArrayBuffer !== "undefined";
  await loadFont();

  const term = new Terminal({
    fontFamily: FONT_FAMILY,
    fontSize: 20,
    cursorBlink: true,
    cursorStyle: "block",
    scrollback: 0,
    drawBoldTextInBrightColors: false,
    // Option types é, ñ, ü ... as everywhere on a Mac; keys.js gives Option-W/N/Q
    // and Option+digit their LSE meanings.
    macOptionIsMeta: false,
    theme: {
      background: "#000000",
      foreground: THEMES.VT220.fg,
      cursor: THEMES.VT220.fg,
      cursorAccent: "#000000",
      black: "#000000",
      selectionBackground: "rgba(188, 188, 188, 0.35)",
    },
  });
  const fit = new FitAddon();
  term.loadAddon(fit);
  term.open($("terminal"));
  try {
    const webgl = new WebglAddon();
    webgl.onContextLoss(() => webgl.dispose());
    term.loadAddon(webgl);
  } catch (err) {
    console.warn("WebGL renderer unavailable, using the DOM renderer:", err);
  }

  // ----- size: at least 80x24, as large a font as fits -----------------------

  function layout() {
    const want = sizeSetting();
    const fitsAt = (size) => {
      term.options.fontSize = size;
      const d = fit.proposeDimensions();
      return d && d.cols >= want.cols && d.rows >= want.rows ? d : null;
    };
    let lo = 6;
    let hi = 96;
    if (!fitsAt(lo)) hi = lo;
    while (hi - lo > 1) {
      const mid = Math.floor((lo + hi) / 2);
      if (fitsAt(mid)) lo = mid;
      else hi = mid;
    }
    const size = want.value === "fit" ? Math.min(lo, MAX_FIT_FONT) : lo;
    term.options.fontSize = size;
    const d = fit.proposeDimensions() || want;
    const cols = want.value === "fit" ? Math.max(MIN_COLS, d.cols) : want.cols;
    const rows = want.value === "fit" ? Math.max(MIN_ROWS, d.rows) : want.rows;
    if (cols !== term.cols || rows !== term.rows) term.resize(cols, rows);
    $("size").value = ["fit", "80x24", "132x24"].includes(want.value) ? want.value : "fit";
    return { cols, rows };
  }

  let { cols, rows } = layout();
  term.write("\x1b[?25l\x1b[2J\x1b[H\r\n  LSE for Pascal\r\n\r\n  Loading Python (Pyodide)...");

  // ----- the worker and the key ring ------------------------------------------

  const worker = new Worker(new URL(`./worker.js?v=${BUILD_ID}`, import.meta.url), {
    type: "module",
  });
  let ring = null;
  let interrupt = null;
  if (blocking) {
    ring = {
      ctrl: new Int32Array(new SharedArrayBuffer(8)),
      data: new Int32Array(new SharedArrayBuffer(RING_UNITS * 4)),
    };
    interrupt = new Int32Array(new SharedArrayBuffer(4));
  }
  let lastInput = performance.now();

  function pushChunk(text, elapsedMs) {
    const { ctrl, data } = ring;
    const w = Atomics.load(ctrl, 0);
    const r = Atomics.load(ctrl, 1);
    const n = 1 + text.length;
    if (w - r + n > RING_UNITS) {
      console.warn("typing faster than LSE can keep up; keys dropped");
      return;
    }
    data[w % RING_UNITS] = -(1 + elapsedMs);
    for (let i = 0; i < text.length; i += 1) data[(w + 1 + i) % RING_UNITS] = text.charCodeAt(i);
    Atomics.store(ctrl, 0, w + n);
    Atomics.notify(ctrl, 0);
    worker.postMessage({ type: "wake" });
  }

  const sent = [];

  function sendInput(text) {
    sent.push(text);
    if (sent.length > 200) sent.shift();
    const now = performance.now();
    const elapsed = Math.min(Math.round(now - lastInput), 1e9);
    lastInput = now;
    if (ring) {
      if (state.mode === "run" && text === "\x03") {
        Atomics.store(interrupt, 0, 2);
        pushChunk("", elapsed);
        return;
      }
      pushChunk(text, elapsed);
    } else {
      worker.postMessage({ type: "keys", chunks: [[elapsed / 1000, text]] });
    }
  }

  term.onData(sendInput);

  // macOS starts an accent for Option-N (and Option-E, -U, -I, -`) even when the
  // keydown is cancelled, and the accent lands on the next key typed. After an
  // Alt/Option key LSE uses, swallow any composition that starts and end it by
  // taking the focus off the textarea and back.
  const ta = term.textarea;
  const composition = {
    armedUntil: 0,
    cancelling: false,
    active() {
      return this.cancelling || performance.now() < this.armedUntil;
    },
    cancel() {
      this.cancelling = true;
      ta.readOnly = true;
      ta.blur();
      ta.value = "";
      setTimeout(() => {
        ta.value = "";
        ta.readOnly = false;
        this.cancelling = false;
        this.armedUntil = 0;
        term.focus();
      }, 20);
    },
  };
  for (const type of ["compositionstart", "compositionupdate", "compositionend", "beforeinput", "input", "keypress"]) {
    term.element.addEventListener(type, (ev) => {
      if (ev.target !== ta || !composition.active()) return;
      ev.stopPropagation();
      if (ev.cancelable) ev.preventDefault();
      if (ev.type === "compositionstart" && !composition.cancelling) composition.cancel();
    }, true);
  }

  term.attachCustomKeyEventHandler((ev) => {
    if (ev.type !== "keydown") return true;
    const input = keyInput(ev);
    if (input === null) {
      if (!MODIFIER_KEYS.has(ev.key)) composition.armedUntil = 0;
      return true;
    }
    ev.preventDefault();
    composition.armedUntil = ev.altKey ? performance.now() + 300 : 0;
    sendInput(input);
    return false;
  });

  function applyTheme(name) {
    const t = THEMES[name] || THEMES.VT220;
    term.options.theme = { ...term.options.theme, foreground: t.fg, cursor: t.fg };
    document.documentElement.style.setProperty("--glow", t.glow);
  }

  worker.onmessage = (event) => {
    const msg = event.data;
    switch (msg.type) {
      case "out":
        state.outputs += 1;
        term.write(msg.text);
        break;
      case "status":
        setStatus(msg.text);
        term.write(`\r\x1b[2K  ${msg.text}`);
        break;
      case "ready":
        state.ready = true;
        state.blocking = msg.blocking;
        state.persistent = msg.persistent;
        if (!msg.blocking) {
          state.readyStatus = ["Limited: running programs cannot read the keyboard in this window", "warn"];
        } else if (!msg.persistent) {
          state.readyStatus = ["Files last until you close this page (no IndexedDB)", "warn"];
        } else {
          state.readyStatus = ["Your files are saved in this browser", ""];
        }
        setStatus(...state.readyStatus);
        break;
      case "event":
        if (msg.kind === "mode") {
          state.mode = msg.value;
          if (msg.value === "run") setStatus("Your program is running. Ctrl-C stops it.");
          else setStatus(...state.readyStatus);
        } else if (msg.kind === "input") {
          state.reads += 1;
          setStatus("Your program is waiting for you: type an answer and press RETURN.");
        } else if (msg.kind === "modified") state.modified = msg.value === "1";
        else if (msg.kind === "theme") applyTheme(msg.value);
        else if (msg.kind === "bell") {
          $("bezel").classList.add("bell");
          setTimeout(() => $("bezel").classList.remove("bell"), 160);
        } else if (msg.kind === "error") console.error("LSE:", msg.value);
        break;
      case "fatal":
        setStatus("LSE could not start", "error");
        term.write(`\r\n\r\n\x1b[1m  LSE could not start: ${msg.text}\x1b[0m\r\n  Reload the page to try again.`);
        break;
      default:
        break;
    }
  };
  worker.onerror = (err) => {
    console.error(err);
    setStatus("LSE stopped with an error; reload the page", "error");
  };

  worker.postMessage({
    type: "init",
    rows,
    cols,
    args: launchArgs(),
    ring: ring && { ctrl: ring.ctrl.buffer, data: ring.data.buffer },
    interrupt: interrupt && interrupt.buffer,
  });

  // ----- page controls ------------------------------------------------------

  let resizeTimer = 0;
  function relayout() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const size = layout();
      if (size.cols !== cols || size.rows !== rows) {
        ({ cols, rows } = size);
        worker.postMessage({ type: "resize", rows, cols });
      }
    }, 100);
  }
  window.addEventListener("resize", relayout);
  $("size").addEventListener("change", (ev) => {
    localStorage.setItem(STORE + "size", ev.target.value);
    if (params.has("size")) {
      params.delete("size");
      const query = params.toString();
      history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}`);
    }
    relayout();
    term.focus();
  });

  $("keys-btn").addEventListener("click", () => {
    const panel = $("keys-panel");
    panel.hidden = !panel.hidden;
    $("keys-btn").setAttribute("aria-expanded", String(!panel.hidden));
    relayout();
    if (panel.hidden) term.focus();
  });

  $("reset-btn").addEventListener("click", async () => {
    if (!confirm("Start over? This erases your files and tutorial progress in this browser.")) {
      term.focus();
      return;
    }
    worker.terminate();
    await new Promise((resolve) => {
      const req = indexedDB.deleteDatabase(HOME_DB);
      req.onsuccess = req.onerror = req.onblocked = () => resolve();
    });
    location.reload();
  });

  const bezel = $("bezel");
  bezel.addEventListener("mousedown", () => setTimeout(() => term.focus(), 0));
  term.textarea?.addEventListener("focus", () => bezel.classList.remove("unfocused"));
  term.textarea?.addEventListener("blur", () => {
    if (!composition.cancelling) bezel.classList.add("unfocused");
  });

  window.addEventListener("beforeunload", (ev) => {
    if (state.modified) {
      ev.preventDefault();
      ev.returnValue = "";
    }
  });
  const flush = () => worker.postMessage({ type: "flush" });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);

  term.focus();

  // for tests and the curious (window.lse.text() is the screen as text)
  window.lse = {
    term,
    state,
    text() {
      const buf = term.buffer.active;
      const lines = [];
      for (let i = 0; i < term.rows; i += 1) {
        lines.push(buf.getLine(buf.viewportY + i)?.translateToString(true) ?? "");
      }
      return lines.join("\n");
    },
    input: sendInput,
    sent,
  };
}

main().catch((err) => {
  console.error(err);
  setStatus(`LSE could not start: ${err.message || err}`, "error");
});
