# Japan 2026 — options by hub

A small static site that makes our trip research readable by people who aren't in the
planning weeds. For every town we might sleep in, it lists the things we could do from
there: **what it is in one line, how long it takes, and whether late May is a good time
for it.**

Nothing on the site is booked. It exists so everyone can see what a place actually
involves before we commit nights to it.

## Where the content comes from

The site does not have its own copy of the trip content. It is generated from the
Obsidian planning vault next door, which stays the single source of truth:

| Vault file | Becomes |
|---|---|
| `Japan/Items/*.md` | one option card — description, hours, booking, coordinates |
| `Japan/Planning/Hubs/**.md` | the hubs, their day trips, and the day-plan packages |
| `Japan/Planning/item_packages.tsv` | which options each package covers |
| `Japan/Planning/00 After Kyoto Tracks.md` | which track a hub belongs to |
| `Japan/Planning/Media/**` | hub and day-trip photos |

Everything lands in one file, `data/trip.json`, which the page fetches on load.

## Regenerating

```bash
python3 scripts/export_from_vault.py          # vault -> data/trip.json
python3 scripts/fetch_images.py               # add missing photos (slow, rate-limited)
```

`export_from_vault.py` assumes the vault is at `../JapanPlanning`; pass `--vault` if it
moved. It never writes to the vault. Photos already attached to an option are preserved
across re-exports.

## Photos

Options are photographed from Wikimedia Commons, but a wrong photo is worse than no
photo, so a candidate has to pass two tests before it is used:

1. Wikipedia's geosearch finds the article **within 900 m of the option's own
   coordinates**, which we already store in the vault.
2. The article title actually matches the option name — with an explicit rule against
   a town's own article, so "Kochi Castle" can't quietly inherit a photo of Kōchi city.

Anything that fails is left with a generated placeholder tile. Options with no
coordinates, and things that aren't places at all (tours, cooking classes), are never
looked up. Each photo keeps its author and licence and shows them on the option.

Useful flags:

```bash
python3 scripts/fetch_images.py --dry-run     # match without downloading
python3 scripts/fetch_images.py --recheck     # retry previous misses
python3 scripts/fetch_images.py --revalidate  # drop photos that fail current rules
```

## Running it locally

There is no build step — it's HTML, one CSS file, and one JS file. But the page fetches
JSON, which browsers block on `file://`, so serve the folder:

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>.

## Deploying

Push to GitHub and turn on **Settings → Pages → Deploy from a branch → `main` / root**.
No workflow or bundler needed.

## Licence

Site code is MIT (`LICENSE`). The planning notes are ours. Photos belong to their
respective Wikimedia Commons authors under the licences shown on each option —
see [`ATTRIBUTION.md`](ATTRIBUTION.md).
