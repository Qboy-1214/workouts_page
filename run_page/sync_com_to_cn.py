"""
Sync activities from Garmin International (COM) to Garmin China (CN).
Ensures activity type and name are preserved from COM.

Usage:
    python run_page/sync_com_to_cn.py --com-username USER --com-password PASS --cn-username USER --cn-password PASS
    python run_page/sync_com_to_cn.py  # Use environment variables or config
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

# Add project to path
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.insert(0, current)

from activity_type_map import map_com_type_to_cn
from config import FIT_FOLDER
from garmin_sync import Garmin, restore_or_login


async def get_com_activities_with_details(com_client, limit=10):
    """Get latest activities from COM with full details including type and name"""
    garmin_com = Garmin(com_client, "COM", False)

    # Get activity list
    activities = await garmin_com.get_activities(0, limit)
    print(f"Found {len(activities)} activities in Garmin COM")

    detailed_activities = []
    for act in activities:
        activity_id = act.get("activityId")
        activity_name = act.get("activityName", "")
        activity_type = act.get("activityType", {})
        type_key = activity_type.get("typeKey", "unknown")
        type_name = activity_type.get("typeGui", "Unknown")

        detailed_activities.append(
            {
                "id": activity_id,
                "name": activity_name,
                "type_key": type_key,
                "type_name": type_name,
                "start_time": act.get("startTimeGMT", ""),
                "original_data": act,
            }
        )
        print(f"  [{activity_id}] {activity_name} ({type_key})")

    return detailed_activities


async def get_cn_existing_ids(cn_client):
    """Get activity IDs that already exist in Garmin CN"""
    garmin_cn = Garmin(cn_client, "CN", False)
    existing_ids = set()

    # Get all CN activities in batches
    start = 0
    limit = 100
    while True:
        activities = await garmin_cn.get_activities(start, limit)
        if not activities:
            break
        for act in activities:
            activity_id = act.get("activityId")
            if activity_id:
                existing_ids.add(activity_id)
        if len(activities) < limit:
            break
        start += limit

    print(f"Found {len(existing_ids)} existing activities in Garmin CN")
    return existing_ids


async def download_activity_details(com_wrapper, activity_id, activity_info):
    """Download activity file and return path with metadata"""
    # Save to folder
    folder = FIT_FOLDER
    os.makedirs(folder, exist_ok=True)

    file_path = os.path.join(folder, f"{activity_id}.fit")
    tcx_path = os.path.join(folder, f"{activity_id}.tcx")

    # Try FIT format first
    print(f"  Downloading activity {activity_id} (trying FIT)...")
    file_data = await com_wrapper.download_activity(activity_id, file_type="fit")

    success = False
    if file_data and len(file_data) > 100:
        if file_data[:2] == b"PK":  # ZIP signature
            zip_path = os.path.join(folder, f"{activity_id}.zip")
            with open(zip_path, "wb") as f:
                f.write(file_data)

            import zipfile

            with zipfile.ZipFile(zip_path, "r") as zf:
                file_list = zf.namelist()
                print(f"    ZIP contents: {file_list}")

                for filename in file_list:
                    if filename.endswith(".fit") or filename.lower().endswith(".fit"):
                        zf.extract(filename, folder)
                        extracted = os.path.join(folder, filename)
                        print(f"    Extracted FIT: {filename}")
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        os.rename(extracted, file_path)
                        success = True
                        break
                    elif filename.endswith(".tcx") or filename.lower().endswith(".tcx"):
                        zf.extract(filename, folder)
                        extracted = os.path.join(folder, filename)
                        print(f"    Extracted TCX: {filename}")
                        if os.path.exists(tcx_path):
                            os.remove(tcx_path)
                        os.rename(extracted, tcx_path)
                        # Use TCX path as fallback
                        if not success:
                            file_path = tcx_path
                            success = True
                        break

            if os.path.exists(zip_path):
                os.remove(zip_path)
        else:
            # Raw data
            if b".fit" in file_data[:100] or file_data[:4] == b"PK\x03":
                with open(file_path, "wb") as f:
                    f.write(file_data)
                success = True

    # If FIT failed, try TCX
    if not success:
        print(f"  FIT download failed, trying TCX for {activity_id}...")
        file_data = await com_wrapper.download_activity(activity_id, file_type="tcx")

        if file_data and len(file_data) > 100:
            if file_data[:2] == b"PK":  # ZIP
                zip_path = os.path.join(folder, f"{activity_id}.zip")
                with open(zip_path, "wb") as f:
                    f.write(file_data)

                import zipfile

                with zipfile.ZipFile(zip_path, "r") as zf:
                    for filename in zf.namelist():
                        if filename.endswith(".tcx") or filename.lower().endswith(".tcx"):
                            zf.extract(filename, folder)
                            extracted = os.path.join(folder, filename)
                            print(f"    Extracted TCX: {filename}")
                            if os.path.exists(tcx_path):
                                os.remove(tcx_path)
                            os.rename(extracted, tcx_path)
                            file_path = tcx_path
                            success = True
                            break

                if os.path.exists(zip_path):
                    os.remove(zip_path)
            else:
                with open(tcx_path, "wb") as f:
                    f.write(file_data)
                file_path = tcx_path
                success = True

    if not success:
        print(f"  Failed to download activity {activity_id}")
        return None

    if not os.path.exists(file_path):
        print(f"  ERROR: File not created at {file_path}")
        return None

    file_size = os.path.getsize(file_path)
    print(f"  Downloaded {activity_id} ({file_path.split('.')[-1]}) ({file_size} bytes)")

    return {
        "file_path": file_path,
        "activity_id": activity_id,
        "activity_name": activity_info.get("name", ""),
        "activity_type_key": activity_info.get("type_key", ""),
        "activity_type_name": activity_info.get("type_name", ""),
        "start_time": activity_info.get("start_time", ""),
    }


async def upload_to_garmin_cn(cn_client, activity_data):
    """Upload activity to Garmin CN with correct type and name"""
    garmin_cn = Garmin(cn_client, "CN", False)

    file_path = activity_data["file_path"]
    activity_id = activity_data["activity_id"]
    activity_name = activity_data["activity_name"]
    com_type_key = activity_data["activity_type_key"]

    # Map COM type to CN-compatible type
    cn_type_key = map_com_type_to_cn(com_type_key)

    print(f"  Processing {activity_id} in CN: name='{activity_name}', type='{com_type_key}' -> '{cn_type_key}'")

    # First, try to find if this activity already exists in CN by start time
    start_time = activity_data.get("start_time", "")
    existing_cn_id = None

    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            date_str = start_dt.strftime("%Y-%m-%d")

            # Search CN activities
            for offset in [0, 100, 200, 300]:  # Search more pages
                recent = await garmin_cn.get_activities(offset, 100)
                if not recent:
                    break

                for act in recent:
                    act_start = act.get("startTimeGMT", "")
                    if act_start and date_str in str(act_start):
                        existing_cn_id = act.get("activityId")
                        current_name = act.get("activityName", "")
                        current_type = act.get("activityType", {}).get("typeKey", "")

                        print(f"  Found existing CN activity: {existing_cn_id}")
                        print(f"    Current: name='{current_name}', type='{current_type}'")

                        # Update name if different
                        if activity_name and activity_name != current_name:
                            try:
                                await asyncio.to_thread(
                                    garmin_cn._client.update_activity_name,
                                    existing_cn_id,
                                    activity_name,
                                )
                                print(f"  Updated name to: {activity_name}")
                            except Exception as name_err:
                                print(f"  Could not update name: {name_err}")

                        # Update type if different (use CN-mapped type)
                        if cn_type_key and cn_type_key != current_type:
                            try:
                                # Get activity types for CN
                                types = await asyncio.to_thread(garmin_cn._client.get_activity_types)

                                # Find matching CN type
                                type_id = None
                                parent_type_id = None
                                for t in types:
                                    if t.get("typeKey") == cn_type_key:
                                        type_id = t.get("id")
                                        parent_type_id = t.get("parentId")
                                        break

                                if type_id:
                                    await asyncio.to_thread(
                                        garmin_cn._client.update_activity_type,
                                        existing_cn_id,
                                        cn_type_key,
                                        type_id,
                                        parent_type_id,
                                    )
                                    print(f"  Updated type to: {cn_type_key}")
                                else:
                                    print(f"  CN type '{cn_type_key}' not found (may not be supported in CN)")
                            except Exception as type_err:
                                print(f"  Could not update type: {type_err}")

                        return True
        except Exception as find_err:
            print(f"  Could not search for existing activity: {find_err}")

    # If not found, try to upload
    try:
        result = await asyncio.to_thread(garmin_cn._client.upload_activity, file_path)
        print(f"  Upload result: {result}")
        return True
    except Exception as upload_err:
        err_str = str(upload_err)
        if "409" in err_str or "Conflict" in err_str:
            print("  Activity already exists (409 Conflict)")
            return True
        else:
            print(f"  Upload failed: {upload_err}")
            return False


async def gather_with_concurrency(n, *tasks):
    """Run tasks with limited concurrency"""
    semaphore = asyncio.Semaphore(n)

    async def sem_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*[sem_task(t) for t in tasks])


async def main():
    parser = argparse.ArgumentParser(description="Sync Garmin COM -> CN with activity name/type")
    parser.add_argument("--com-username", dest="com_username", help="Garmin COM username")
    parser.add_argument("--com-password", dest="com_password", help="Garmin COM password")
    parser.add_argument("--cn-username", dest="cn_username", help="Garmin CN username")
    parser.add_argument("--cn-password", dest="cn_password", help="Garmin CN password")
    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=10,
        help="Number of activities to sync (default: 10)",
    )
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Re-sync even if already in CN",
    )

    options = parser.parse_args()

    # Priority: environment variables > command line args
    com_username = os.getenv("GARMIN_COM_USERNAME") or options.com_username
    com_password = os.getenv("GARMIN_COM_PASSWORD") or options.com_password
    cn_username = os.getenv("GARMIN_CN_USERNAME") or options.cn_username
    cn_password = os.getenv("GARMIN_CN_PASSWORD") or options.cn_password
    limit = options.limit
    force_sync = options.force

    print("=" * 60)
    print("Garmin COM -> CN Sync (with Activity Name/Type)")
    print("=" * 60)

    # Validate credentials
    if not com_username or not com_password:
        print("Missing COM credentials!")
        print("Set GARMIN_COM_USERNAME and GARMIN_COM_PASSWORD environment variables")
        print("Or use --com-username and --com-password")
        sys.exit(1)

    if not cn_username or not cn_password:
        print("Missing CN credentials!")
        print("Set GARMIN_CN_USERNAME and GARMIN_CN_PASSWORD environment variables")
        print("Or use --cn-username and --cn-password")
        sys.exit(1)

    # Step 1: Login to Garmin COM
    print("\n[1] Logging in to Garmin COM...")
    com_client = restore_or_login(com_username, com_password, "COM")
    if not com_client:
        print("Failed to login to COM!")
        sys.exit(1)
    print("COM login successful")

    # Step 2: Login to Garmin CN
    print("\n[2] Logging in to Garmin CN...")
    cn_client = restore_or_login(cn_username, cn_password, "CN")
    if not cn_client:
        print("Failed to login to CN!")
        sys.exit(1)
    print("CN login successful")

    # Step 3: Get COM activities
    print(f"\n[3] Getting latest {limit} activities from Garmin COM...")
    com_activities = await get_com_activities_with_details(com_client, limit)

    # Step 4: Get existing CN activity IDs
    if force_sync:
        cn_existing_ids = set()
        print("Force mode: Will re-sync all activities")
    else:
        print("\n[4] Checking existing activities in Garmin CN...")
        cn_existing_ids = await get_cn_existing_ids(cn_client)

    # Step 5: Filter activities to sync
    activities_to_sync = []
    for act in com_activities:
        if act["id"] in cn_existing_ids:
            print(f"  Skipping {act['id']} - already exists in CN")
        else:
            activities_to_sync.append(act)

    if not activities_to_sync:
        print("\nNo new activities to sync!")
        return

    print(f"\n[5] Will sync {len(activities_to_sync)} activities to CN")

    # Step 6: Download activities from COM
    print("\n[6] Downloading activities from Garmin COM...")
    com_wrapper = Garmin(com_client, "COM", False)
    downloaded = []
    for act in activities_to_sync:
        result = await download_activity_details(com_wrapper, act["id"], act)
        if result:
            downloaded.append(result)

    if not downloaded:
        print("No activities downloaded!")
        sys.exit(1)

    # Step 7: Upload to Garmin CN
    print(f"\n[7] Uploading {len(downloaded)} activities to Garmin CN...")
    results = await gather_with_concurrency(
        3,  # Limit concurrent uploads
        *[upload_to_garmin_cn(cn_client, act) for act in downloaded],
    )

    success_count = sum(1 for r in results if r)
    print(f"\n{'=' * 60}")
    print(f"Sync completed: {success_count}/{len(downloaded)} successful")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
