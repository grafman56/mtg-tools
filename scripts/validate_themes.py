#!/usr/bin/env python3
"""Run theme detection (no suggestion queries) across a list of Archidekt
deck IDs and print compact results — used to sanity-check themes.json
against decks whose archetypes are known."""

import sys
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

taxonomy = decktool.load_themes()
for label, deck_id in DECKS.items():
    try:
        name, commanders, main = decktool.fetch_archidekt(str(deck_id))
        cards = decktool.deck_card_data(str(deck_id), commanders, main)
        ranked, tribal = decktool.detect_themes(cards, taxonomy, commanders)
        parts = [f"{'*' if ch else ''}{t} ({len(m)})" for t, m, ch in ranked]
        if tribal:
            parts.append(f"{tribal[0]} tribal ({len(tribal[1])})")
        print(f"{label} [{', '.join(commanders)}]:")
        print(f"  {'; '.join(parts) if parts else 'NO THEME DETECTED'}")
    except Exception as e:
        print(f"{label}: ERROR {e}")
