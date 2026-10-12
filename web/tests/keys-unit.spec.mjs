// keys.js on its own: the characters sent for key events (as macOS browsers
// report them) and for clicks on the key bar. No browser needed.

import { expect, test } from "@playwright/test";
import { barItems, barKeyInput, fkey, isMac, keyInput } from "../src/keys.js";

test.skip(({ browserName }) => browserName !== "chromium", "plain JavaScript; once is enough");

const down = (init) => ({ type: "keydown", key: "", code: "", ...init });

test("Ctrl+letter comes from the letter typed, or the physical key on a non-Latin layout", () => {
  expect(keyInput(down({ key: "q", code: "KeyQ", ctrlKey: true }))).toBe("\x11");
  // Hebrew input source on a Mac: Q types "/", Chrome and Safari say keyCode 191
  expect(keyInput(down({ key: "/", code: "KeyQ", ctrlKey: true }))).toBe("\x11");
  // Russian: W types "ц"
  expect(keyInput(down({ key: "ц", code: "KeyW", ctrlKey: true }))).toBe("\x17");
  // an input method (keyCode 229)
  expect(keyInput(down({ key: "Process", code: "KeyL", ctrlKey: true }))).toBe("\x0c");
  // AZERTY: the key labelled A is where QWERTY has Q
  expect(keyInput(down({ key: "a", code: "KeyQ", ctrlKey: true }))).toBe("\x01");
  expect(keyInput(down({ key: "C", code: "KeyC", ctrlKey: true }))).toBe("\x03");
});

test("Alt/Option-W, -N, -Q stand in for Ctrl-W, Ctrl-N, Ctrl-Q; Option+digit is an F-key", () => {
  expect(keyInput(down({ key: "∑", code: "KeyW", altKey: true }))).toBe("\x17");
  expect(keyInput(down({ key: "Dead", code: "KeyN", altKey: true }))).toBe("\x0e");
  expect(keyInput(down({ key: "œ", code: "KeyQ", altKey: true }))).toBe("\x11");
  expect(keyInput(down({ key: "¢", code: "Digit4", altKey: true }))).toBe("\x1bOS");
  expect(keyInput(down({ key: "º", code: "Digit0", altKey: true }))).toBe("\x1b[21~");
  expect(keyInput(down({ key: "¡", code: "Digit1", altKey: true }))).toBe("\x1bOP");
  // other Option keys type their character (é, ñ ...) as usual
  expect(keyInput(down({ key: "Dead", code: "KeyE", altKey: true }))).toBeNull();
  expect(keyInput(down({ key: "Œ", code: "KeyQ", altKey: true, shiftKey: true }))).toBeNull();
});

test("Esc and the F-keys, whatever keyCode says", () => {
  expect(keyInput(down({ key: "Escape", code: "Escape" }))).toBe("\x1b");
  expect(keyInput(down({ key: "F4", code: "F4" }))).toBe("\x1bOS");
  expect(keyInput(down({ key: "F5", code: "F5" }))).toBe("\x1b[15~");
  expect(keyInput(down({ key: "F10", code: "F10" }))).toBe("\x1b[21~");
  expect(keyInput(down({ key: "F8", code: "F8", shiftKey: true }))).toBe("\x1b[19;2~");
  expect(keyInput(down({ key: "F1", code: "F1", shiftKey: true }))).toBe("\x1b[1;2P");
  expect(keyInput(down({ key: "F20", code: "F20" }))).toBeNull();
});

test("everything else is left to xterm.js", () => {
  expect(keyInput(down({ key: "a", code: "KeyA" }))).toBeNull();
  expect(keyInput(down({ key: "Tab", code: "Tab" }))).toBeNull();
  expect(keyInput(down({ key: "ArrowUp", code: "ArrowUp" }))).toBeNull();
  expect(keyInput(down({ key: "q", code: "KeyQ", metaKey: true }))).toBeNull();
  expect(keyInput(down({ key: "Tab", code: "Tab", shiftKey: true }))).toBeNull();
  expect(keyInput(down({ key: "K", code: "KeyK", ctrlKey: true, shiftKey: true }))).toBeNull();
  // AltGr on Windows is Ctrl+Alt
  expect(keyInput(down({ key: "@", code: "KeyQ", ctrlKey: true, altKey: true }))).toBeNull();
  expect(keyInput(down({ key: "q", code: "KeyQ", ctrlKey: true, isComposing: true }))).toBeNull();
  expect(keyInput({ type: "keyup", key: "F4", code: "F4" })).toBeNull();
});

