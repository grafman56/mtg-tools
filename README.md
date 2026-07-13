# mtg-tools

Deck-building helper for Paul's Commander decks. Part 1 of the two-part plan
(part 2 = Forge headless AI-vs-AI feasibility sims, not started).

## decktool.py

No dependencies beyond stdlib (Python 3.10+). Data sources: Archidekt API
(decklists), Commander Spellbook API (combos), Scryfall API (finisher search).

```
python decktool.py fetch 23718180          # normalized decklist from Archidekt
python decktool.py combos 23718180         # combos in deck + 1 card away
python decktool.py wincons 23718180        # only combos that end the game
python decktool.py finishers 23718180     # non-combo finite game-enders, EDHREC-ranked
```

Deck argument: Archidekt ID, Archidekt URL, or path to a local text list
(`1x Card Name`, commander marked `*CMDR*`).

Flags: `--show-infinite` (collapsed by
default), `--max-price N` (default $20), `--json` (raw report).

## Design notes

- Infinite combos are detected via Spellbook `produces` features starting with
  "Infinite"/"Near-infinite" and hidden by default
- Key learning: Commander Spellbook near-misses are
  almost all infinite. The real gap is *finite finishers*, hence the
  `finishers` command: bucketed Scryfall searches (alt-win, drain, burn,
  overrun, extra combat, mass evasion) in the commander's color identity,
  ordered by EDHREC rank, excluding cards already in the deck.
- Archidekt categories with `includedInDeck: false` (Maybeboard etc.) are
  excluded from the mainboard.
- Scryfall requires both User-Agent and Accept headers.

## TODO

- Tune the "Overrun effects" Scryfall bucket (surfaces jank; EDHREC order not
  great there).
- Regex misses wordy drains like Torment of Hailfire ("Repeat the following
  process...").
- Part 2: Forge .dck export + headless sim harness (combo assembly rate,
  average win turn vs a baseline deck).

## Web UI (docs/index.html)

Single self-contained HTML file, zero backend — the browser calls Scryfall and
Commander Spellbook directly (both are CORS-open). Paste any pile of cards
(theme seed or full deck), optional commander, and it shows: deck health vs
the standard Commander baseline (37 lands / 10 ramp / 10 draw / 10
interaction, scaled to pile size), combos in the pile, finite one-card-away
combos, and EDHREC-ranked finite finishers under a price cap. Infinites
hidden by default.

Run locally: `python -m http.server 8420 --directory docs` then open
http://localhost:8420 — or just double-click the file. To share with a
friend: send them the file, or enable GitHub Pages on this repo.

## Theme-aware suggestions (v0.3)

`python decktool.py themes <deck>` and the web UI's "Themes in this pile"
section detect the deck's dominant mechanics via the oracle-text taxonomy in
docs/themes.json (17 themes + dynamic tribal detection with a higher bar for
ubiquitous types like Human), then suggest payoffs keyed to those mechanics
instead of generic color staples. Validated against all 15 real decks —
each detected its known archetype. The web UI also shows EDHREC synergy
picks for the commander (json.edhrec.com is CORS-open; synergy = played
far more with this commander than elsewhere).

## v0.4: commander-weighted themes, intersections, goal box

- The commander's own oracle text is the build-around signal: themes it
  matches are always surfaced (support bar drops to 2 cards) and tagged.
- New themes: Theft / mind control, Exile / impulse draw.
- themes.json "intersections": when two themes co-occur (clones+sac,
  theft+sac, theft+clones, treasure+sac, exile+treasure), cards serving both
  mechanics are suggested first.
- Web UI goal box: describe the gameplan in words ("steal creatures,
  sacrifice them, become them") — keyword map in themes.json "goals" forces
  those themes even in an empty pile. Plain keyword matching, not NLP.

## v0.5 (branch: import + fuzzy names + theme picker)

- Paste importer understands Archidekt "Export → Text" and Moxfield/MTGA
  formats: set codes, collector numbers, foil flags, and [Category] tags are
  stripped; [Commander] auto-fills the commander field; Maybeboard/Sideboard
  sections are skipped. Direct URL import is impossible from the browser —
  Archidekt CORS-allows only localhost:3000 and Moxfield 403s outside callers.
- Misspelled names get a second chance through Scryfall's fuzzy endpoint
  (capped at 15 per run) and show as "Auto-corrected: X → Y".
- "Or pick themes to build toward…" checkbox picker forces themes, same as
  the goal box.
