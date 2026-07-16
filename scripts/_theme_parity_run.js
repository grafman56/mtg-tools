"use strict";
// Node side of the theme-parity harness (driven by scripts/theme_parity.py).
// Loads the REAL Deck Forge page (docs/index.html) inside a vm sandbox with
// document/fetch stubbed out, so the page's own detectThemesJs runs unmodified
// -- no browser, no reimplementation. Reads a deck payload on argv[2] and
// prints, per deck, the ordered theme names the web app would surface.
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "docs", "index.html"), "utf8");
const tax = JSON.parse(fs.readFileSync(path.join(root, "docs", "themes.json"), "utf8"));
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^"use strict";/, "");

// Minimal stubs: the page wires up DOM handlers and kicks off a themes.json
// fetch at load. We don't want either; we only want the pure functions.
const stubEl = {
  addEventListener() {}, value: "", checked: false, innerHTML: "",
  style: {}, querySelectorAll: () => [],
};
const sandbox = {
  document: { getElementById: () => stubEl, querySelectorAll: () => [] },
  fetch: () => Promise.reject(new Error("no network in harness")),
  setTimeout: () => 0, clearTimeout() {}, console,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(script, sandbox); // defines detectThemesJs et al in the sandbox

const detectThemesJs = sandbox.detectThemesJs;
if (typeof detectThemesJs !== "function") {
  console.error("could not reach detectThemesJs from the page source");
  process.exit(1);
}

const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
for (const d of payload.decks) {
  const { ranked, tribal } = detectThemesJs(d.cardObjs, tax, d.cmdrCard, "", []);
  // [theme name, supporting-card count], in order -- compared against the CLI.
  const entries = ranked.map((r) => [r[0], r[1].length]);
  if (tribal) entries.push([tribal[0] + " tribal", tribal[1].length]);
  out[d.label] = entries;
}
process.stdout.write(JSON.stringify(out));
