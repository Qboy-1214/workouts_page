"""Backfill run_page/geocode_cache.json from existing activities.json.

Decodes each activity's summary_polyline, reverse-geocodes the start point
with Nominatim (run this locally — GitHub runner IPs are blocked by OSM),
and stores results keyed by "lat3,lng3" so generator/db.py can reuse them
without network access.

Usage:
    python run_page/update_geocode_cache.py
"""

import json
import os
import time

import polyline as mod_polyline
from geopy.geocoders import Nominatim

HERE = os.path.dirname(__file__)
CACHE_FILE = os.path.join(HERE, "geocode_cache.json")
ACTIVITIES = os.path.join(HERE, "..", "src", "static", "activities.json")


def main():
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)

    with open(ACTIVITIES, encoding="utf-8") as f:
        activities = json.load(f)

    g = Nominatim(user_agent="workouts_page_geocode")
    total = 0
    for a in activities:
        sp = a.get("summary_polyline")
        if not sp:
            continue
        try:
            lat, lon = mod_polyline.decode(sp)[0]
        except Exception as e:
            print(f"skip {a.get('run_id')}: decode failed {e}")
            continue
        key = f"{lat:.3f},{lon:.3f}"
        if key in cache:
            continue
        try:
            cache[key] = str(g.reverse(f"{lat}, {lon}", language="zh-CN", timeout=15))
            total += 1
            print(f"[{total}] {key} -> {cache[key][:60]}")
        except Exception as e:
            print(f"{key}: {type(e).__name__}: {e}")
        if total % 20 == 0:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=0)
        time.sleep(1.1)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)
    print(f"Done. {total} new entries, {len(cache)} total in {CACHE_FILE}")


if __name__ == "__main__":
    main()
