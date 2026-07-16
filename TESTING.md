# Testing notes

How the automated checks work, and how the machine was set up to run them.
Written as a follow-along so it can be re-read (or redone) later.

There are two harnesses:

| Harness | Language | What it proves | Needs |
|---|---|---|---|
| `scripts/validate_themes.py` | Python only | Theme detection classifies 15 known decks correctly | Python 3 + internet |
| `scripts/theme_parity.py` | Python + Node | The CLI and the web app detect the **same** themes | Python 3 + Node + internet |

The second one is the interesting one: it runs the web app's *actual* JavaScript
(not a reimplementation) and checks it agrees with the Python CLI, deck for deck.
That is the concrete test behind the "two front-ends, one brain" claim in
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Setting up Node (one time)

This machine (PC2) has no `node` and no root access, so Node was installed as a
**user-local binary** under the home directory. Nothing system-wide, no `sudo`,
fully reversible.

Everything below is reproducible. `~/.local/bin` is already on `PATH` here (the
default Ubuntu `~/.profile` adds it), which is why the symlinks are enough to
make `node` available in every new shell.

```bash
# 1. Download the current Node LTS for Linux x64, and VERIFY it against the
#    official checksums before trusting it. (uses python3, already present)
cd /tmp
python3 - <<'PY'
import json, urllib.request, hashlib
get = lambda u: urllib.request.urlopen(
    urllib.request.Request(u, headers={"User-Agent": "curl/8"}), timeout=60).read()
ver = next(r for r in json.loads(get("https://nodejs.org/dist/index.json")) if r["lts"])["version"]
fn  = f"node-{ver}-linux-x64.tar.xz"
data = get(f"https://nodejs.org/dist/{ver}/{fn}")
want = next(l.split()[0] for l in get(f"https://nodejs.org/dist/{ver}/SHASUMS256.txt").decode().splitlines()
           if l.strip().endswith(fn))
assert hashlib.sha256(data).hexdigest() == want, "checksum mismatch!"
open(fn, "wb").write(data)
print("verified and saved", fn)
PY

# 2. Extract into ~/.local/node (strip the top-level folder from the tarball)
rm -rf ~/.local/node && mkdir -p ~/.local/node
tar -xJf /tmp/node-*-linux-x64.tar.xz -C ~/.local/node --strip-components=1

# 3. Expose node/npm/npx on PATH via ~/.local/bin (already on PATH)
ln -sf ~/.local/node/bin/node ~/.local/bin/node
ln -sf ~/.local/node/bin/npm  ~/.local/bin/npm
ln -sf ~/.local/node/bin/npx  ~/.local/bin/npx

# 4. Confirm
node --version    # -> v24.x
npm  --version
```

Installed version at time of writing: **Node v24.18.0 LTS ("Krypton")**, ~203 MB
under `~/.local/node`.

**To remove it:** `rm -rf ~/.local/node ~/.local/bin/node ~/.local/bin/npm ~/.local/bin/npx`

---

## 2. Running the parity harness

```bash
cd ~/projects/mtg-tools
python3 scripts/theme_parity.py
```

Expected tail:

```
PASS  Vorel Counters   +1/+1 counters / proliferate(30)
...
15/15 decks agree between CLI and web
```

Exit code is `0` when all decks agree, non-zero otherwise (so it can gate a
commit). Each line is `THEME(count)`; a `DIFF` line shows the CLI list above the
web list so you can see exactly what diverged.

### How it works

1. `scripts/theme_parity.py` fetches each deck once (Archidekt), runs the Python
   detector (`decktool.detect_themes`), and reshapes the same card data into the
   Scryfall-ish objects the web functions expect.
2. It hands that to `scripts/_theme_parity_run.js`, which loads the **real**
   `docs/index.html` inside a Node `vm` sandbox (with `document`/`fetch` stubbed
   so the page's browser setup doesn't run) and calls the page's own
   `detectThemesJs`.
3. Python diffs the two ordered `(theme, count)` lists per deck.

So both sides consume identical card data; the only thing under test is whether
the two detectors reach the same answer. They must, because the knowledge lives
in `docs/themes.json`, which both read.

### When a DIFF is real

A `DIFF` means the CLI and web genuinely disagree — a drift bug. This harness has
already caught two: a commander-only theme the web dropped (Vadrik / +1/+1) and a
tribal count that skipped the commander. Both were fixed by making the web count
the commander as a deck card, the way the CLI does.

---

## 3. Adding a deck to the tests

Both harnesses share the same list. Add an Archidekt deck id to the `DECKS` dict
in `scripts/validate_themes.py` and `scripts/theme_parity.py`. Pick decks whose
archetype you already know, so a wrong classification is obvious.
