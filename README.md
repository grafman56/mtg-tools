# mtg-tools

Deck-building helper for casual Commander decks. It answers one question: "my
deck does not close games, what should I add?" It finds combos already in a
deck and one card away, detects the deck's themes, and suggests **finite** (non-
infinite) game-enders in the deck's colors and budget, ranked by what people
actually play. When theme fit ties, multiplayer suggestions rank table-wide
effects above target-opponent effects. The output explains the detected scope
and delivery type. Theme analysis also shows conservative potential cuts to
review when an unprotected card has weak theme support and a higher-value
incoming suggestion exists.

It is a recommender, not a rules engine. The work is done by three community
services (Scryfall for cards, Commander Spellbook for combos, EDHREC for
popularity); this project is the thin layer on top that filters to finite wins,
detects themes, and ranks suggestions.

Live web app: **https://grafman56.github.io/mtg-tools/**

## Two ways to use it

### Command line (`decktool.py`)

Python 3.10+, no dependencies beyond the standard library.

```
python decktool.py fetch      <deck>   # normalized decklist
python decktool.py combos     <deck>   # combos in deck + one card away
python decktool.py wincons    <deck>   # only combos that end the game
python decktool.py finishers  <deck>   # finite, non-combo game-enders (EDHREC-ranked)
python decktool.py themes     <deck>   # dominant themes + payoffs keyed to them
```

`<deck>` is an Archidekt ID, an Archidekt URL, or a path to a text list
(`1x Card Name` per line, commander marked `*CMDR*` or under a `Commander`
header).

Flags: `--show-infinite` (infinite combos are collapsed by default),
`--max-price N` (default $100), `--json` (raw report for piping).

### Web app (`docs/index.html`)

One self-contained HTML file, no backend. Paste any pile of cards (a theme seed
or a full deck) and an optional commander, and it shows deck health against a
standard Commander baseline, combos in the pile, finite one-card-away combos,
theme detection, EDHREC synergy picks, and finite finishers under a price cap.
Both deck-health categories and detected themes have expandable evidence lists,
so every classification can be checked without cluttering the default view.
Card names in those lists link to Scryfall using URLs already returned by the
batched lookup; displaying the links makes no additional network requests.
Cards banned in Commander are flagged at the top and beside their names, but
analysis continues. Functional roles may overlap: for example, a mana rock that
also draws a card can count as both Ramp and Card draw.
Potential cuts are review aids, not mandatory replacements. The tool protects
commanders, lands, under-target baseline roles, active tribal cards, strong
theme evidence, and meaningful table-wide multiplayer effects. It does not rank
cards by mana value alone. A high-cost, color-intensive, one-shot graveyard
payoff can still receive a review prompt when the deck has overlapping graveyard
recovery access. When a commander can blink nonland permanents, the tool also
protects ETB cards, entering-trigger multipliers, and artifact ramp that the
commander can reset, such as Basalt Monolith in a Brago deck.
Lands-matter evidence includes cards that sacrifice lands for recurring value.
The review also retains cards that cover at least two core roles, such as
repeatable Treasure ramp plus card draw. These are safeguards, not claims that
every land-sacrifice or multifunctional card belongs in every deck.
“Other functional roles” does not mean off-theme: death payoffs, copy targets,
and similar build-around cards are listed under their detected themes below the
basic ramp/draw/removal audit. Commander-enabled mechanics receive extra theme
weight, while incidental self-sacrifice wording alone cannot establish an
aristocrats theme.
Theme-query matches provide a bounded strength preference. They do not outrank
a materially broader multiplayer payoff that fills the same purpose. The optional
Oracle Tag index adds semantic role evidence for ramp, draw, removal, board
wipes, and recursion when card wording does not match a local pattern exactly.

Run it locally with `python -m http.server 8420 --directory docs` and open
http://localhost:8420, or just double-click the file. To share, send the file
or point someone at the live URL above.

## Architecture at a glance

Two front-ends (the CLI and the web app) give the same answers because the
knowledge that drives them lives in shared **data files** both read, not in
either program's code:

