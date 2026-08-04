#!/usr/bin/env python3
"""Export the Obsidian planning vault into the single JSON file the site reads.

    python3 scripts/export_from_vault.py [--vault /path/to/JapanPlanning]

Reads (never writes) the vault:
  Japan/Items/*.md                  one note per option
  Japan/Planning/Hubs/**.md         hubs, side quests, and the package checkboxes
  Japan/Planning/item_packages.tsv  which options each package covers
  Japan/Planning/00 After Kyoto Tracks.md   which track a hub belongs to
  Japan/Planning/Media/**           hero photos, copied into images/

Writes: data/trip.json and images/hubs/*
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = REPO.parent / "JapanPlanning"

BLOCK_START = "<!-- items:start -->"
PKG_RE = re.compile(
    r"^- \[([ xX])\] \*\*(.+?)\*\*([^|]*)\| ([0-9.]+)h \| tags:([^|]+)\|(.*)$"
)
TRACK_RE = re.compile(r"^- \[[ xX]\] \*\*(.+?)\*\* \| id:([A-Za-z0-9]+) \| hubs:([^|]+)\|(.*)$")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
IMG_RE = re.compile(r"!\[[^\]]*\]\((\.\./[^)]+)\)")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def frontmatter(text: str) -> dict:
    m = FM_RE.match(text)
    if not m:
        return {}
    data: dict = {}
    key = None
    for line in m.group(1).splitlines():
        item = re.match(r"^\s+- (.*)$", line)
        if item and key:
            # A YAML list is written as an empty `key:` followed by `  - value` lines,
            # so the empty scalar recorded a moment ago has to become the list.
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(item.group(1).strip().strip('"'))
            continue
        kv = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            data[key] = val
    return data


def body_of(text: str) -> str:
    m = FM_RE.match(text)
    return text[m.end():] if m else text


def num(v: str | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def truthy(v: str | None) -> bool:
    return str(v).strip().lower() == "true"


# --------------------------------------------------------------------- hubs

def hub_track_map(vault: Path) -> dict[str, dict]:
    path = vault / "Japan/Planning/00 After Kyoto Tracks.md"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = TRACK_RE.match(line.strip())
        if not m:
            continue
        title, tid, hubs, note = m.groups()
        for hub in (h.strip() for h in hubs.split(",")):
            out[hub] = {"id": tid.strip(), "title": title.strip(), "note": note.strip()}
    return out


def copy_image(vault: Path, note: Path, rel: str, dest_dir: Path) -> str | None:
    """Resolve a vault-relative image reference and copy it into the site."""
    src = (note.parent / rel).resolve()
    if not src.exists() or not src.is_file():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{slugify(src.parent.name)}-{slugify(src.stem)}{src.suffix.lower()}"
    shutil.copyfile(src, dest_dir / name)
    return f"images/hubs/{name}"


def hero_image(vault: Path, note: Path, text: str, dest: Path) -> str | None:
    """First local photo. Locator maps are deliberately excluded — three hubs sharing
    the same pale outline of Japan tells a reader nothing; the site falls back to a
    photo of one of the hub's own options instead."""
    for rel in IMG_RE.findall(text):
        if "/maps/" in rel:
            continue
        got = copy_image(vault, note, rel, dest)
        if got:
            return got
    return None


def locator_map(vault: Path, note: Path, text: str, dest: Path) -> str | None:
    for rel in IMG_RE.findall(text):
        if "/maps/" in rel:
            return copy_image(vault, note, rel, dest)
    return None


def blurb_of(text: str) -> str:
    """The first ordinary prose paragraph — skips headings, bold meta lines, images."""
    for para in body_of(text).split("\n\n"):
        p = para.strip()
        if not p or p.startswith(("#", "!", ">", "|", "-", "*", "_", "[!")):
            continue
        if p.startswith("**") and p.count("**") <= 4 and ":" in p.split("**")[2][:3]:
            continue
        if re.match(r"^\*\*(Sleep hub|Under|From DC path|≈)", p):
            continue
        p = re.sub(r"\s{2,}$", "", p)
        p = WIKILINK_RE.sub(r"\1", p).replace("\n", " ")
        if len(p) > 40:
            return p
    return ""


def packages_of(text: str, stem: str) -> list[dict]:
    """Checkbox packages, ignoring anything inside the generated options block."""
    head = text.partition(BLOCK_START)[0]
    out = []
    for line in head.splitlines():
        m = PKG_RE.match(line.strip())
        if not m:
            continue
        checked, title, qual, hours, tags, note = m.groups()
        note = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", note.strip())
        out.append({
            "id": f"{stem} :: {title.strip()}",
            "title": title.strip(),
            "qualifier": qual.strip(" —-"),
            "hours": float(hours),
            "checked": checked.lower() == "x",
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
            "note": WIKILINK_RE.sub(r"\1", note),
            "options": [],
        })
    return out


# ------------------------------------------------------------------ options

