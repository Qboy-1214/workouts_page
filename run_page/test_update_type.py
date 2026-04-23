"""Test activity type update"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from garmin_cn_garth import GarminCngarthClient
from dotenv import load_dotenv

load_dotenv(".temp_garmin.env")


async def main():
    # Login to CN
    cn_client = GarminCngarthClient(
        os.getenv("GARMIN_CN_USERNAME"), os.getenv("GARMIN_CN_PASSWORD"), is_cn=True
    )
    cn_client.login()

    garth = cn_client._garth_client

    # First, get an activity
    act_id = 587346421  # 足球

    print(f"Fetching activity {act_id} before update...")
    try:
        resp = garth.connectapi(f"/activity-service/activity/{act_id}")
        print(f'Before: activityName={resp.get("activityName")}')
        print(f'  activityType={resp.get("activityType")}')
    except Exception as e:
        print(f"Error fetching: {e}")

    # Try to update the type
    print(f"\nUpdating type to soccer (id=40, parent=28)...")
    try:
        path = f"/activity-service/activity/{act_id}"
        payload = {
            "activityId": act_id,
            "activityType": {"typeId": 40, "parentTypeId": 28},
        }
        result = garth.connectapi(path, method="PUT", json=payload)
        print(f"Update result: {result}")
    except Exception as e:
        print(f"Update error: {e}")

    # Fetch again
    print(f"\nFetching activity {act_id} after update...")
    try:
        resp = garth.connectapi(f"/activity-service/activity/{act_id}")
        print(f'After: activityName={resp.get("activityName")}')
        print(f'  activityType={resp.get("activityType")}')
    except Exception as e:
        print(f"Error fetching: {e}")


if __name__ == "__main__":
    asyncio.run(main())
