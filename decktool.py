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
  themes <deck>           Detect the deck's dominant themes (oracle-text
                          taxonomy in docs/themes.json + tribal counting) and
                          suggest payoffs/finishers keyed to those themes
                          instead of generic color staples.

Options:
  --show-infinite         Expand infinite combos instead of collapsing them.
  --max-price N           Only suggest missing cards costing <= N dollars (default 100).
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
UA = "mtg-tools/0.1 (decktool; +https://github.com/grafman56/mtg-tools)"
DEFAULT_MAX_PRICE = 100.0

# Feature names that mean "this actually ends the game".
GAME_ENDING_PAT = re.compile(
    r"wins? the game|loses? the game|damage|life loss|lifeloss|mill|poison|infect|combat",
    re.IGNORECASE,
)

ROLE_TARGETS = {
    "Lands": 37, "Ramp": 10, "Card draw": 10,
    "Interaction": 10, "Board wipes": 3,
}


def http_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
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
        if any(cat in excluded for cat in cats):
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


# ---------------------------------------------------------------- themes

def load_themes():
    return json.loads((Path(__file__).parent / "docs" / "themes.json")
                      .read_text(encoding="utf-8"))


def load_theme_tags():
    path = Path(__file__).parent / "docs" / "theme-tags.json"
    return json.loads(path.read_text(encoding="utf-8"))["cards"] if path.exists() else {}


def oracle_text(card):
    """Return Oracle text for a normal or double-faced Scryfall card."""
    return card.get("oracle_text") or card.get("text") or "\n".join(
        face.get("oracle_text", "") for face in card.get("card_faces", []))


def impact_for_card(card, taxonomy):
    """Classify multiplayer reach without treating it as theme evidence."""
    text = oracle_text(card)
    impact = taxonomy.get("impact", {})
    scope = next((rule for rule in impact.get("scope", [])
                  if re.search(rule["pattern"], text, re.IGNORECASE)), None)
    if not scope:
        return {"score": 0, "scope": None, "delivery": None}
    delivery = next((rule for rule in impact.get("delivery", [])
                     if re.search(rule["pattern"], text, re.IGNORECASE)),
                    {"name": "one-shot effect", "weight": 1.0})
    return {"score": scope["weight"] * delivery["weight"],
            "scope": scope["name"], "delivery": delivery["name"]}


def rank_suggestions(candidates, taxonomy):
    """Rank multi-query matches first, then multiplayer impact, then API order."""
    return [{**card, "_theme_matches": matches} for card, matches, _ in sorted(
        candidates,
        key=lambda row: (-row[1], -impact_for_card(row[0], taxonomy)["score"], row[2]),
    )]


def card_roles(card):
    """Return Commander functional roles used to protect cut candidates."""
    types = card.get("types") or re.split(
        r"\s+", (card.get("type_line") or "").split("—")[0])
    text = oracle_text(card).lower()
    if "Land" in types:
        return ["Lands"]
    roles = []
    if re.search(r"add \{|add (one|two|three|x) mana|create (a|one|two|three|x) treasure tokens?|search your library for .{0,30}(land|plains|island|swamp|mountain|forest) card,? put it onto the battlefield|spells? you cast cost .{0,12} less to cast", text):
        roles.append("Ramp")
    if re.search(r"draw (a|one|two|three|four|five|six|seven|x|\d+|that many) cards?\b|draw cards? equal to", text):
        roles.append("Card draw")
    if re.search(r"destroy all|exile all|each creature|all creatures", text) and re.search(r"destroy|exile|-\d+/-\d+|sacrifices", text):
        roles.append("Board wipes")
    if re.search(r"(destroy|exile|counter|return) target|target .{0,35} (gets? -\d+/-\d+|phases out)|deals? (\d+|x) damage to (any target|target creature)|put target .{0,35} (on the top|on the bottom|into its owner's library)|each opponent sacrifices", text):
        roles.append("Interaction")
    return roles or ["Other"]


def token_linked_draw(card):
    """Return whether a draw engine benefits from token or creature entries."""
    if "Card draw" not in card_roles(card):
        return False
    text = oracle_text(card).lower()
    return bool(re.search(r"token|creatures?.{0,35}enter", text))


def creates_creature_tokens(card):
    return bool(re.search(r"create .{0,40}creature tokens?", oracle_text(card), re.I))


