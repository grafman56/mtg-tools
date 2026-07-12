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

Flags: `--show-infinite` (Paul avoids infinite combos, so they're collapsed by
default), `--max-price N` (default $20), `--json` (raw report).

## Design notes

- Infinite combos are detected via Spellbook `produces` features starting with
  "Infinite"/"Near-infinite" and hidden by default — Paul's core preference.
- Key learning: for most of Paul's decks, Commander Spellbook near-misses are
  almost all infinite. The real gap is *finite finishers*, hence the
  `finishers` command: bucketed Scryfall searches (alt-win, drain, burn,
  overrun, extra combat, mass evasion) in the commander's color identity,
  ordered by EDHREC rank, excluding cards already in the deck.
- Archidekt categories with `includedInDeck: false` (Maybeboard etc.) are
  excluded from the mainboard.
- Scryfall requires both User-Agent and Accept headers.

## Paul's decks (Archidekt folder 163818)

Ever Changing 23718180 · Mimeoplasm 14392139 · Brago 14179968 · Bruenor
14422119 · Prosper 14181420 · Wilhelt 14424067 · Nekusar 13865790 · Obuun
14427307 · Vadrick 14545722 · Anowon 14429038 · Siona 14423840 · Coven
Counters 14402209 · Vorel Counters 14090810 · Rafiq 14179232 · Raggadragga
14392356 · Varolz JANK 13904010

## TODO

- Tune the "Overrun effects" Scryfall bucket (surfaces jank; EDHREC order not
  great there).
- Regex misses wordy drains like Torment of Hailfire ("Repeat the following
  process...").
- Part 2: Forge .dck export + headless sim harness (combo assembly rate,
  average win turn vs a baseline deck).
