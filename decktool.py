#!/usr/bin/env python3
"""decktool — deck-building helper for Paul's Commander decks.

Subcommands:
  fetch <deck>            Print a normalized decklist from an Archidekt deck ID/URL.
  combos <deck>           Find combos in the deck and combos 1 card away
                          (Commander Spellbook). Finite combos shown first;
                          infinite combos are flagged and collapsed by default.
  wincons <deck>          Like combos, but only show combos that actually end
                          the game (win / lose / damage / mill the table).
  finishers <deck>        Suggest non-combo, finite game-enders (Scryfall,
                          ranked by EDHREC popularity) in the deck's color
                          identity that aren't already in the list.

Options:
  --show-infinite         Expand infinite combos instead of collapsing them.
  --max-price N           Only suggest missing cards costing <= N dollars (default 20).
  --json                  Dump raw report as JSON (for piping to other tools).

Deck argument accepts a bare Archidekt ID (23718180), an Archidekt URL, or a
path to a local text decklist ("1x Card Name" or "1 Card Name" per line,
commander marked with a trailing *CMDR* or listed after a "Commander" header).
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
SPELLBOOK_URL = "https://backend.commanderspellbook.com/find-my-combos"
UA = "mtg-tools/0.1 (decktool; contact: pauleitel4@gmail.com)"

# Feature names that mean "this actually ends the game".
GAME_ENDING_PAT = re.compile(
    r"wins? the game|loses? the game|damage|life loss|lifeloss|mill|poison|infect|combat",
    re.IGNORECASE,
)


def http_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


# ---------------------------------------------------------------- deck input

def parse_deck_arg(arg):
    """Return (deck_name, commanders[list of names], main[dict name->qty])."""
    m = re.search(r"archidekt\.com/(?:api/)?decks/(\d+)", arg)
    if m:
        return fetch_archidekt(m.group(1))
    if arg.isdigit():
        return fetch_archidekt(arg)
    return parse_text_decklist(Path(arg))


def fetch_archidekt(deck_id):
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"archidekt_{deck_id}.json"
    d = http_json(f"https://archidekt.com/api/decks/{deck_id}/")
    cache.write_text(json.dumps(d), encoding="utf-8")

    # Categories with includedInDeck=False (Maybeboard, Sideboard...) are out.
    excluded = {c["name"] for c in d.get("categories", []) if not c.get("includedInDeck", True)}
    commanders, main = [], {}
    for entry in d["cards"]:
        cats = entry.get("categories") or []
        name = entry["card"]["oracleCard"]["name"]
        if cats and cats[0] in excluded:
            continue
        if "Commander" in cats:
            commanders.append(name)
        else:
            main[name] = main.get(name, 0) + entry["quantity"]
    return d.get("name", deck_id), commanders, main


def parse_text_decklist(path):
    commanders, main = [], {}
    section_cmdr = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if re.fullmatch(r"\[?commander:?\]?", line, re.IGNORECASE):
            section_cmdr = True
            continue
        if re.fullmatch(r"\[?(main|deck|mainboard):?\]?", line, re.IGNORECASE):
            section_cmdr = False
            continue
        m = re.match(r"(\d+)x?\s+(.*)", line)
        qty, name = (int(m.group(1)), m.group(2)) if m else (1, line)
        is_cmdr = section_cmdr or "*CMDR*" in name
        name = name.replace("*CMDR*", "").strip()
        if is_cmdr:
            commanders.append(name)
        else:
            main[name] = main.get(name, 0) + qty
    return path.stem, commanders, main


# ---------------------------------------------------------------- spellbook

def find_combos(commanders, main):
    body = {
        "commanders": [{"card": c, "quantity": 1} for c in commanders],
        "main": [{"card": n, "quantity": q} for n, q in main.items()],
    }
    return http_json(SPELLBOOK_URL, body)["results"]


def combo_summary(combo, deck_names):
    uses = [u["card"]["name"] for u in combo["uses"]]
    produces = [p["feature"]["name"] for p in combo["produces"]]
    missing = [u for u in uses if u not in deck_names]
    price = combo.get("prices", {}).get("tcgplayer")
    return {
        "id": combo["id"],
        "uses": uses,
        "missing": missing,
        "produces": produces,
        "infinite": any(p.lower().startswith(("infinite", "near-infinite")) for p in produces),
        "game_ending": any(GAME_ENDING_PAT.search(p) for p in produces),
        "description": combo.get("description", ""),
        "popularity": combo.get("popularity") or 0,
        "price": float(price) if price else None,
        "bracket": combo.get("bracketTag"),
        "url": f"https://commanderspellbook.com/combo/{combo['id']}/",
    }


# ---------------------------------------------------------------- finishers

# Buckets of "actually ends the game without going infinite" cards.
FINISHER_QUERIES = {
    "Alternate win condition": '(o:"you win the game") -o:"can\'t win"',
    "Drain the table": 'o:/each opponent loses [X\\d]+ life/',
    "Burn the table": 'o:/deals [X\\d]+ damage to each opponent/',
    "Overrun effects": '(t:sorcery or t:instant) o:/creatures you control get \\+[X\\d]/',
    "Extra combat": 'o:"additional combat phase"',
    "Mass evasion": "(t:sorcery or t:instant or t:enchantment) "
                    "(o:\"can't be blocked\" or o:\"gain flying until\") "
                    'o:"creatures you control"',
}


def commander_identity(commanders):
    ident = set()
    for name in commanders:
        card = http_json("https://api.scryfall.com/cards/named?exact="
                         + urllib.parse.quote(name))
        ident.update(card.get("color_identity", []))
    return "".join(c for c in "WUBRG" if c in ident) or "C"


def scryfall_search(query):
    url = ("https://api.scryfall.com/cards/search?order=edhrec&unique=cards&q="
           + urllib.parse.quote(query))
    try:
        return http_json(url).get("data", [])
    except urllib.error.HTTPError as e:
        if e.code == 404:  # no results
            return []
        raise


def print_finishers(deck_name, commanders, main, max_price):
    ident = commander_identity(commanders)
    deck_names = set(main) | set(commanders)
    deck_names |= {n.split("//")[0].strip() for n in deck_names}
    print(f"# Finisher suggestions for {deck_name} "
          f"({', '.join(commanders)} — identity {ident})\n")
    for bucket, q in FINISHER_QUERIES.items():
        full_q = f"({q}) id<={ident} legal:commander usd<={max_price:g}"
        cards = scryfall_search(full_q)
        fresh = [c for c in cards
                 if c["name"] not in deck_names
                 and c["name"].split("//")[0].strip() not in deck_names][:8]
        print(f"## {bucket}")
        if not fresh:
            print("  (nothing new in identity/budget)")
        for c in fresh:
            price = c.get("prices", {}).get("usd")
            pricestr = f" ${price}" if price else ""
            line1 = (c.get("oracle_text") or
                     " // ".join(f.get("oracle_text", "")
                                 for f in c.get("card_faces", []))).split("\n")
            text = next((l for l in line1 if GAME_ENDING_PAT.search(l)
                         or "win the game" in l.lower()), line1[0] if line1 else "")
            print(f"  - {c['name']} ({c.get('mana_cost', '?')}){pricestr}")
            print(f"      {text[:150]}")
        print()


# ---------------------------------------------------------------- reporting

def build_report(deck_name, commanders, main, wincons_only=False):
    results = find_combos(commanders, main)
    deck_names = set(main) | set(commanders)
    # Split double-faced deck names so "Glasspool Mimic // Glasspool Shore"
    # matches Spellbook's front-face naming.
    for n in list(deck_names):
        if "//" in n:
            deck_names.add(n.split("//")[0].strip())

    included = [combo_summary(c, deck_names) for c in results["included"]]
    almost = [combo_summary(c, deck_names) for c in results["almostIncluded"]]
    almost = [c for c in almost if len(c["missing"]) == 1]
    if wincons_only:
        included = [c for c in included if c["game_ending"]]
        almost = [c for c in almost if c["game_ending"]]

    # Group near-miss combos by the missing card: which single purchase
    # unlocks the most combos?
    by_card = defaultdict(list)
    for c in almost:
        by_card[c["missing"][0]].append(c)
    return {
        "deck": deck_name,
        "commanders": commanders,
        "deck_size": sum(main.values()) + len(commanders),
        "included": included,
        "almost_by_card": dict(by_card),
    }


def fmt_combo(c, show_missing=False):
    tag = "INFINITE" if c["infinite"] else "finite"
    end = " [ends the game]" if c["game_ending"] else ""
    lines = [f"  - {' + '.join(c['uses'])}  ({tag}{end})"]
    lines.append(f"      -> {'; '.join(c['produces'])}")
    lines.append(f"      {c['url']}")
    return "\n".join(lines)


def print_report(rep, show_infinite=False, max_price=20.0):
    print(f"# {rep['deck']} — {', '.join(rep['commanders'])} ({rep['deck_size']} cards)\n")

    inc_fin = [c for c in rep["included"] if not c["infinite"]]
    inc_inf = [c for c in rep["included"] if c["infinite"]]
    print(f"## Combos already in the deck: {len(rep['included'])} "
          f"({len(inc_fin)} finite, {len(inc_inf)} infinite)")
    for c in inc_fin:
        print(fmt_combo(c))
    if inc_inf:
        if show_infinite:
            for c in inc_inf:
                print(fmt_combo(c))
        else:
            print(f"  ({len(inc_inf)} infinite combos hidden — you avoid these; "
                  f"--show-infinite to list, e.g. for cuts)")

    print("\n## One card away (best single adds first)")
    ranked = []
    for card, combos in rep["almost_by_card"].items():
        finite = [c for c in combos if not c["infinite"]]
        ending = [c for c in combos if c["game_ending"] and not c["infinite"]]
        prices = [c["price"] for c in combos if c["price"] is not None]
        price = min(prices) if prices else None
        ranked.append((card, combos, finite, ending, price))
    # Rank: game-ending finite combos first, then finite count, then popularity.
    ranked.sort(key=lambda r: (len(r[3]), len(r[2]),
                               max(c["popularity"] for c in r[1])), reverse=True)

    shown = 0
    for card, combos, finite, ending, price in ranked:
        if not finite and not show_infinite:
            continue
        pricestr = f" (~${price:.2f} for combo)" if price is not None else ""
        if max_price and price is not None and price > max_price:
            continue
        print(f"\n  + {card}{pricestr} — unlocks {len(finite)} finite"
              f" ({len(ending)} game-ending), {len(combos) - len(finite)} infinite")
        for c in (finite if not show_infinite else combos)[:4]:
            print(fmt_combo(c))
        shown += 1
        if shown >= 15:
            remaining = len(ranked) - shown
            if remaining > 0:
                print(f"\n  ... {remaining} more candidate cards (use --json for all)")
            break


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "combos", "wincons", "finishers"])
    ap.add_argument("deck", help="Archidekt ID/URL or path to text decklist")
    ap.add_argument("--show-infinite", action="store_true")
    ap.add_argument("--max-price", type=float, default=20.0)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    name, commanders, main_cards = parse_deck_arg(args.deck)
    if args.command == "fetch":
        print(f"// {name}")
        for c in commanders:
            print(f"1x {c} *CMDR*")
        for n, q in sorted(main_cards.items()):
            print(f"{q}x {n}")
        return

    if args.command == "finishers":
        print_finishers(name, commanders, main_cards, args.max_price)
        return

    rep = build_report(name, commanders, main_cards,
                       wincons_only=(args.command == "wincons"))
    if args.as_json:
        json.dump(rep, sys.stdout, indent=1)
    else:
        print_report(rep, show_infinite=args.show_infinite, max_price=args.max_price)


if __name__ == "__main__":
    main()