test("key-bar names", () => {
  expect(barKeyInput("F4")).toEqual({ input: "\x1bOS", loneEsc: false });
  expect(barKeyInput("^Q")).toEqual({ input: "\x11", loneEsc: false });
  expect(barKeyInput("S-F8")).toEqual({ input: fkey(8, true), loneEsc: false });
  expect(barKeyInput("Esc")).toEqual({ input: "\x1b", loneEsc: true });
  expect(barKeyInput("Esc Esc")).toEqual({ input: "\x1b\x1b", loneEsc: false });
  expect(barKeyInput("^O Enter").input).toBe("\x0f\r");
  expect(barKeyInput("Backspace").input).toBe("\x7f");
  expect(barKeyInput("Y").input).toBe("y");
  // "Up/Down": the half clicked; past the name (on the label) is the last one
  expect(barKeyInput("Up/Down", 0).input).toBe("\x1b[A");
  expect(barKeyInput("Up/Down", 2).input).toBe("\x1b[A");
  expect(barKeyInput("Up/Down", 3).input).toBe("\x1b[B");
  expect(barKeyInput("Up/Down", Infinity).input).toBe("\x1b[B");
  expect(barKeyInput("LSE>")).toBeNull();
  expect(barKeyInput("^Q Later")).toBeNull();
});

function row(text, keys) {
  const inverse = new Array(text.length).fill(false);
  for (const key of keys) {
    const at = text.indexOf(key);
    for (let i = at; i < at + key.length; i += 1) inverse[i] = true;
  }
  return [...text].map((ch, i) => ({ ch, inverse: inverse[i] }));
}

test("the key bar row", () => {
  const bar = "F1 Help  F4 Hint  Up/Down Choose  ^Q Quit   ";
  expect(barItems(row(bar, ["F1", "F4", "Up/Down", "^Q"]))).toEqual([
    { key: "F1", label: "Help", start: 0, end: 7 },
    { key: "F4", label: "Hint", start: 9, end: 16 },
    { key: "Up/Down", label: "Choose", start: 18, end: 32 },
    { key: "^Q", label: "Quit", start: 34, end: 41 },
  ]);
  // at 80 columns LSE puts single spaces between the entries
  const tight = "F1 Help F4 Hint F5 Run F6 Steps F7 Compile F8 Errors ^L Lesson ^Q Quit ";
  expect(barItems(row(tight, ["F1", "F4", "F5", "F6", "F7", "F8", "^L", "^Q"])).slice(2, 5)).toEqual([
    { key: "F5", label: "Run", start: 16, end: 22 },
    { key: "F6", label: "Steps", start: 23, end: 31 },
    { key: "F7", label: "Compile", start: 32, end: 42 },
  ]);
  expect(barKeyInput("F6").input).toBe("\x1b[17~");
  expect(barItems(row("F1 Help  ??? What", ["F1", "???"])).map((i) => i.key)).toEqual(["F1"]);
  // not the key bar (the LSE> command line, a program's output)
  expect(barItems(row("LSE> F4 Hint", ["F4"]))).toEqual([]);
  expect(barItems([])).toEqual([]);
});

test("Mac detection", () => {
  expect(isMac({ platform: "MacIntel" })).toBe(true);
  expect(isMac({ userAgentData: { platform: "macOS" }, platform: "MacIntel" })).toBe(true);
  expect(isMac({ platform: "iPad" })).toBe(true);
  expect(isMac({ platform: "Win32" })).toBe(false);
  expect(isMac({ userAgentData: { platform: "Windows" }, platform: "Linux x86_64" })).toBe(false);
  expect(isMac({ platform: "Linux x86_64" })).toBe(false);
  expect(isMac({})).toBe(false);
});
