"""
Update activity types for already synced activities.
Run after updating activity_type_map.py
"""

import asyncio
import os
import sys
from datetime import datetime

current = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, current)

from activity_type_map import map_com_type_to_cn
from garmin_cn_garth import GarminCngarthClient
from garmin_sync import Garmin, restore_or_login


async def main():
    print("=" * 60)
    print("Updating activity types with new mapping")
    print("=" * 60)

    # Load env
    from dotenv import load_dotenv

    load_dotenv(".temp_garmin.env")

    com_username = os.getenv("GARMIN_COM_USERNAME")
    com_password = os.getenv("GARMIN_COM_PASSWORD")
    cn_username = os.getenv("GARMIN_CN_USERNAME")
    cn_password = os.getenv("GARMIN_CN_PASSWORD")

    # Login to COM
    print("Logging into Garmin COM...")
    com_client = restore_or_login(com_username, com_password, False)
    garmin_com = Garmin(com_client, "COM", False)
    print("COM login OK")

    # Login to CN
    print("Logging into Garmin CN...")
    cn_client = GarminCngarthClient(cn_username, cn_password, is_cn=True)
    cn_client.login()
    garmin_cn = Garmin(cn_client, "CN", False)
    print("CN login OK")

    # Get latest 10 COM activities
    print()
    print("Fetching latest 10 COM activities...")
    com_activities = await garmin_com.get_activities(0, 10)

    for act in com_activities:
        act_id = act.get("activityId")
        act_name = act.get("activityName", "")
        com_type = act.get("activityType", {}).get("typeKey", "unknown")
        start_time = act.get("startTimeGMT", "")

        print(f"  [{act_id}] {act_name}: COM type = {com_type}")

    # Get CN activity types
    cn_types = await asyncio.to_thread(cn_client.get_activity_types)
    print(f"\nCN supports {len(cn_types)} activity types:")
    print(f'  {[t["typeKey"] for t in cn_types]}')

    # Process each activity
    print()
    print("Updating activity types...")
    updated = 0
    skipped = 0

    for act in com_activities:
        act_id = act.get("activityId")
        act_name = act.get("activityName", "")
        com_type = act.get("activityType", {}).get("typeKey", "unknown")
        start_time = act.get("startTimeGMT", "")

        # Map to CN type
        cn_type_key = map_com_type_to_cn(com_type)

        # Check if mapped to 'other' when it shouldn't
        if cn_type_key == "other" and com_type not in ("other", "fitness_equipment"):
            print(
                f"  [{act_id}] {act_name}: {com_type} -> CN: {cn_type_key} (not in CN, skipping)"
            )
            skipped += 1
            continue

        if not start_time:
            skipped += 1
            continue

        # Find matching CN activity by start time
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            date_str = start_dt.strftime("%Y-%m-%d")

            # Search CN activities
            found = False
            for offset in [0, 100, 200, 300]:
                recent = await garmin_cn.get_activities(offset, 100)
                if not recent:
                    break

                for cn_act in recent:
                    cn_start = cn_act.get("startTimeGMT", "")
                    if cn_start and date_str in str(cn_start):
                        cn_act_id = cn_act.get("activityId")
                        cn_current_type = cn_act.get("activityType", {}).get(
                            "typeKey", ""
                        )
                        cn_current_name = cn_act.get("activityName", "")

                        print(
                            f"  [{act_id}] {act_name}: CN current type = {cn_current_type}"
                        )

                        # Update name if different
                        if act_name and act_name != cn_current_name:
                            try:
                                await asyncio.to_thread(
                                    cn_client.update_activity_name, cn_act_id, act_name
                                )
                                print(f"    -> Updated name to: {act_name}")
                            except Exception as name_err:
                                print(f"    -> Could not update name: {name_err}")

                        # Update type if different
                        if cn_type_key != cn_current_type:
                            # Find CN type ID
                            type_info = next(
                                (
                                    t
                                    for t in cn_types
                                    if t.get("typeKey") == cn_type_key
                                ),
                                None,
                            )
                            if type_info:
                                type_id = type_info.get("id")
                                parent_id = type_info.get("parentId")
                                await asyncio.to_thread(
                                    cn_client.update_activity_type,
                                    cn_act_id,
                                    cn_type_key,
                                    type_id,
                                    parent_id,
                                )
                                print(f"    -> Updated to: {cn_type_key}")
                                updated += 1
                            else:
                                print(f'    -> CN type "{cn_type_key}" not found')
                        else:
                            print("    -> Already correct")
                        found = True
                        break

                if found:
                    break

            if not found:
                print(f"  [{act_id}] {act_name}: No matching CN activity found")
                skipped += 1

        except Exception as e:
            print(f"  Error processing {act_id}: {e}")
            skipped += 1

        await asyncio.sleep(0.5)

    print()
    print(f"Updated {updated} activity types, skipped {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
