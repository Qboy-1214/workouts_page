"""One-time backfill: populate location_country for existing data.db rows.

The Strava sync only pulls NEW activities, so rows that were created before
the geocode cache existed never pass through update_or_create_activity again.
This script updates every row with an empty location_country directly in
data.db, using run_page/geocode_cache.json (keys derived from each row's
stored summary_polyline). Commit data.db afterwards.

Usage:
    python run_page/backfill_location.py
"""

import json
import os
import sys

import polyline as mod_polyline
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

from generator.db import Activity  # noqa: E402
from config import SQL_FILE  # noqa: E402


def main():
    cache_file = os.path.join(HERE, "geocode_cache.json")
    with open(cache_file, encoding="utf-8") as f:
        cache = json.load(f)

    engine = create_engine(f"sqlite:///{SQL_FILE}")
    session = sessionmaker(bind=engine)()
    rows = (
        session.query(Activity)
        .filter(
            (Activity.location_country.is_(None)) | (Activity.location_country == "")
        )
        .all()
    )
    print(f"待回填: {len(rows)} 行")
    hit = 0
    for row in rows:
        if not row.summary_polyline:
            continue
        try:
            lat, lon = mod_polyline.decode(row.summary_polyline)[0]
        except Exception as e:
            print(f"skip {row.run_id}: decode failed {e}")
            continue
        key = f"{lat:.3f},{lon:.3f}"
        if key not in cache:
            print(f"miss {row.run_id}: {key}")
            continue
        row.location_country = cache[key]
        hit += 1
    session.commit()
    print(f"回填完成: {hit}/{len(rows)} 行已更新")


if __name__ == "__main__":
    main()
