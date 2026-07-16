#!/usr/bin/env python3
"""Build the static Scryfall Oracle Tag index used by both front-ends."""
import json
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import decktool


def main():
    taxonomy = decktool.load_themes()
    cards = defaultdict(set)
    for theme, spec in taxonomy["themes"].items():
        for tag in spec.get("oracle_tags", []):
            print(f"fetching otag:{tag}", flush=True)
            url = ("https://api.scryfall.com/cards/search?unique=cards&q=" +
                   urllib.parse.quote(f"otag:{tag} legal:commander"))
            while url:
                page = decktool.http_json(url)
                for card in page["data"]:
                    cards[decktool.front(card["name"]).lower()].add(theme)
                url = page.get("next_page")
                time.sleep(0.12)
    payload = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "cards": {name: sorted(themes) for name, themes in sorted(cards.items())}}
    dest = Path(__file__).resolve().parent.parent / "docs" / "theme-tags.json"
    dest.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(cards)} tagged cards to {dest}")


if __name__ == "__main__":
    main()
