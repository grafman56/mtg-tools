# Architecture and Design Notes

This is the "why." The [README](README.md) covers what the tools do and how to
run them; this covers why they are built the way they are, the tradeoffs behind
each choice, and the general programming practices worth carrying to other
projects. If you come back months later wondering why something is shaped a
certain way, start here.

## 1. The mental model: a recommender, not a rules engine

Deck Forge does not simulate Magic. It never resolves a spell or enforces a
rule. It answers one practical question: "my deck does not close games, what
should I add?" It does that by composing three community services and layering
your preferences on top:

- **Scryfall** for card data and searching by oracle text.
- **Commander Spellbook** for the curated combo database.
- **EDHREC** for "what do people actually play with this commander," used as a
  popularity/synergy ranking.

Everything unique here is the thin layer on top of those: filtering out infinite
combos (you want casual, finite wins), detecting a deck's themes, and ranking
suggestions by "which single card helps most, in budget, in color."

**General lesson:** do not rebuild what a specialized service already does well.
Compose the services and spend your effort on the thin slice of value that is
actually yours. A rules engine would have been months of work to answer a
question three existing APIs already have the data for.

## 2. Two front-ends, one data-defined brain (the seam)

There are two ways to use this: the `decktool.py` command line and the
`docs/index.html` web app ("Deck Forge"). They are completely separate programs
in different languages (Python and browser JavaScript), yet they give the same
answers, because the knowledge that drives them lives in **data files they both
read**, not in either program's code:

```
  Archidekt / paste / text list
            │  (normalize to commanders + main)
            ▼
   ┌─────────────────┐        ┌──────────────────────┐
   │  decktool.py    │        │  Deck Forge (web UI) │
   │  (Python CLI)   │        │  docs/index.html     │
   └────────┬────────┘        └───────────┬──────────┘
            │  both read the shared brain │
            │   docs/themes.json  ────────┤   (theme taxonomy)
            │   docs/combos.json  ────────┤   (combo snapshot, web only)
            ▼                             ▼
   Scryfall · Commander Spellbook · EDHREC (live APIs)
            │                             │
            └──────────▶ suggestions ◀────┘
```

`docs/themes.json` is the **seam**: the agreed-on contract (a taxonomy of themes
with detection regexes and suggestion queries) that both front-ends speak. Add a
theme once, in the JSON, and both the CLI and the web app pick it up. Neither
program owns the definition.

**General lesson:** when two programs must agree on some knowledge, put the
knowledge in a data file they both read, not in one program's code with the
other copying it. A plain JSON file is a language both Python and JavaScript
speak, so it makes a clean seam between them.

## 3. Why the CLI has zero dependencies

`decktool.py` uses only the Python standard library: `urllib` for HTTP, `json`,
`re`. No `requests`, no pip install, nothing to set up or keep updated.

For a small personal tool that mostly makes HTTP calls and parses JSON, the
standard library is enough, and every dependency you add is something that can
break, need updating, or fail to install on a friend's machine. The cost shows
up later, not when you add it.

**General lesson:** add a dependency only when it earns its keep. For a script
this size, "clone and run" with no install step is worth more than the small
convenience a library would add.

## 4. Encoding a preference as a first-class filter, and letting a finding reshape the tool

You want non-infinite win conditions. That preference is not a note in the docs,
it is baked into the logic: a combo is tagged infinite when its Spellbook
`produces` features start with "Infinite"/"Near-infinite," and those are hidden
by default (`--show-infinite` to see them, mainly for spotting cards to cut).

The more interesting part is what building the obvious feature taught us. The
first feature was `combos`: combos in the deck and combos one card away. But
almost every one-card-away combo for your decks turned out to be infinite, which
you do not want. So the near-miss list was mostly useless for your actual goal.
That finding is why the `finishers` and `themes` commands exist: they search
Scryfall for *finite* game-enders (alternate-win cards, table drains, overruns,
extra combats) instead, ranked by EDHREC popularity, filtered to your colors and
budget. The most useful feature came from noticing the obvious one did not answer
the real question.

**General lesson:** build the obvious version first, then let what you learn from
it reshape the tool. The gap between "what I built" and "what actually helped" is
usually where the real feature is hiding.

## 5. The CORS wall and the static combo snapshot

This is the decision most worth remembering. Commander Spellbook's backend only
allows browser requests (CORS) from localhost and its own site. So the CLI can
call `find-my-combos` live, but the hosted web app on GitHub Pages cannot: the
browser blocks it.

