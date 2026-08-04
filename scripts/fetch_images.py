#!/usr/bin/env python3
"""Attach a Wikipedia/Commons photo to each option, validated against its coordinates.

    python3 scripts/fetch_images.py [--limit N] [--dry-run] [--recheck]

Matching a photo by name alone is how you end up with a picture of the wrong Inari
shrine. So every candidate has to survive two tests:

  1. Wikipedia geosearch finds the article within 900m of the option's own lat/lng.
  2. The article title overlaps the option name, or it is the only article within 150m.

Anything that fails both is left without a photo — a blank card beats a wrong one.
Results and misses are cached so re-runs are cheap.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data/trip.json"
OUT = REPO / "images/options"
CACHE = REPO / "scripts/.image_cache.json"

UA = "JapanTripOptions/1.0 (static trip-planning site; contact via GitHub repo)"
WIKI = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
PAUSE = 1.0

# Kinds that plausibly have a photographed, fixed location on Wikipedia.
PLACE_KINDS = {
    "temple", "shrine", "castle", "garden", "park", "museum", "market",
    "neighborhood", "viewpoint", "nature", "hike", "onsen", "island", "theme-park",
}
STOPWORDS = {"the", "of", "and", "a", "in", "at", "japan", "temple", "shrine",
             "park", "garden", "castle", "museum", "market", "street", "area"}


class ApiError(RuntimeError):
    """A network or API failure — distinct from 'looked, found nothing'."""


def get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": UA})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429:
                raise ApiError(f"{url}: {exc}") from exc
            # Anonymous API access gets throttled hard; wait it out properly.
            wait = int(exc.headers.get("Retry-After") or 0) or (5, 15, 40, 90)[attempt]
            print(f"      rate limited, waiting {wait}s")
            time.sleep(wait)
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise ApiError(f"{url} failed after 4 attempts: {last}")


def flatten(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def norm_tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return {t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOPWORDS}


def score(name: str, title: str) -> float:
    """Best of token overlap, whole-string similarity, and containment.

    Whole-string similarity is what rescues the romanisation differences that are
    everywhere here: "Amanoiwato Shrine" vs "Amano-Iwato Shrine", "Dogo" vs "Dōgo".
    """
    a, b = norm_tokens(name), norm_tokens(title)
    token = len(a & b) / len(a | b) if a and b else 0.0
    fa, fb = flatten(name), flatten(title)
    if not fa or not fb:
        return token
    ratio = SequenceMatcher(None, fa, fb).ratio()
    # Containment only counts when the shorter name is most of the longer one.
    # Otherwise "Uji" swallows "Chazuna Tea Park Uji" and every option in the town
    # inherits the same generic city photo.
    short, long = sorted((fa, fb), key=len)
    contain = 0.9 if short in long and len(short) >= 0.6 * len(long) else 0.0
    return max(token, ratio, contain)


# Wikipedia lead "images" are often diagrams. A relief map of a caldera is not a photo
# of the place, and looks broken next to real photography.
NOT_A_PHOTO = re.compile(
    r"\b(map|topograph|relief|locator|location|diagram|chart|plan|flag|seal|emblem|logo|coa)\b",
    re.I,
)


def is_city_article(title: str, o: dict) -> bool:
    """True for the town's own article when the option is something inside the town.

    Wikipedia titles Japanese settlements "Kōchi, Kōchi", so "Kochi Castle" scores a
    perfect token match against the city and inherits a photo of the wrong subject.
    We already know each option's city, so just say no.
    """
    # Ward / district articles: "Hakata-ku, Fukuoka" is not a photo of Hakata food.
    if re.search(r"-\s*ku\s*,", title, re.I) and "ku" not in o["name"].lower():
        return True
    if re.search(r"\b(prefecture|province|city)\b", title, re.I) and flatten(o["name"]) not in flatten(title):
        return True
    head = flatten(title.split(",")[0])
    if not head:
        return False
    name = flatten(o["name"])
    for place in (o.get("city"), o.get("region")):
        if place and head == flatten(place) and name != head:
            return True
    return False


# A railway station next door is almost always the geosearch hit that wins on
# proximity. Only keep it when the option itself is about that station.
INFRA = re.compile(r"\b(station|railway|university|college|hospital|school)\b", re.I)


def is_wrong_subject(title: str, o: dict) -> bool:
    if is_city_article(title, o):
        return True
    if INFRA.search(title) and not INFRA.search(o["name"]):
        return True
    # Kind keyword in the *name* must appear (or a synonym) in the article.
    # Only the name — the kind field is too coarse ("museum" rejects Folk Village).
    # Otherwise "Takachiho Gorge" happily matches "Takachiho Shrine".
    kind_need = {
        "castle": r"\bcastl",
        "shrine": r"\b(shrine|jing[uū]|jinja|taisha)",
        "temple": r"\b(temple|dera)",
        "garden": r"\bgarden",
        "onsen": r"\bonsen",
        "market": r"\bmarket",
        "gorge": r"\b(gorge|valley|canyon)",
    }
    name_l = o["name"].lower()
    title_l = title.lower()
    for word, pat in kind_need.items():
        if word in name_l:
            if not re.search(pat, title_l, re.I) and flatten(o["name"]) not in flatten(title):
                return True
    return False


def geosearch(lat: float, lng: float) -> list[dict]:
    r = get(WIKI, {
        "action": "query", "list": "geosearch",
        "gscoord": f"{lat}|{lng}", "gsradius": 900, "gslimit": 12,
    })
    return r.get("query", {}).get("geosearch", [])


def page_image(title: str) -> tuple[str, str] | None:
    """-> (thumbnail url, commons file title)"""
    r = get(WIKI, {
        "action": "query", "prop": "pageimages", "titles": title,
        "piprop": "thumbnail|name", "pithumbsize": 900, "redirects": 1,
    })
    for p in r.get("query", {}).get("pages", {}).values():
        thumb = p.get("thumbnail", {}).get("source")
        fname = p.get("pageimage")
        if thumb and fname:
            return thumb, f"File:{fname}"
    return None


def credit_for(file_title: str) -> dict:
    out = {"artist": "", "license": "", "licenseUrl": "",
           "page": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(file_title)}"}
    r = get(COMMONS, {
        "action": "query", "prop": "imageinfo", "titles": file_title,
        "iiprop": "extmetadata",
    })
    for p in r.get("query", {}).get("pages", {}).values():
        meta = (p.get("imageinfo") or [{}])[0].get("extmetadata", {})
        artist = meta.get("Artist", {}).get("value", "")
        out["artist"] = re.sub(r"<[^>]+>", "", artist).strip()[:120]
        out["license"] = meta.get("LicenseShortName", {}).get("value", "")
        out["licenseUrl"] = meta.get("LicenseUrl", {}).get("value", "")
    return out


def download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            if len(blob) < 4000:  # a placeholder or an error page, not a photo
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            return True
        except Exception:
            time.sleep((5, 20, 45)[attempt])
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="retry options that previously missed")
    ap.add_argument("--revalidate", action="store_true",
                    help="drop photos that no longer pass the matching rules, then refetch")
    args = ap.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    if args.revalidate:
        dropped = 0
        for o in data["options"]:
            img = o.get("image")
            if not img:
                continue
            page = img.get("page", "").replace("_", " ")
            why = ("wrong subject" if is_wrong_subject(img.get("articleTitle", ""), o)
                   else "a diagram, not a photo" if NOT_A_PHOTO.search(page) else None)
            if why:
                print(f"  dropping {o['name']} -> {img['articleTitle']} ({why})")
                (REPO / img["src"]).unlink(missing_ok=True)
                o["image"] = None
                cache.pop(o["name"], None)
                dropped += 1
        print(f"revalidate: dropped {dropped} mismatched photo(s)\n")

    todo = []
    for o in data["options"]:
        if o.get("image"):
            continue
        if o["kind"] not in PLACE_KINDS or o["geoPrecision"] not in {"exact", "approx"}:
            continue
        if not o["lat"] or not o["lng"]:
            continue
        if o["name"] in cache and not args.recheck:
            if cache[o["name"]]:
                o["image"] = cache[o["name"]]
            continue
        todo.append(o)
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(data['options'])} options · {len(todo)} to look up"
          + (" (dry run)" if args.dry_run else ""))
    hits = misses = errors = 0
    # One article, one option. Two nearby options both matching "Uji" would otherwise
    # show the same photo and look like a bug.
    used = {o["image"]["articleTitle"] for o in data["options"]
            if o.get("image") and o["image"].get("articleTitle")}

    for i, o in enumerate(todo, 1):
        try:
            results = geosearch(o["lat"], o["lng"])
        except ApiError as exc:
            errors += 1  # never cache a network failure as "no photo exists"
            print(f"  [{i}/{len(todo)}] ! {o['name']} — {exc}")
            continue
        time.sleep(PAUSE)
        best, best_score = None, 0.0
        for r in results:
            if r["title"] in used or is_wrong_subject(r["title"], o):
                continue
            s = score(o["name"], r["title"])
            near_and_alone = r["dist"] < 150 and len(results) <= 2 and s > 0
            if s > best_score and (s >= 0.55 or near_and_alone):
                best, best_score = r, s
        if not best:
            misses += 1
            cache[o["name"]] = None
            print(f"  [{i}/{len(todo)}] – {o['name']} (no confident match)")
            continue

        try:
            got = page_image(best["title"])
        except ApiError as exc:
            errors += 1
            print(f"  [{i}/{len(todo)}] ! {o['name']} — {exc}")
            continue
        time.sleep(PAUSE)
        if not got:
            misses += 1
            cache[o["name"]] = None
            print(f"  [{i}/{len(todo)}] – {o['name']} -> {best['title']} (article has no photo)")
            continue

        thumb, file_title = got
        if NOT_A_PHOTO.search(file_title.replace("_", " ")):
            misses += 1
            cache[o["name"]] = None
            print(f"  [{i}/{len(todo)}] – {o['name']} -> {file_title} (a diagram, not a photo)")
            continue
        rel = f"images/options/{o['slug']}.jpg"
        if not args.dry_run:
            if not download(thumb, REPO / rel):
                errors += 1
                print(f"  [{i}/{len(todo)}] ! {o['name']} (download failed)")
                continue
        try:
            credit = credit_for(file_title)
        except ApiError:
            credit = {"artist": "", "license": "", "licenseUrl": "",
                      "page": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(file_title)}"}
        time.sleep(PAUSE)
        image = {
            "src": rel,
            "article": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(best['title'].replace(' ', '_'))}",
            "articleTitle": best["title"],
            "distanceM": round(best["dist"]),
            **credit,
        }
        o["image"] = image
        cache[o["name"]] = image
        used.add(best["title"])
        hits += 1
        print(f"  [{i}/{len(todo)}] ✓ {o['name']} -> {best['title']} "
              f"({round(best['dist'])}m, match {best_score:.2f})")

        if i % 25 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            if not args.dry_run:
                data["counts"]["withPhoto"] = sum(1 for x in data["options"] if x.get("image"))
                DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    data["counts"]["withPhoto"] = sum(1 for x in data["options"] if x.get("image"))
    if not args.dry_run:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nmatched {hits} · no confident match {misses} · errors {errors} · "
          f"{data['counts']['withPhoto']}/{len(data['options'])} options now have a photo")
    if errors:
        print("Errors were not cached — re-run to retry just those.")


if __name__ == "__main__":
    main()
