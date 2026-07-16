#!/usr/bin/env python3
"""Theme-detection parity harness: proves the CLI (decktool.detect_themes) and
the web app (detectThemesJs in docs/index.html) surface the SAME themes, in the
same order, for a set of known decks -- the concrete check behind the
"two front-ends, one brain" claim in ARCHITECTURE.md.

It fetches each deck once, runs the Python detector, hands the exact same card
data to the real page JS via Node (scripts/_theme_parity_run.js), and diffs the
two ordered theme lists.

Usage:  python3 scripts/theme_parity.py
Requires: node on PATH (user-local install documented in TESTING.md).

Compares the ordered list of (theme name, supporting-card count) for each deck:
same themes, same order, same counts. Both paths count the commander as a deck
card, so the counts line up too.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import decktool  # noqa: E402

DECKS = {
    "Ever Changing": 23718180, "Mimeoplasm": 14392139, "Brago": 14179968,
    "Bruenor": 14422119, "Prosper": 14181420, "Wilhelt": 14424067,
    "Nekusar": 13865790, "Obuun": 14427307, "Vadrick": 14545722,
    "Anowon": 14429038, "Siona": 14423840, "Coven Counters": 14402209,
    "Vorel Counters": 14090810, "Rafiq": 14179232, "Varolz JANK": 13904010,
}


def scry_shape(card):
    """Reshape a decktool card into the Scryfall-ish object the web functions
    expect (oracle_text + type_line), so the real page JS consumes it as-is."""
    tl = " ".join(card["types"])
    if card["subtypes"]:
        tl += " — " + " ".join(card["subtypes"])
    return {"name": card["name"], "oracle_text": card["text"], "type_line": tl}


def py_entries(cards, commanders, tax):
    ranked, tribal = decktool.detect_themes(cards, tax, commanders)
    entries = [[t, len(m)] for t, m, _ch in ranked]
    if tribal:
        entries.append([tribal[0] + " tribal", len(tribal[1])])
    return entries


def main():
    tax = decktool.load_themes()
    decks_payload, py_results = [], {}
    for label, deck_id in DECKS.items():
        _name, commanders, main = decktool.fetch_archidekt(str(deck_id))
        cards = decktool.deck_card_data(str(deck_id), commanders, main)
        py_results[label] = py_entries(cards, commanders, tax)
        cmdr_keys = {decktool.front(c).lower() for c in commanders}
        card_objs = [scry_shape(c) for c in cards
                     if decktool.front(c["name"]).lower() not in cmdr_keys]
        cmdr_objs = [scry_shape(c) for c in cards
                     if decktool.front(c["name"]).lower() in cmdr_keys]
        decks_payload.append({"label": label, "cardObjs": card_objs,
                              "cmdrCard": cmdr_objs[0] if cmdr_objs else None})

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"decks": decks_payload}, f)
        payload_path = f.name

    runner = Path(__file__).resolve().parent / "_theme_parity_run.js"
    proc = subprocess.run(["node", str(runner), payload_path],
                          capture_output=True, text=True)
    Path(payload_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        print("node harness failed:\n" + (proc.stderr or proc.stdout))
        sys.exit(1)
    js_results = json.loads(proc.stdout)

    def fmt(entries):
        return "; ".join(f"{n}({c})" for n, c in entries) or "(none)"

    passed = 0
    for label in DECKS:
        py, js = py_results[label], js_results.get(label, [])
        if py == js:
            passed += 1
            print(f"PASS  {label:16} {fmt(py)}")
        else:
            print(f"DIFF  {label:16}")
            print(f"        CLI: {fmt(py)}")
            print(f"        web: {fmt(js)}")
    print(f"\n{passed}/{len(DECKS)} decks agree between CLI and web")
    sys.exit(0 if passed == len(DECKS) else 2)


if __name__ == "__main__":
    main()
