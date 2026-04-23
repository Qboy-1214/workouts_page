"""Check what types CN supports by checking uploaded activities"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from garmin_cn_garth import GarminCngarthClient
from garmin_sync import Garmin
from dotenv import load_dotenv

load_dotenv(".temp_garmin.env")


async def main():
    cn_client = GarminCngarthClient(
        os.getenv("GARMIN_CN_USERNAME"), os.getenv("GARMIN_CN_PASSWORD"), is_cn=True
    )
    cn_client.login()
    garmin_cn = Garmin(cn_client, "CN", False)

    # Get activities with type info
    print("Fetching CN activities and checking types...")
    activities = await garmin_cn.get_activities(0, 100)

    type_counts = {}
    for act in activities:
        act_type = act.get("activityType", {})
        type_key = act_type.get("typeKey", "unknown")
        type_gui = act_type.get("typeGui", "unknown")

        if type_key not in type_counts:
            type_counts[type_key] = []
        type_counts[type_key].append(
            {
                "id": act.get("activityId"),
                "name": act.get("activityName", "")[:30],
                "gui": type_gui,
            }
        )

    print(f"\nFound {len(activities)} activities")
    print(f"Unique types: {len(type_counts)}")
    print("\nType breakdown:")
    for t, acts in sorted(type_counts.items()):
        print(f"  {t}: {len(acts)} activities")
        # Show a few examples
        for a in acts[:3]:
            print(f'    - [{a["id"]}] {a["name"]} (gui: {a["gui"]})')


if __name__ == "__main__":
    asyncio.run(main())