def efficient_role_card(card):
    """Return whether a low-cost card performs a core role efficiently."""
    mana_value = card.get("mana_value", card.get("cmc"))
    return mana_value is not None and mana_value <= 2 and "Ramp" in card_roles(card)


def is_graveyard_recovery(card):
    """Return whether a card restores or reuses cards from the graveyard."""
    text = oracle_text(card).lower()
    return bool(re.search(
        r"from (your|a) graveyard.{0,100}(battlefield|cast)|play lands? from your graveyard",
        text,
    ))


def high_commitment_graveyard_payoff(card, cards, policy):
    """Return whether a scalable one-shot recovery spell merits a review prompt."""
    text = oracle_text(card).lower()
    types = card.get("types") or re.split(
        r"\s+", (card.get("type_line") or "").split("—")[0])
    mana_value = card.get("mana_value", card.get("cmc", 0))
    pips = re.findall(r"\{([WUBRG])\}", card.get("mana_cost", ""))
    overlap = sum(other is not card and is_graveyard_recovery(other) for other in cards)
    settings = policy["high_commitment_graveyard_review"]
    eligible = (
        "Sorcery" in types
        and re.search(r"return any number of .{0,80}from your graveyard", text)
        and mana_value >= settings["minimum_mana_value"]
        and len(pips) >= settings["minimum_colored_pips"]
        and len(set(pips)) >= settings["minimum_distinct_colors"]
        and overlap >= settings["minimum_recovery_overlap"]
    )
    return eligible, overlap


def theme_evidence_for_card(card, theme, taxonomy, tag_index=None):
    """Return strong, weak, or no evidence for one card and active theme."""
    spec = taxonomy["themes"][theme]
    text = oracle_text(card)
    tagged = theme in (tag_index or {}).get(front(card["name"]).lower(), [])
    if tagged:
        return "strong"
    if "strong" in spec or "weak" in spec:
        if re.search("|".join(spec.get("strong", [])) or "(?!x)x", text, re.IGNORECASE):
            return "strong"
        if re.search("|".join(spec.get("weak", [])) or "(?!x)x", text, re.IGNORECASE):
            return "weak"
        return None
    return "strong" if re.search("|".join(spec["detect"]), text, re.IGNORECASE) else None


def functional_role_counts(cards):
    counts = {role: 0 for role in ROLE_TARGETS}
    for card in cards:
        for role in card_roles(card):
            if role in counts:
                counts[role] += card.get("qty", 1)
    return counts


def cut_candidates(cards, suggestions, active_themes, tribal, commanders, taxonomy,
                   tag_index=None, role_counts=None, scale=None):
    """Return cautious, replacement-aware cards for a Commander cut review."""
    if not active_themes and not tribal:
        return []
    policy = taxonomy["cut_candidates"]
    weights = policy["keep_weights"]
    role_counts = role_counts or functional_role_counts(cards)
    scale = scale if scale is not None else min(1, sum(c.get("qty", 1) for c in cards) / 99)
    token_production = any(creates_creature_tokens(card) for card in cards)
    commander_keys = {front(name).lower() for name in commanders}
    tribal_type = tribal[0] if tribal else None
    blink_theme = "Blink / ETB value" in active_themes
    blink_commander = blink_theme and any(
        front(card["name"]).lower() in commander_keys
        and theme_evidence_for_card(card, "Blink / ETB value", taxonomy, tag_index) == "strong"
        and "nonland permanent" in oracle_text(card).lower()
        for card in cards)

    results = []
    for order, card in enumerate(cards):
        name = card["name"]
        if front(name).lower() in commander_keys:
            continue
        roles = card_roles(card)
        if "Lands" in roles:
            continue
        if len([role for role in roles if role in ROLE_TARGETS]) >= 2:
            continue
        if efficient_role_card(card):
            continue
        if token_production and token_linked_draw(card):
            continue
        types = card.get("types") or re.split(
            r"\s+", (card.get("type_line") or "").split("—")[0])
        if blink_commander and "Ramp" in roles and "Artifact" in types:
            continue
        protected = [role for role in roles if role in ROLE_TARGETS
                     and role_counts.get(role, 0) < round(ROLE_TARGETS[role] * scale)]
        if protected:
            continue
        evidence = [theme_evidence_for_card(card, theme, taxonomy, tag_index)
                    for theme in active_themes]
        if blink_commander and evidence.count("weak"):
            evidence = ["strong" if value == "weak" else value for value in evidence]
        high_commitment, recovery_overlap = high_commitment_graveyard_payoff(
            card, cards, policy)
        if "strong" in evidence and not high_commitment:
            continue
        if tribal_type and tribal_type in card.get("subtypes", []):
            continue
        impact = impact_for_card(card, taxonomy)
        if impact["score"] >= policy["meaningful_multiplayer_impact"]:
            continue
        weak = evidence.count("weak")
        if weak:
            continue
        keep_score = weak * weights["active_theme_weak"] + impact["score"]
        reasons = (["strong active-theme evidence"] if high_commitment
                   else ["weak active-theme evidence only"] if weak
                   else ["no active-theme evidence"])
        if high_commitment:
            keep_score -= policy["high_commitment_graveyard_review"]["review_risk"]
            reasons.extend([
                "high mana and color commitment",
                f"one-shot graveyard recovery overlaps {recovery_overlap} other recovery cards",
            ])
        reasons.append("Other functional role" if roles == ["Other"]
                       else ", ".join(roles) + " is above target")
        if not impact["score"]:
            reasons.append("no multiplayer impact")
        results.append({"name": name, "keep_score": keep_score,
                        "reasons": reasons, "roles": roles,
                        "impact": impact, "order": order})
    results.sort(key=lambda item: (item["keep_score"], item["order"]))
    return results[:policy["max_results"]]


