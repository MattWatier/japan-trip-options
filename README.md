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

Options get a photo in this order:

1. **Already attached** Wikimedia Commons photos (matched by coordinates).
2. **`fill_missing_photos.py`** — the place's own `og:image`, then a Wikipedia
   name search validated against coordinates.
3. **`fetch_google_places.py`** — Google Places (New) photos, the same pictures
   that show up on Google Maps. Needs a free API key (see below).

Tours, workshops and food experiences stay blank on purpose — they aren't a
single place. A blank tile beats a wrong picture.

```bash
python3 scripts/fetch_images.py               # Wikimedia by coordinates
python3 scripts/fill_missing_photos.py        # official sites + Wikipedia by name
# optional, for the remaining gaps:
export GOOGLE_PLACES_API_KEY=...              # Places API (New) on Google Cloud
python3 scripts/fetch_google_places.py
```

Useful flags on the Wikimedia script:

```bash
python3 scripts/fetch_images.py --dry-run
python3 scripts/fetch_images.py --recheck
python3 scripts/fetch_images.py --revalidate
```

### Google Places key (optional)

1. Open [Places API (New)](https://console.cloud.google.com/apis/library/places.googleapis.com) and enable it.
2. Create an API key and (optionally) restrict it to Places API.
3. Put it in `.env` as `GOOGLE_PLACES_API_KEY=...` or export it, then run
   `fetch_google_places.py`.

Photos from Google stay marked for **private trip use only** in the attribution
file. Don't republish the site publicly with those photos without checking Google's
geo guidelines.

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
