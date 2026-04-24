"""Test activity type update with correct field name"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from dotenv import load_dotenv
from garmin_cn_garth import GarminCngarthClient

load_dotenv(".temp_garmin.env")


async def main():
    cn_client = GarminCngarthClient(
        os.getenv("GARMIN_CN_USERNAME"), os.getenv("GARMIN_CN_PASSWORD"), is_cn=True
    )
    cn_client.login()
    garth = cn_client._garth_client

    act_id = 587346421

    # Check current state
    print("Before update:")
    resp = garth.connectapi(f"/activity-service/activity/{act_id}")
    print(f'  activityName: {resp.get("activityName")}')
    print(f'  activityTypeDTO: {resp.get("activityTypeDTO")}')

    # Try update with activityTypeDTO
    print("\nUpdating with activityTypeDTO...")
    try:
        payload = {
            "activityId": act_id,
            "activityTypeDTO": {"typeId": 40, "typeKey": "soccer", "parentTypeId": 28},
        }
        result = garth.connectapi(
            f"/activity-service/activity/{act_id}", method="PUT", json=payload
        )
        print(f"  Result: {result}")
    except Exception as e:
        print(f"  Error: {e}")

    # Check after
    print("\nAfter update:")
    resp = garth.connectapi(f"/activity-service/activity/{act_id}")
    print(f'  activityName: {resp.get("activityName")}')
    print(f'  activityTypeDTO: {resp.get("activityTypeDTO")}')

    # Also check via activity list
    print("\nChecking via activity list...")
    resp = garth.connectapi("/activitylist-service/activities?start=0&limit=5")
    if resp and "activityList" in resp:
        for act in resp["activityList"]:
            if act["activityId"] == act_id:
                print(f'  activityType: {act.get("activityType")}')
                break


if __name__ == "__main__":
    asyncio.run(main())
