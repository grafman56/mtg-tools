#!/usr/bin/env python3
"""Build the static Scryfall Oracle Tag index used by both front-ends."""
import json
import time
import urllib.parse
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import decktool

CACHE_PATH = Path(__file__).resolve().parent / "theme-tag-cache.json"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "theme-tags.json"


def write_json(path, payload):
    """Write JSON atomically so a failed refresh preserves the prior artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as temp:
        json.dump(payload, temp, separators=(",", ":"))
        temp_path = Path(temp.name)
    temp_path.replace(path)


def tag_specs(taxonomy):
    """Return Scryfall tag-to-local-label mappings from the shared taxonomy."""
    specs = []
    for theme, spec in taxonomy["themes"].items():
        specs.extend((tag, theme) for tag in spec.get("oracle_tags", []))
    specs.extend((spec["tag"], spec["factor"])
                 for spec in taxonomy.get("strength", {}).get("oracle_tags", []))
    return specs


def seed_cache(taxonomy, output_path):
    """Recover already-built tag sets from the checked-in static index."""
    if not output_path.exists():
        return {"tags": {}}
    cards = json.loads(output_path.read_text(encoding="utf-8")).get("cards", {})
    tags = {}
    for tag, label in tag_specs(taxonomy):
        matches = [name for name, labels in cards.items() if label in labels]
        if matches:
            tags[tag] = matches
    return {"tags": tags}


def fetch_tag_cards(tag):
    """Fetch one complete Commander-legal Oracle Tag result set from Scryfall."""
    print(f"fetching otag:{tag}", flush=True)
    url = ("https://api.scryfall.com/cards/search?unique=cards&q=" +
           urllib.parse.quote(f"otag:{tag} legal:commander"))
    cards = set()
    while url:
        page = decktool.http_json(url)
        cards.update(decktool.front(card["name"]).lower() for card in page["data"])
        url = page.get("next_page")
        time.sleep(0.12)
    return sorted(cards)


def build_index(taxonomy, cache_path, output_path, fetch_cards, max_new_tags=1):
    """Build the static browser index, fetching at most one missing tag per run."""
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        cache = seed_cache(taxonomy, output_path)
        write_json(cache_path, cache)
    tags = cache.setdefault("tags", {})
    fetched = 0
    for tag, _label in tag_specs(taxonomy):
        if tag in tags:
            continue
        if fetched >= max_new_tags:
            write_json(cache_path, cache)
            return False
        tags[tag] = fetch_cards(tag)
        fetched += 1
        write_json(cache_path, cache)

    cards = defaultdict(set)
    for tag, label in tag_specs(taxonomy):
        for name in tags[tag]:
            cards[decktool.front(name).lower()].add(label)
    payload = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "cards": {name: sorted(labels) for name, labels in sorted(cards.items())}}
    write_json(output_path, payload)
    return True


def main():
    taxonomy = decktool.load_themes()
    try:
        complete = build_index(taxonomy, CACHE_PATH, OUTPUT_PATH, fetch_tag_cards)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            print("Scryfall rate limited this tag. The existing static index is unchanged.")
            return
        raise
    if not complete:
        print("Cached one new tag. Run the builder later to fetch the next tag.")
        return
    count = len(json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))["cards"])
    print(f"wrote {count} tagged cards to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
