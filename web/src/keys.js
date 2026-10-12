// Keys for LSE in the browser: what to send to LSE for a key event, or for a
// click on the key bar, as the characters an xterm/VT220 terminal sends.
//
// xterm.js turns Ctrl+letter, Esc and the F-keys into characters from the
// legacy KeyboardEvent.keyCode. Chrome and Safari on macOS derive keyCode
// from the character the active input source types: with a Hebrew input
// source Ctrl-Q arrives as keyCode 191 (that key types "/"), and while an
// input method is active every key is 229. xterm then sends nothing. So
// those keys are decoded here from KeyboardEvent.key and .code instead.

const FKEYS = {
  1: "\x1bOP", 2: "\x1bOQ", 3: "\x1bOR", 4: "\x1bOS", 5: "\x1b[15~", 6: "\x1b[17~",
  7: "\x1b[18~", 8: "\x1b[19~", 9: "\x1b[20~", 10: "\x1b[21~", 11: "\x1b[23~", 12: "\x1b[24~",
};

// Browsers on Windows and Linux keep Ctrl-W, Ctrl-N and Ctrl-Q (close tab, new
// window, quit), so Alt (Option on a Mac) plus the same letter stands in.
const ALT_ALIASES = { KeyW: "\x17", KeyN: "\x0e", KeyQ: "\x11" };

const NAMED = {
  Esc: "\x1b", Enter: "\r", Tab: "\t", Backspace: "\x7f",
  Up: "\x1b[A", Down: "\x1b[B", Right: "\x1b[C", Left: "\x1b[D",
};

export function isMac(nav = globalThis.navigator) {
  const platform = nav?.userAgentData?.platform || nav?.platform || "";
  return /^(mac|iphone|ipad|ipod)/i.test(platform);
}

/** What an xterm sends for F``n`` (with Shift: xterm's modifier 2). */
export function fkey(n, shift = false) {
  const seq = FKEYS[n];
  if (!seq || !shift) return seq;
  return n <= 4 ? `\x1b[1;2${seq.slice(-1)}` : seq.replace("~", ";2~");
}

function ctrl(letter) {
  return String.fromCharCode(letter.toUpperCase().charCodeAt(0) - 64);
}

/**
 * The characters to send for a keydown event, or null to let xterm.js handle it.
 *
 * * Ctrl+letter: the letter the layout types if it is a-z (so AZERTY and
 *   Dvorak work), otherwise the physical key (Hebrew, Russian, Greek ...).
 * * Alt/Option-W, -N, -Q: Ctrl-W, Ctrl-N, Ctrl-Q.
 * * Alt/Option+digit: that F-key (Option-4 = F4, Option-0 = F10), like Esc then the digit.
 * * Esc and F1-F12 (Shift for S-F1..S-F12), whatever keyCode says.
 */
export function keyInput(ev) {
  if (ev.type !== "keydown" || ev.isComposing || ev.metaKey) return null;
  const code = ev.code || "";
  const { altKey: alt, ctrlKey: ctl, shiftKey: shift } = ev;
  if (alt && !ctl) {
    if (shift) return null;
    if (ALT_ALIASES[code]) return ALT_ALIASES[code];
    const digit = /^Digit(\d)$/.exec(code);
    return digit ? fkey(digit[1] === "0" ? 10 : Number(digit[1])) : null;
  }
  if (ctl && !alt) {
    if (shift) return null;
    if (/^[a-z]$/i.test(ev.key)) return ctrl(ev.key);
    const key = /^Key([A-Z])$/.exec(code);
    return key ? ctrl(key[1]) : null;
  }
  if (ctl || alt) return null;
  if (ev.key === "Escape" || code === "Escape") return shift ? null : "\x1b";
  const f = /^F(\d+)$/.exec(ev.key) || /^F(\d+)$/.exec(code);
  return f ? fkey(Number(f[1]), shift) || null : null;
}

/** The input for one key-bar key name ("F4", "^Q", "S-F8", "Esc"...), or null. */
function barPart(name) {
  if (NAMED[name]) return NAMED[name];
  let m = /^F(\d+)$/.exec(name);
  if (m) return fkey(Number(m[1])) || null;
  m = /^S-F(\d+)$/.exec(name);
  if (m) return fkey(Number(m[1]), true) || null;
  m = /^\^([A-Z])$/.exec(name);
  if (m) return ctrl(m[1]);
  if (/^[A-Z]$/.test(name)) return name.toLowerCase();
  return null;
}

/**
 * What a click on key-bar ``key`` sends, ``at`` characters into the key's name
 * ("Up/Down" is Up on the left half, Down on the right).
 * Returns ``{ input, loneEsc }`` or null; ``loneEsc`` means the input ends with
 * an Esc that LSE would otherwise hold, waiting to see if a digit follows.
 */
export function barKeyInput(key, at = 0) {
  const parts = [];
  let pos = 0;
  for (const word of key.split(" ")) {
    let name = word;
    if (word.includes("/")) {
      const choices = word.split("/");
      let start = pos;
      name = choices[choices.length - 1];
      for (const choice of choices) {
        if (at < start + choice.length + 1) {
          name = choice;
          break;
        }
        start += choice.length + 1;
      }
    }
    const input = barPart(name);
    if (input === null) return null;
    parts.push({ name, input });
    pos += word.length + 1;
  }
  if (!parts.length) return null;
  const last = parts[parts.length - 1].name;
  const before = parts.length > 1 ? parts[parts.length - 2].name : "";
  return {
    input: parts.map((p) => p.input).join(""),
    loneEsc: last === "Esc" && before !== "Esc",
  };
}

/**
 * The items of LSE's key bar in one screen row.
 *
 * ``cells`` is the row as ``[{ ch, inverse }]``; LSE draws each key name in
 * reverse video, followed by its label ("F4" "Hint"), starting in the first
 * column. Returns ``[{ key, label, start, end }]`` (columns, ``end``
 * exclusive) for the items whose keys can be sent.
 */
export function barItems(cells) {
  const items = [];
  if (!cells.length || !cells[0].inverse) return items;
  let i = 0;
  while (i < cells.length) {
    if (!cells[i].inverse) {
      i += 1;
      continue;
    }
    const keyStart = i;
    while (i < cells.length && cells[i].inverse) i += 1;
    const key = cells.slice(keyStart, i).map((c) => c.ch).join("").trim();
    let j = i;
    while (j < cells.length && !cells[j].inverse) j += 1;
    const label = cells.slice(i, j).map((c) => c.ch).join("");
    const end = i + label.trimEnd().length;
    if (key && barKeyInput(key) !== null) {
      items.push({ key, label: label.trim(), start: keyStart, end });
    }
    i = j;
  }
  return items;
}
