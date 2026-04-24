"""Check actual activity types in CN"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from dotenv import load_dotenv
from garmin_cn_garth import GarminCngarthClient

load_dotenv(".temp_garmin.env")


async def main():
    # Login to CN
    cn_client = GarminCngarthClient(os.getenv("GARMIN_CN_USERNAME"), os.getenv("GARMIN_CN_PASSWORD"), is_cn=True)
    cn_client.login()

    # Get activity summary directly via API
    garth = cn_client._garth_client

    # Fetch a specific activity detail
    test_ids = [587346421, 587346389, 586714707, 586714497]  # soccer, squash, badminton

    print("Fetching activity details from CN:")
    for act_id in test_ids:
        try:
            resp = garth.connectapi(f"/activity-service/activity/{act_id}")
            if resp:
                print(f"\n[{act_id}]")
                print(f'  activityName: {resp.get("activityName")}')
                act_type = resp.get("activityType", {})
                print(f"  activityType: {act_type}")
        except Exception as e:
            print(f"[{act_id}] Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