def print_cut_candidates(cuts, taxonomy):
    """Print cut candidates as review advice, never as mandatory replacements."""
    print("## Potential cuts to review")
    print("   This is a review aid, not a one-for-one replacement rule.")
    if not cuts:
        print("   No low-confidence cuts found without weakening a protected role.\n")
        return
    for cut in cuts:
        print(f"   - {cut['name']}: {'; '.join(cut['reasons'])}.")
    print()


def deck_card_data(arg, commanders, main):
    """Return per-card data [{name, qty, text, types, subtypes}] for the deck.
    Archidekt decks carry oracle text already; text lists go through Scryfall."""
    m = re.search(r"archidekt\.com/(?:api/)?decks/(\d+)", arg)
    deck_id = m.group(1) if m else (arg if arg.isdigit() else None)
    if deck_id:
        raw = json.loads((CACHE_DIR / f"archidekt_{deck_id}.json")
                         .read_text(encoding="utf-8"))
        excluded = {c["name"] for c in raw.get("categories", [])
                    if not c.get("includedInDeck", True)}
        out = []
        for entry in raw["cards"]:
            cats = entry.get("categories") or []
            if any(cat in excluded for cat in cats):
                continue
            oc = entry["card"]["oracleCard"]
            out.append({"name": oc["name"], "qty": entry["quantity"],
                        "text": oc.get("text") or "",
                        "types": oc.get("types") or [],
                        "subtypes": oc.get("subTypes") or [],
                        "mana_value": oc.get("cmc"),
                        "mana_cost": oc.get("manaCost")})
        return out
    # text decklist: fetch oracle data in batches from Scryfall
    out = []
    names = list(main) + commanders
    for i in range(0, len(names), 75):
        batch = names[i:i + 75]
        resp = http_json("https://api.scryfall.com/cards/collection",
                         {"identifiers": [{"name": n} for n in batch]})
        for c in resp.get("data", []):
            text = c.get("oracle_text") or "\n".join(
                f.get("oracle_text", "") for f in c.get("card_faces", []))
            tl = c.get("type_line", "")
            types = re.split(r"\s+", tl.split("—")[0].strip())
            subtypes = re.split(r"\s+", tl.split("—")[1].strip()) if "—" in tl else []
            out.append({"name": c["name"], "qty": main.get(c["name"], 1),
                        "text": text, "types": types, "subtypes": subtypes,
                        "mana_value": c.get("cmc"),
                        "mana_cost": c.get("mana_cost")})
    return out