Rather than stand up a server to proxy the call (infrastructure to run and
maintain), the web app ships a **precomputed snapshot**. `scripts/build_combo_db.py`
downloads Spellbook's full bulk export (a 578 MB `variants.json`), throws away
what does not matter (non-commander-legal combos, combos needing six or more
specific cards, anything not marked OK), and writes a compact `docs/combos.json`
(about 26 MB). The web app loads that once and matches combos against your deck
entirely in the browser.

Two techniques worth stealing are in that script:

- **Filter to what matters before you ship it.** Most of the 578 MB is combos
  that will never apply. Cutting them first is what makes a browser-loadable file
  possible.
- **Compress the schema.** The output uses one-letter keys (`c` cards, `p`
  produces, `i` id, `o` popularity, `d` color identity, `$` price) and omits
  fields at their default. On a 98,000-record file, short keys save real
  megabytes over descriptive ones. This is a place where terseness pays; the
  README and this doc are where you explain what the letters mean.

The tradeoff is that the snapshot goes stale as new combos are published, so it
is regenerated occasionally (the same "cached data needs a freshness policy"
idea that shows up as the 90-day TTL in the CarPartScraper project).

**General lesson:** a platform boundary like CORS is a security rule, not a bug
to fight. Work within it. When you cannot query a service live, precompute a
snapshot, trim it to what you actually need, and give it a refresh cadence.

## 6. Validating fuzzy logic against known-good cases

Theme detection is regex matching against card oracle text, which is inherently
fuzzy: a pattern that is too loose tags every deck as everything, too tight and
it misses real archetypes. `scripts/validate_themes.py` runs detection across 15
real decks whose archetypes are already known (Brago is blink, Prosper is
treasure, Nekusar is wheels, and so on) and prints what it found, so a change to
the taxonomy can be checked against ground truth in one command.

That harness is what surfaced the real tuning lessons: ramp packages were
false-triggering the landfall theme (the "search your library for a land"
pattern had to go), incidental counters were tripping the +1/+1 theme (the regex
now requires "put a +1/+1 counter" or proliferate), auras had to be split from
equipment. None of those were obvious from reading the regexes; they showed up
when detection ran against decks with a known answer.

**General lesson:** when your logic is heuristic rather than exact, build a cheap
way to run it against inputs whose correct answer you already know. It turns
"this regex feels right" into "this regex still classifies all 15 decks
correctly," which is the difference you feel the next time you change it.

## 7. Weighting by domain knowledge

Not every card is an equal signal for what a deck is about. The commander defines
the deck, so a theme that the commander's own oracle text matches is treated as
the build-around signal: it is always surfaced and its support threshold drops
from five cards to one. A generic theme needs five cards to count; a theme the
commander itself enables needs almost none.

**General lesson:** when you rank or detect, let real domain knowledge tilt the
weights. A flat count treats a 99-card pile and the one card that defines the
strategy the same, which is usually wrong.

## 8. Normalizing messy input at the boundary

Deck lists arrive in many shapes, and all the mess is handled once, at the point
of entry, so the rest of the code sees clean data:

- Archidekt IDs, Archidekt URLs, and local text lists all normalize to the same
  `(name, commanders, main)` shape.
- Double-faced cards ("Glasspool Mimic // Glasspool Shore") are split on `//` so
  a name matches Spellbook's front-face naming.
- The web paste box understands Archidekt, Moxfield, and MTGA export formats,
  stripping set codes, collector numbers, foil flags, and `[Category]` tags.
- Misspelled names get a second pass through Scryfall's fuzzy endpoint.
- Archidekt categories flagged `includedInDeck: false` (Maybeboard, Sideboard)
  are dropped from the mainboard.

**General lesson:** clean the data once, at the boundary, and let everything
downstream assume it is clean. Scattering "but what if the name has a slash"
checks through the whole codebase is how you get bugs.

## 9. Rankings encode a judgment, so make them legible

The one-card-away list is not sorted by combo count. It is sorted by "which
single purchase unlocks the most *finite, game-ending* combos," then by finite
combo count, then by popularity. That ordering is the actual advice: spend one
card to close the most games. Theme suggestions first favor cards that satisfy
multiple active queries. Tied cards then favor broader multiplayer reach, such
as "each opponent" over "target opponent," and repeatable triggers over one-shot
effects. Scryfall's EDHREC order remains the final tie-breaker, which favors
cards that people actually play with the commander rather than random legal
matches.

**General lesson:** a sort key is an opinion about what matters. Write the opinion
down (in a comment, in the docs) so the next person understands the advice the
ranking is really giving, instead of treating it as an arbitrary order.

