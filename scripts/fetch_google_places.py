#!/usr/bin/env python3
"""Attach Google Places photos to options that still have none.

    export GOOGLE_PLACES_API_KEY=...
    python3 scripts/fetch_google_places.py [--limit N] [--dry-run]

Uses the official Places API (New) Text Search + Place Photos endpoints —
the same photos that appear on Google Maps for a place, without scraping Maps.

Enable "Places API (New)" on a Google Cloud project, create an API key, and
restrict it to Places if you like. For a private family trip the free monthly
credit is plenty.

Skipped: tours, workshops, food-experiences (no single place photo).
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data/trip.json"
CACHE = REPO / "scripts/.google_places_cache.json"
UA = "JapanTripOptions/1.0 (private family trip planner)"
SKIP = {"tour", "workshop", "food-experience"}
SEARCH = "https://places.googleapis.com/v1/places:searchText"
PAUSE = 0.35


def places_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")
    if key:
        return key
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GOOGLE_PLACES_API_KEY=") or line.startswith("GOOGLE_MAPS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(
        "Set GOOGLE_PLACES_API_KEY (or put it in .env). "
        "Enable Places API (New) at https://console.cloud.google.com/apis/library/places.googleapis.com"
    )


def api(method: str, url: str, key: str, body: dict | None = None, field_mask: str = "") -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {
        "User-Agent": UA,
        "X-Goog-Api-Key": key,
        "Content-Type": "application/json",
    }
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def find_place(o: dict, key: str) -> dict | None:
    query = f"{o['name']} {o.get('city') or ''} Japan".strip()
    body: dict = {
        "textQuery": query,
        "languageCode": "en",
        "maxResultCount": 3,
    }
    if o.get("lat") and o.get("lng"):
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": o["lat"], "longitude": o["lng"]},
                "radius": 1500.0,
            }
        }
    try:
        r = api("POST", SEARCH, key, body,
                "places.id,places.displayName,places.photos,places.location,places.formattedAddress")
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:300]
        raise RuntimeError(f"Places search failed for {o['name']}: {exc.code} {err}") from exc
    places = r.get("places") or []
    if not places:
        return None
    # Prefer a result whose display name overlaps the option name.
    name = o["name"].lower()
    for p in places:
        dn = (p.get("displayName") or {}).get("text", "").lower()
        if name.split()[0] in dn or dn.split()[0] in name:
            if p.get("photos"):
                return p
    for p in places:
        if p.get("photos"):
            return p
    return None


def download_photo(photo_name: str, key: str, dest: Path) -> bool:
    # photo_name looks like "places/ChIJ.../photos/..."
    url = (f"https://places.googleapis.com/v1/{photo_name}/media"
           f"?maxHeightPx=900&maxWidthPx=1200&key={urllib.parse.quote(key)}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        if len(blob) < 4000:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        return True
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    key = places_key()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [o for o in data["options"]
            if not o.get("image") and o["kind"] not in SKIP]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(todo)} options to try via Google Places"
          + (" · dry run" if args.dry_run else ""))
    hits = misses = errors = 0

    for i, o in enumerate(todo, 1):
        if o["name"] in cache and cache[o["name"]] is None:
            # prior confirmed miss
            misses += 1
            print(f"  [{i}/{len(todo)}] – {o['name']} (cached miss)")
            continue
        try:
            place = find_place(o, key)
        except RuntimeError as exc:
            errors += 1
            print(f"  [{i}/{len(todo)}] ! {o['name']} — {exc}")
            time.sleep(PAUSE)
            continue
        time.sleep(PAUSE)
        if not place or not place.get("photos"):
            misses += 1
            cache[o["name"]] = None
            print(f"  [{i}/{len(todo)}] – {o['name']}")
            continue

        photo = place["photos"][0]
        photo_name = photo["name"]
        attributions = photo.get("authorAttributions") or []
        artist = ", ".join(a.get("displayName", "") for a in attributions if a.get("displayName"))
        rel = f"images/options/{o['slug']}.jpg"
        display = (place.get("displayName") or {}).get("text", o["name"])

        if not args.dry_run:
            if not download_photo(photo_name, key, REPO / rel):
                errors += 1
                print(f"  [{i}/{len(todo)}] ! {o['name']} (photo download failed)")
                continue

        image = {
            "src": rel,
            "article": f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(display)}",
            "articleTitle": display,
            "distanceM": 0,
            "artist": artist or "Google Maps contributor",
            "license": "Google Maps user content (private trip use only)",
            "licenseUrl": "https://www.google.com/permissions/geoguidelines/",
            "page": f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(display)}",
            "source": "google-places",
        }
        o["image"] = image
        cache[o["name"]] = image
        hits += 1
        print(f"  [{i}/{len(todo)}] ✓ {o['name']} <- {display}")

        if i % 25 == 0 and not args.dry_run:
            data["counts"]["withPhoto"] = sum(1 for x in data["options"] if x.get("image"))
            DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    data["counts"]["withPhoto"] = sum(1 for x in data["options"] if x.get("image"))
    if not args.dry_run:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        from export_from_vault import write_attribution
        write_attribution(data["options"])
    print(f"\nfilled {hits} · miss {misses} · errors {errors} · "
          f"{data['counts']['withPhoto']}/{len(data['options'])} with a photo")


if __name__ == "__main__":
    main()