def detect_themes(cards, taxonomy, commanders=(), tagged_themes=(), tag_index=None):
    """Return ([(theme, [card names], is_cmdr_theme)...], tribal info or None).
    Themes the commander's own text matches are the build-around signal and
    are always surfaced (with a lower support threshold)."""
    cmdr_keys = {front(c).lower() for c in commanders}
    tagged_themes = set(tagged_themes)
    tag_index = tag_index or {}
    weights = taxonomy.get("weights", {"strong": 2, "weak": 1,
                                        "commander_bonus": 3})
    hits = {}
    for theme, spec in taxonomy["themes"].items():
        weighted = "strong" in spec or "weak" in spec
        strong_pat = re.compile("|".join(spec.get("strong", [])) or "(?!x)x",
                                re.IGNORECASE)
        weak_pat = re.compile("|".join(spec.get("weak", [])) or "(?!x)x",
                              re.IGNORECASE)
        pat = None if weighted else re.compile("|".join(spec["detect"]), re.IGNORECASE)
        tagged_names = {name.lower() for name, themes in tag_index.items()
                        if theme in themes}
        matched, strong_n, weak_n, cmdr_hit = [], 0, 0, False
        for c in cards:
            text, name = c["text"], c["name"]
            is_commander = front(name).lower() in cmdr_keys
            tagged = (front(name).lower() in tagged_names or
                      (is_commander and theme in tagged_themes))
            strong = weighted and bool(strong_pat.search(text))
            weak = weighted and not strong and bool(weak_pat.search(text))
            legacy = not weighted and bool(pat.search(text))
            if not (tagged or strong or weak or legacy):
                continue
            matched.append(name)
            strong_n += int(strong or tagged)
            weak_n += int(weak or legacy)
            cmdr_hit = cmdr_hit or (is_commander and (strong or legacy))
        score = (strong_n * weights["strong"] + weak_n * weights["weak"] +
                 (weights.get("commander_bonus", 3) if cmdr_hit else 0))
        if weighted:
            qualifies = (cmdr_hit and bool(matched)) or (
                strong_n >= taxonomy.get("min_strong", 2) and
                score >= taxonomy["min_cards"])
        else:
            qualifies = len(matched) >= (0 if theme in tagged_themes else
                                        (1 if cmdr_hit else taxonomy["min_cards"]))
        if qualifies:
            hits[theme] = (matched, cmdr_hit, score)
    ranked = sorted(hits.items(), key=lambda kv: (not kv[1][1], -kv[1][2],
                                                   -len(kv[1][0])))
    ranked = [(t, m, ch) for t, (m, ch, _) in ranked]
    ranked = ranked[:taxonomy["max_themes"]]

    trib = taxonomy["tribal"]
    creature_subtypes = {}
    n_creatures = 0
    for c in cards:
        if "Creature" not in c["types"]:
            continue
        n_creatures += 1
        for s in c["subtypes"]:
            creature_subtypes.setdefault(s, []).append(c["name"])
    tribal = None
    ubiq = trib.get("ubiquitous_types", {})
    for top, members in sorted(creature_subtypes.items(), key=lambda kv: -len(kv[1])):
        share_needed = ubiq.get(top, trib["min_share"])
        if (len(members) >= trib["min_count"]
                and len(members) >= share_needed * max(n_creatures, 1)):
            tribal = (top, members)
            break
    return ranked, tribal


def print_themes(deck_name, commanders, main, cards, max_price):
    taxonomy = load_themes()
    tag_index = load_theme_tags()
    tagged = set(tag_index.get(front(commanders[0]).lower(), [])) if commanders else set()
    ranked, tribal = detect_themes(cards, taxonomy, commanders, tagged, tag_index)
    ident = commander_identity(commanders) if commanders else "WUBRG"
    deck_names = {front(n).lower() for n in list(main) + commanders}
    print(f"# Theme analysis — {deck_name} ({', '.join(commanders) or 'no commander'})\n")
    if not ranked and not tribal:
        print("No dominant theme detected — the pile is either too small or "
              "too scattered. Themes need >= "
              f"{taxonomy['min_cards']} matching cards.")
        return
    active = {t for t, _, _ in ranked}
    theme_suggestions = []
    for pair, spec in taxonomy.get("intersections", {}).items():
        a, b = pair.split("|")
        if a in active and b in active:
            print(f"## {spec['label']} (both themes present)")
            theme_suggestions.extend(_suggest(spec["payoffs"], ident, max_price, deck_names))
    for theme, matched, cmdr_hit in ranked:
        flag = " [commander theme]" if cmdr_hit else ""
        print(f"## {theme}{flag} — {len(matched)} cards")
        print(f"   e.g. {', '.join(matched[:6])}")
        spec = taxonomy["themes"][theme]
        queries = [f"otag:{tag}" for tag in spec.get("oracle_tags", [])]
        queries += spec["payoffs"]
        theme_suggestions.extend(_suggest(queries, ident, max_price, deck_names))
    if tribal:
        ttype, members = tribal
        print(f"## {ttype} tribal — {len(members)} creatures")
        print(f"   e.g. {', '.join(members[:6])}")
        queries = [q.replace("{TYPE}", ttype) for q in taxonomy["tribal"]["payoffs"]]
        theme_suggestions.extend(_suggest(queries, ident, max_price, deck_names))
    print_cut_candidates(
        cut_candidates(cards, theme_suggestions, active, tribal, commanders,
                       taxonomy, tag_index), taxonomy)