Potential cuts use the opposite, conservative comparison. A card must have no
strong active-theme or tribal evidence, no protected functional role, and no
meaningful multiplayer impact before the tool can flag it. Weak theme evidence
is protected in this first pass. The tool lists additions separately, because a
potential cut does not prove that one specific incoming card is its replacement.
The result remains a review aid because Oracle-text heuristics cannot prove that
a card is bad in a specific deck. Mana value stays out of this comparison until
the tool has deck curve and effect-size context.

Commander context can strengthen this protection. A commander that can blink
nonland permanents makes ETB cards and artifact ramp deck-specific resources.
The cut review protects those cards rather than treating them as generic surplus.
Incoming replacements must also show active-theme or tribal evidence, so a card
such as Psychosis Crawler cannot become a generic replacement in a blink deck.

## 10. Zero-backend, static hosting

Deck Forge is one self-contained HTML file with its CSS and JS inline. GitHub
Pages serves it straight from `main:/docs`, and the browser does all the work by
calling Scryfall and EDHREC directly (both allow cross-origin requests) and
loading the local `combos.json`. There is no server to run, no database, no
deploy step beyond a git push. Sharing it with a friend is sending one file or a
URL.

**General lesson:** if the work can happen in the browser and the data sources
allow cross-origin calls, a static file is a complete app with zero hosting cost.
Reach for a backend only when you truly need one (secrets, a private database, a
service that blocks CORS, which is exactly why the combo data had to be
snapshotted instead of called live).

## 11. Module and data map

| File | Role | Notes |
|------|------|-------|
| `decktool.py` | The CLI: `fetch`, `combos`, `wincons`, `finishers`, `themes` | Stdlib only. Calls Spellbook live. |
| `docs/index.html` | Deck Forge web app | Self-contained, zero backend, uses the combo snapshot. |
| `docs/themes.json` | Theme taxonomy (detect regexes + payoff queries + tribal + intersections + goals) | The shared brain. Read by both front-ends. Data, not code. |
| `docs/combos.json` | Compact Spellbook snapshot | Built by the script below, matched client-side because of CORS. |
| `scripts/build_combo_db.py` | Distills Spellbook's 578 MB export into the ~26 MB snapshot | Re-run occasionally to refresh. |
| `scripts/validate_themes.py` | Runs theme detection over known decks | Cheap regression check for the fuzzy taxonomy. |

## 12. Programming practices demonstrated here

- **Compose, do not rebuild** (§1): layer thin, unique value over specialized
  services instead of reimplementing them.
- **Data-defined seams / single source of truth** (§2, §5): shared knowledge
  lives in JSON both front-ends read, so they cannot drift.
- **Right-size dependencies** (§3): stdlib-only where that is enough.
- **Let findings reshape the tool** (§4): the useful feature came from the
  obvious one falling short.
- **Respect platform boundaries; precompute when you cannot query** (§5): the
  CORS wall, solved with a trimmed, schema-compressed snapshot.
- **Test heuristics against known-good cases** (§6): the theme validation harness.
- **Weight by domain knowledge** (§7): the commander as the build-around signal.
- **Normalize at the boundary** (§8): all the input mess handled once, up front.
- **Legible rankings** (§9): the sort key is the advice; state it.
- **Static over server** (§10): free hosting, no ops, when the browser can do it.
- **Be a good API citizen**: descriptive User-Agent with a contact, the headers
  Scryfall requires, batching lookups (75 names per call), treating a 404 as an
  empty result.

## 13. Known limitations

- The "Overrun effects" Scryfall bucket surfaces jank; EDHREC ordering is weak
  there and the query needs tuning.
- The drain-detection regex misses wordy cards like Torment of Hailfire ("Repeat
  the following process..."), which do not phrase the effect the way the pattern
  expects.
- `combos.json` is a snapshot and goes stale between rebuilds.
- The browser cannot import from a deck URL directly: Archidekt allows CORS only
  from localhost:3000 and Moxfield blocks outside callers, so the web app is
  paste-based by necessity.
- Direct URL import remains a TODO, contingent on supported cross-origin API
  access. In particular, Moxfield's undocumented endpoint is protected by
  Cloudflare; bypassing that from a static client would be brittle and
  inappropriate. Plain-text export stays the dependable fallback.
- Part 2 of the original plan (Forge headless AI-vs-AI simulations to measure
  combo assembly rate and average win turn against a baseline deck) is not built.
