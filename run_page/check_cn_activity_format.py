"""Check the raw activityType format from CN API"""

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

    # Get activities with pagination
    print("Fetching activities via API...\n")

    try:
        # Try GET endpoint
        resp = garth.connectapi("/activitylist-service/activities?start=0&limit=5")
        print(f"Response type: {type(resp)}")
        if resp:
            print(f"Response: {str(resp)[:500]}")

    except Exception as e:
        print(f"GET Error: {e}")

    # Also try to get a specific activity to see the full structure
    print("\n\nFetching specific activity...")
    try:
        act_id = 587346421
        resp = garth.connectapi(f"/activity-service/activity/{act_id}")
        print(f"Activity keys: {resp.keys() if resp else None}")
        if resp:
            import json

            print(json.dumps(resp, indent=2, default=str)[:2000])
    except Exception as e:
        print(f"Activity Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
