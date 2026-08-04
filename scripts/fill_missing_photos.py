#!/usr/bin/env python3
"""Fill missing option photos from each place's own page, then Wikimedia by name.

    python3 scripts/fill_missing_photos.py [--limit N] [--dry-run]

Order of attempt for every option that still has no photo:

  1. OpenGraph / Twitter image on official_url or source_url (the place's own photo)
  2. Wikipedia search by name, validated against the option's coordinates when we have them
  3. Leave blank — better than a wrong picture

Tours, workshops and food-experiences are skipped: they don't have a single place photo.
Google Maps gallery scraping is intentionally not done (ToS); if you want Google Place
photos specifically, set GOOGLE_PLACES_API_KEY and use scripts/fetch_google_places.py.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# Reuse the matching helpers we already trust.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_images import (  # noqa: E402
    ApiError, CACHE, DATA, NOT_A_PHOTO, PAUSE, REPO, UA, WIKI,
    credit_for, download, get, is_wrong_subject, page_image, score,
)

SKIP_KINDS = {"tour", "workshop", "food-experience"}
MAX_DISTANCE_M = 2500  # name-search articles must still be near the option when we have coords


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image: str | None = None
        self.title: str = ""

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs}
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"} and a.get("content"):
                if not self.image:
                    self.image = a["content"].strip()
        if tag == "title" and not self.title:
            self._capture = True

    def handle_data(self, data):
        if getattr(self, "_capture", False):
            self.title += data
            self._capture = False


def fetch_html(url: str) -> str | None:
    if not url or not url.startswith("http"):
        return None
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en,ja;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                return None
            raw = r.read(400_000)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return None


def og_image(url: str) -> tuple[str, str] | None:
    html = fetch_html(url)
    if not html:
        return None
    p = MetaParser()
    try:
        p.feed(html)
    except Exception:
        return None
    if not p.image:
        return None
    img = urllib.parse.urljoin(url, p.image)
    # Skip tiny icons / SVGs / tracking pixels
    low = img.lower()
    if any(x in low for x in (".svg", "logo", "icon", "sprite", "1x1", "pixel", "favicon")):
        return None
    return img, (p.title or url)[:120]


def wiki_name_search(name: str, city: str) -> list[dict]:
    """Search Wikipedia by name; prefer results that mention Japan / the city."""
    try:
        r = get(WIKI, {
            "action": "query", "list": "search",
            "srsearch": f"{name} {city} Japan".strip(),
            "srlimit": 8, "srnamespace": 0,
        })
    except ApiError:
        return []
    return r.get("query", {}).get("search", [])


def wiki_coords(title: str) -> tuple[float, float] | None:
    try:
        r = get(WIKI, {
            "action": "query", "prop": "coordinates", "titles": title, "redirects": 1,
        })
    except ApiError:
        return None
    for p in r.get("query", {}).get("pages", {}).values():
        coords = p.get("coordinates") or []
        if coords:
            return coords[0]["lat"], coords[0]["lon"]
    return None


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import radians, sin, cos, asin, sqrt
    lat1, lon1, lat2, lon2 = map(radians, [*a, *b])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def try_og(o: dict, dry: bool) -> dict | None:
    for url in (o.get("url"),):
        if not url:
            continue
        got = og_image(url)
        time.sleep(0.4)
        if not got:
            continue
        img_url, title = got
        rel = f"images/options/{o['slug']}.jpg"
        if not dry and not download(img_url, REPO / rel):
            # some CDN hotlinks need a referer; try once more with one
            req_headers_ok = False
            try:
                req = urllib.request.Request(img_url, headers={
                    "User-Agent": UA, "Referer": url,
                })
                with urllib.request.urlopen(req, timeout=45) as r:
                    blob = r.read()
                if len(blob) >= 4000:
                    (REPO / rel).parent.mkdir(parents=True, exist_ok=True)
                    (REPO / rel).write_bytes(blob)
                    req_headers_ok = True
            except Exception:
                pass
            if not req_headers_ok:
                continue
        return {
            "src": rel,
            "article": url,
            "articleTitle": title or o["name"],
            "distanceM": 0,
            "artist": title or "official site",
            "license": "from official/source page (private trip use)",
            "licenseUrl": url,
            "page": url,
            "source": "og",
        }
    return None


def try_wiki_name(o: dict, used: set[str], dry: bool) -> dict | None:
    results = wiki_name_search(o["name"], o.get("city") or "")
    time.sleep(PAUSE)
    best, best_score, best_dist = None, 0.0, None
    for r in results:
        title = r["title"]
        if title in used or is_wrong_subject(title, o):
            continue
        s = score(o["name"], title)
        if s < 0.55:
            continue
        dist = None
        if o.get("lat") and o.get("lng"):
            coords = wiki_coords(title)
            time.sleep(PAUSE)
            if coords:
                dist = haversine_m((o["lat"], o["lng"]), coords)
                if dist > MAX_DISTANCE_M:
                    continue
        if s > best_score:
            best, best_score, best_dist = title, s, dist
    if not best:
        return None
    got = page_image(best)
    time.sleep(PAUSE)
    if not got:
        return None
    thumb, file_title = got
    if NOT_A_PHOTO.search(file_title.replace("_", " ")):
        return None
    rel = f"images/options/{o['slug']}.jpg"
    if not dry and not download(thumb, REPO / rel):
        return None
    try:
        credit = credit_for(file_title)
    except ApiError:
        credit = {"artist": "", "license": "", "licenseUrl": "",
                  "page": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(file_title)}"}
    time.sleep(PAUSE)
    return {
        "src": rel,
        "article": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(best.replace(' ', '_'))}",
        "articleTitle": best,
        "distanceM": round(best_dist) if best_dist is not None else None,
        **credit,
        "source": "wikipedia-name",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    used = {o["image"]["articleTitle"] for o in data["options"]
            if o.get("image") and o["image"].get("articleTitle")}

    todo = [o for o in data["options"]
            if not o.get("image") and o["kind"] not in SKIP_KINDS]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(todo)} options without a photo (skipping tours/workshops/food)"
          + (" · dry run" if args.dry_run else ""))
    hits = misses = 0

    for i, o in enumerate(todo, 1):
        image = None
        # Prefer the place's own photo when we have a URL.
        if o.get("url"):
            image = try_og(o, args.dry_run)
            if image:
                print(f"  [{i}/{len(todo)}] ✓ {o['name']} <- official page")
        if not image:
            image = try_wiki_name(o, used, args.dry_run)
            if image:
                print(f"  [{i}/{len(todo)}] ✓ {o['name']} <- {image['articleTitle']}"
                      + (f" ({image['distanceM']}m)" if image.get("distanceM") is not None else ""))
        if not image:
            misses += 1
            print(f"  [{i}/{len(todo)}] – {o['name']}")
            continue

        o["image"] = image
        cache[o["name"]] = image
        if image.get("articleTitle"):
            used.add(image["articleTitle"])
        hits += 1

        if i % 20 == 0 and not args.dry_run:
            data["counts"]["withPhoto"] = sum(1 for x in data["options"] if x.get("image"))
            DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    data["counts"]["withPhoto"] = sum(1 for x in data["options"] if x.get("image"))
    if not args.dry_run:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        # refresh the attribution table
        from export_from_vault import write_attribution
        write_attribution(data["options"])

    print(f"\nfilled {hits} · still blank {misses} · "
          f"{data['counts']['withPhoto']}/{len(data['options'])} options now have a photo")


if __name__ == "__main__":
    main()