```
  Archidekt / paste / text  ──normalize──▶  commanders + main
        │                                          │
        ▼                                          ▼
   decktool.py (Python CLI)             Deck Forge (docs/index.html)
        │        both read the shared brain        │
        ├── docs/themes.json  (theme taxonomy) ────┤
        │   docs/combos.json  (combo snapshot) ────┤  (web only)
        ▼                                          ▼
        Scryfall · Commander Spellbook · EDHREC (live APIs)
```

`themes.json` is the seam: define a theme once and both front-ends use it. The
full rationale behind every design choice, and the general programming practices
they illustrate, are in [ARCHITECTURE.md](ARCHITECTURE.md). The short version:

- **Compose community APIs, do not build a rules engine.** The unique value is
  the thin layer on top: finite-only filtering, theme detection, budget/color
  ranking.
- **Shared knowledge lives in JSON both front-ends read**, so the Python CLI and
  the JavaScript web app never drift.
- **The web app ships a precomputed combo snapshot** (`combos.json`) because
  Commander Spellbook's backend blocks browser (CORS) calls. A server would be
  upkeep; a static snapshot is not.
- **A preference is a first-class filter:** infinite combos are detected and
  hidden. The `finishers` command exists because the near-miss combos turned out
  to be almost all infinite, so finite finishers were the real gap.
- **Fuzzy theme detection is checked against known decks** (`validate_themes.py`)
  so tuning the regexes does not silently break archetype detection.
- **Theme payoff suggestions favor cards that satisfy multiple active queries**
  before falling back to Scryfall's EDHREC ordering.

## Data files

- `docs/themes.json` — theme taxonomy: per-theme detection regexes and payoff
  Scryfall queries/Oracle Tags, plus tribal thresholds, theme intersections, and goal
  keywords. Edit this to add or tune a theme; both front-ends pick it up.
- `docs/theme-tags.json` — optional generated Oracle Tag index. It lets both
  front-ends use Scryfall's community-maintained semantic labels as a second
  detection and bounded strength signal without making tag searches during every
  analysis. The builder keeps its source cache in
  `scripts/theme-tag-cache.json`, fetches at most one missing Scryfall tag per
  run, and updates the static browser index only after all requested tags are
  cached. If Scryfall rate-limits a refresh, the published index stays unchanged.
  If the index is absent, the rules-text detector continues to work normally.
- `docs/combos.json` — compact Commander Spellbook snapshot, built by
  `scripts/build_combo_db.py`. Refresh occasionally:

  ```
  curl -o variants.json https://json.commanderspellbook.com/variants.json
  python scripts/build_combo_db.py variants.json
  ```

  Scryfall limits API traffic; do not repeatedly run the tag refresh after a
  429 response. Let the limit clear and try once later.

## Gotchas worth knowing

- Scryfall requires **both** a `User-Agent` and an `Accept` header, or it returns
  400.
- A full deck lookup is batched at 75 names per Scryfall collection request
  (normally two requests for Commander), never one request per card. Optional
  recommendation searches time out/fail soft so a slow API cannot hold the
  entire analysis open indefinitely.
- Archidekt categories flagged `includedInDeck: false` (Maybeboard, Sideboard)
  are excluded from the mainboard.
- Double-faced card names are split on `//` to match Spellbook's front-face
  naming.
- The web app cannot import from a deck URL: Archidekt allows CORS only from
  localhost:3000 and Moxfield blocks outside callers, so import is paste-based.
- **TODO — direct deck URL import:** revisit if Archidekt permits this app's
  origin or Moxfield provides supported noncommercial API access. Moxfield's
  undocumented deck endpoints currently require Cloudflare clearance and are
  not a stable foundation for a public static app. Until then, Moxfield's
  More → Export → Copy for Moxfield/plain text is the reliable workflow.

## Known limitations / TODO

- The "Overrun effects" Scryfall bucket surfaces jank and needs tuning.
- The drain-detection regex misses wordy cards like Torment of Hailfire.
- `combos.json` is a snapshot and goes stale between rebuilds.
- Part 2 of the original plan, Forge headless AI-vs-AI simulations (combo
  assembly rate, average win turn vs a baseline), is not built.