def _suggest(queries, ident, max_price, deck_names, limit=8):
    taxonomy = load_themes()
    cards = suggestion_cards(queries, ident, max_price, deck_names, limit)
    for c in cards:
        price = c.get("prices", {}).get("usd")
        text = (c.get("oracle_text")
                or " // ".join(f.get("oracle_text", "")
                               for f in c.get("card_faces", []))).replace("\n", " ")
        print(f"   + {c['name']} ({c.get('mana_cost', '?')})"
              f"{' $' + price if price else ''}")
        impact = impact_for_card(c, taxonomy)
        if impact["score"]:
            print(f"       Multiplayer impact: {impact['scope']}; {impact['delivery']}")
        print(f"       {text[:140]}")
    print()
    return cards


def suggestion_cards(queries, ident, max_price, deck_names, limit=8):
    """Return unowned suggestions, prioritizing theme fit then multiplayer impact."""
    candidates = {}
    for q in queries:
        full = f"({q}) id<={ident} legal:commander usd<={max_price:g}"
        try:
            results = scryfall_search(full)
        except (TimeoutError, urllib.error.URLError):
            break  # suggestions are optional; return candidates promptly
        for c in results:
            key = front(c["name"]).lower()
            if key in deck_names:
                continue
            if key not in candidates:
                candidates[key] = [c, 0, len(candidates)]
            candidates[key][1] += 1
    return rank_suggestions(candidates.values(), load_themes())[:limit]


def front(name):
    return name.split("//")[0].strip()


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
    taxonomy = load_themes()
    deck_names = set(main) | set(commanders)
    deck_names |= {n.split("//")[0].strip() for n in deck_names}
    print(f"# Finisher suggestions for {deck_name} "
          f"({', '.join(commanders)} — identity {ident})\n")
    for bucket, q in FINISHER_QUERIES.items():
        full_q = f"({q}) id<={ident} legal:commander usd<={max_price:g}"
        cards = scryfall_search(full_q)
        fresh = [c for c in cards
                 if c["name"] not in deck_names
                 and c["name"].split("//")[0].strip() not in deck_names]
        fresh = rank_suggestions(
            [(card, 1, order) for order, card in enumerate(fresh)], taxonomy)[:8]
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
            impact = impact_for_card(c, taxonomy)
            if impact["score"]:
                print(f"      Multiplayer impact: {impact['scope']}; {impact['delivery']}")
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


def print_report(rep, show_infinite=False, max_price=DEFAULT_MAX_PRICE):
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
    ap.add_argument("command",
                    choices=["fetch", "combos", "wincons", "finishers", "themes"])
    ap.add_argument("deck", help="Archidekt ID/URL or path to text decklist")
    ap.add_argument("--show-infinite", action="store_true")
    ap.add_argument("--max-price", type=float, default=DEFAULT_MAX_PRICE)
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
    if args.command == "themes":
        cards = deck_card_data(args.deck, commanders, main_cards)
        print_themes(name, commanders, main_cards, cards, args.max_price)
        return

    rep = build_report(name, commanders, main_cards,
                       wincons_only=(args.command == "wincons"))
    if args.as_json:
        json.dump(rep, sys.stdout, indent=1)
    else:
        print_report(rep, show_infinite=args.show_infinite, max_price=args.max_price)


if __name__ == "__main__":
    main()
