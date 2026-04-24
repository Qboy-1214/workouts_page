"""Check for badminton activities"""

import asyncio
import os
import sys

sys.path.insert(0, "run_page")

from activity_type_map import map_com_type_to_cn
from garmin_sync import Garmin, restore_or_login


async def main():
    from dotenv import load_dotenv

    load_dotenv(".temp_garmin.env")

    com_client = restore_or_login(os.getenv("GARMIN_COM_USERNAME"), os.getenv("GARMIN_COM_PASSWORD"), False)
    garmin_com = Garmin(com_client, "COM", False)

    # Get more activities
    print("Fetching COM activities (looking for badminton, tennis, etc)...")
    found_any = []
    for offset in [0, 100, 200, 300]:
        activities = await garmin_com.get_activities(offset, 100)
        for act in activities:
            act_type = act.get("activityType", {}).get("typeKey", "")
            if act_type in ["soccer", "squash", "badminton", "tennis", "table_tennis"]:
                cn_type = map_com_type_to_cn(act_type)
                found_any.append(
                    {
                        "id": act.get("activityId"),
                        "name": act.get("activityName", ""),
                        "com_type": act_type,
                        "cn_type": cn_type,
                    }
                )
                print(f'  [{act.get("activityId")}] {act.get("activityName", "")}: {act_type} -> {cn_type}')
        if not activities:
            break

    print(f"\nTotal found: {len(found_any)}")

    if not found_any:
        print("No badminton/tennis/table_tennis activities found in COM")


if __name__ == "__main__":
    asyncio.run(main())
