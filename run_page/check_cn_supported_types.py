"""Try different approaches to update activity type in CN"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from dotenv import load_dotenv
from garmin_cn_garth import GarminCngarthClient

load_dotenv(".temp_garmin.env")


async def main():
    cn_client = GarminCngarthClient(os.getenv("GARMIN_CN_USERNAME"), os.getenv("GARMIN_CN_PASSWORD"), is_cn=True)
    cn_client.login()
    garth = cn_client._garth_client

    act_id = 587346421  # 足球

    # Try different API endpoints and payloads

    # 1. Try the activity service update endpoint with different format
    print("Testing different update approaches...\n")

    # Approach 1: Full activity update
    print("1. Full activity update:")
    try:
        path = f"/activity-service/activity/{act_id}"
        payload = {
            "activityId": act_id,
            "activityName": "测试足球",
            "activityType": {"typeKey": "other", "typeId": 247, "parentTypeId": 247},
        }
        resp = garth.connectapi(path, method="PUT", json=payload)
        print(f"   Result: {resp}")
    except Exception as e:
        print(f"   Error: {e}")

    # 2. Try with just typeId
    print("\n2. Just typeId update:")
    try:
        path = f"/activity-service/activity/{act_id}"
        payload = {"activityId": act_id, "activityType": {"typeId": 247}}
        resp = garth.connectapi(path, method="PUT", json=payload)
        print(f"   Result: {resp}")
    except Exception as e:
        print(f"   Error: {e}")

    # 3. Try PATCH instead of PUT
    print("\n3. PATCH request:")
    try:
        path = f"/activity-service/activity/{act_id}"
        payload = {
            "activityId": act_id,
            "activityType": {"typeId": 247, "parentTypeId": 247},
        }
        resp = garth.connectapi(path, method="PATCH", json=payload)
        print(f"   Result: {resp}")
    except Exception as e:
        print(f"   Error: {e}")

    # 4. Check what types CN actually accepts by looking at activity summary
    print("\n4. Fetching activity summary to see type info:")
    try:
        resp = garth.connectapi(f"/activity-service/activity/{act_id}/summary")
        print(f"   Result keys: {resp.keys() if resp else None}")
        if resp:
            print(f'   sportType: {resp.get("sportTypeId")}')
            print(f'   activityType: {resp.get("activityType")}')
    except Exception as e:
        print(f"   Error: {e}")

    # 5. Try setting the sport type directly
    print("\n5. Try sport type update:")
    try:
        path = f"/activity-service/activity/{act_id}"
        payload = {"activityId": act_id, "sportTypeId": 247}
        resp = garth.connectapi(path, method="PUT", json=payload)
        print(f"   Result: {resp}")
    except Exception as e:
        print(f"   Error: {e}")

    # Final check
    print("\n6. Final state:")
    resp = garth.connectapi(f"/activity-service/activity/{act_id}")
    print(f'   activityName: {resp.get("activityName")}')
    print(f'   activityType: {resp.get("activityType")}')


if __name__ == "__main__":
    asyncio.run(main())
