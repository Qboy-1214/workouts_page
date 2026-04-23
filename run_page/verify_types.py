"""Verify specific activity types"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from garmin_cn_garth import GarminCngarthClient
from dotenv import load_dotenv

load_dotenv(".temp_garmin.env")


async def main():
    cn_client = GarminCngarthClient(
        os.getenv("GARMIN_CN_USERNAME"), os.getenv("GARMIN_CN_PASSWORD"), is_cn=True
    )
    cn_client.login()
    garth = cn_client._garth_client

    # Check a few specific activities
    test_ids = [
        (587346421, "soccer", "足球"),
        (586714707, "badminton", "羽毛球"),
        (586714859, "walking", "散步"),
        (586714889, "road_biking", "骑行"),
    ]

    print("Verifying activity types:\n")
    for act_id, expected_type, name in test_ids:
        try:
            resp = garth.connectapi(f"/activity-service/activity/{act_id}")
            act_type_dto = resp.get("activityTypeDTO", {})
            actual_type = act_type_dto.get("typeKey", "unknown")
            status = "OK" if actual_type == expected_type else "FAIL"
            print(f"[{status}] [{act_id}] {name}")
            print(f"   Expected: {expected_type}, Actual: {actual_type}")
            print(f"   Full DTO: {act_type_dto}")
            print()
        except Exception as e:
            print(f"[FAIL] [{act_id}] Error: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