def read_options(vault: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    items = vault / "Japan/Items"
    for path in sorted(items.glob("*.md")):
        if path.name.startswith("00 "):
            continue
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm.get("type") != "itinerary-item":
            continue
        body = body_of(text)
        quote = re.search(r"^> (?!\[!)(.+)$", body, re.M)
        callout = re.search(r"^> \[!note\] (.+)$", body, re.M)
        out[path.stem] = {
            "slug": slugify(path.stem),
            "name": path.stem,
            "description": quote.group(1).strip() if quote else "",
            "flag": callout.group(1).strip() if callout else "",
            "hub": fm.get("hub", "unassigned"),
            "city": fm.get("city", ""),
            "region": fm.get("region", ""),
            "kind": fm.get("kind", "other"),
            "category": fm.get("category", "sights"),
            "status": fm.get("status", "idea"),
            "mustDo": truthy(fm.get("must_do")),
            "hours": num(fm.get("duration_hrs")),
            "effort": fm.get("effort", ""),
            "indoor": fm.get("indoor", ""),
            "booking": fm.get("booking", ""),
            "seasonMay": fm.get("season_may", ""),
            "styleSlot": fm.get("style_slot", ""),
            "closedDays": fm.get("closed_days", ""),
            "costJpy": num(fm.get("cost_pp_jpy")),
            "transitMin": num(fm.get("transit_from_hub_min")),
            "car": truthy(fm.get("car")),
            "lat": num(fm.get("lat")),
            "lng": num(fm.get("lng")),
            "geoPrecision": fm.get("geo_precision", "none"),
            "maps": fm.get("maps", ""),
            "url": fm.get("official_url", "") or fm.get("source_url", ""),
            "packages": fm.get("package") if isinstance(fm.get("package"), list) else [],
            "image": None,
        }
    return out


def write_attribution(options: list[dict]) -> None:
    """One row per reused photo, so the credits survive outside the page itself."""
    rows = sorted((o for o in options if o.get("image")), key=lambda o: o["name"])
    lines = [
        "# Photo attribution",
        "",
        "Photographs on this site come from Wikimedia Commons and remain the work of "
        "their authors, under the licences below. Site code and planning text are covered "
        "by `LICENSE`.",
        "",
        f"{len(rows)} photos in use.",
        "",
        "| Option | Photo source | Author | Licence |",
        "|--------|--------------|--------|---------|",
    ]
    for o in rows:
        img = o["image"]
        lines.append(
            f"| {o['name']} | [{img.get('articleTitle', 'Commons')}]({img.get('page', '')}) "
            f"| {img.get('artist') or '—'} | {img.get('license') or 'see source'} |"
        )
    (REPO / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    args = ap.parse_args()
    vault: Path = args.vault.expanduser().resolve()
    if not (vault / "Japan/Items").is_dir():
        raise SystemExit(f"No vault at {vault} — pass --vault")

    hubs_dir = vault / "Japan/Planning/Hubs"
    img_dest = REPO / "images/hubs"
    tracks = hub_track_map(vault)
    options = read_options(vault)

    # Preserve photos a previous fetch attached to each option.
    prev_path = REPO / "data/trip.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        for o in prev.get("options", []):
            if o.get("image") and o["name"] in options:
                options[o["name"]]["image"] = o["image"]

    by_id: dict[str, dict] = {}
    hubs = []
    for path in sorted(hubs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text)
        title = (re.search(r"^# (.+)$", body_of(text), re.M) or [None, path.stem])[1]
        hub = {
            "id": path.stem,
            "label": fm.get("hub", path.stem),
            "title": title.strip(),
            "minNights": int(fm.get("min_nights", 2) or 2),
            "track": tracks.get(path.stem, {"id": "common", "title": "Common spine"}),
            "blurb": blurb_of(text),
            "image": hero_image(vault, path, text, img_dest),
            "map": locator_map(vault, path, text, img_dest),
            "packages": packages_of(text, path.stem),
            "sideQuests": [],
        }
        for sq in sorted((hubs_dir / path.stem).glob("*.md")) if (hubs_dir / path.stem).is_dir() else []:
            st = sq.read_text(encoding="utf-8")
            sq_title = (re.search(r"^# (.+)$", body_of(st), re.M) or [None, sq.stem])[1]
            stem = f"{path.stem}/{sq.stem}"
            hub["sideQuests"].append({
                "id": stem,
                "label": sq.stem,
                "title": sq_title.strip(),
                "blurb": blurb_of(st),
                "image": hero_image(vault, sq, st, img_dest),
                "packages": packages_of(st, stem),
            })
        hubs.append(hub)
        for pkg in hub["packages"] + [p for s in hub["sideQuests"] for p in s["packages"]]:
            by_id[pkg["id"]] = pkg

    # Options carry their package ids; walk them back so packages list their options.
    for name, o in options.items():
        for pid in o["packages"]:
            if pid in by_id:
                by_id[pid]["options"].append(name)
    for pkg in by_id.values():
        pkg["options"].sort()

    live = [o for o in options.values() if o["status"] not in {"rejected", "parked"}]
    payload = {
        "generated": date.today().isoformat(),
        "counts": {
            "hubs": len(hubs),
            "options": len(live),
            "packages": len(by_id),
            "withPhoto": sum(1 for o in live if o["image"]),
        },
        "hubs": hubs,
        "options": sorted(live, key=lambda o: o["name"]),
    }
    prev_path.parent.mkdir(parents=True, exist_ok=True)
    prev_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    write_attribution(live)

    print(f"vault:    {vault}")
    print(f"hubs:     {len(hubs)} ({sum(len(h['sideQuests']) for h in hubs)} side quests)")
    print(f"packages: {len(by_id)}")
    print(f"options:  {len(live)} live ({payload['counts']['withPhoto']} with a photo)")
    print(f"wrote:    {prev_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
