#!/usr/bin/env python3
"""Distill Commander Spellbook's bulk variants.json into a compact static
combo DB for the Deck Forge web UI (docs/combos.json).

Why: backend.commanderspellbook.com only allows CORS from localhost and its
own frontends, so the hosted web UI can't call find-my-combos. Instead we
ship a preprocessed snapshot and match combos client-side.

Usage:
  python scripts/build_combo_db.py <path-to-variants.json>

Re-run occasionally to pick up new combos:
  curl -o variants.json https://json.commanderspellbook.com/variants.json
  python scripts/build_combo_db.py variants.json
"""

import json
import sys
from datetime import date, timezone, datetime
from pathlib import Path

MAX_CARDS = 5  # combos needing 6+ specific cards never matter in practice

def main(src):
    print(f"loading {src} (large)...")
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    variants = data["variants"] if isinstance(data, dict) else data
    print(f"{len(variants)} variants")

    out, skipped = [], 0
    for v in variants:
        if v.get("status") != "OK":
            skipped += 1
            continue
        legal = v.get("legalities") or {}
        if legal and legal.get("commander") is False:
            skipped += 1
            continue
        uses = v.get("uses") or []
        cards = [u["card"]["name"] for u in uses]
        if not cards or len(cards) > MAX_CARDS:
            skipped += 1
            continue
        produces = [p["feature"]["name"] for p in (v.get("produces") or [])]
        # c=cards, m=indices of cards that must be your commander,
        # p=produces, i=id, o=popularity, $=cheapest printing total (tcgplayer)
        entry = {
            "c": cards,
            "p": produces,
            "i": v["id"],
            "o": v.get("popularity") or 0,
            "d": "".join(c for c in "WUBRG" if c in (v.get("identity") or "")),
        }
        cmdr_idx = [n for n, u in enumerate(uses) if u.get("mustBeCommander")]
        if cmdr_idx:
            entry["m"] = cmdr_idx
        price = (v.get("prices") or {}).get("tcgplayer")
        if price:
            try:
                entry["$"] = round(float(price), 2)
            except ValueError:
                pass
        out.append(entry)

    out.sort(key=lambda e: -e["o"])
    dest = Path(__file__).resolve().parent.parent / "docs" / "combos.json"
    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "https://json.commanderspellbook.com/variants.json",
        "combos": out,
    }
    dest.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    mb = dest.stat().st_size / 1e6
    print(f"kept {len(out)}, skipped {skipped} -> {dest} ({mb:.1f} MB)")

if __name__ == "__main__":
    main(sys.argv[1])
