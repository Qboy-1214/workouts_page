"""
Sync activities from Garmin International (COM) to Garmin China (CN).

Workflow:
1. Login to Garmin COM and download new activities (not in CN)
2. Upload new activities to Garmin CN

This is used after strava_to_garmin_sync.py syncs from Strava to Garmin COM.
Reference: strava_to_garmin_sync.py login and sync logic pattern.
"""

import argparse
import asyncio
import os
import sys
import time

from config import FIT_FOLDER, GPX_FOLDER, JSON_FILE, SQL_FILE
from garmin_sync import Garmin, restore_or_login, get_activity_id_list
from garmin_sync import (
    download_garmin_data,
    get_garmin_summary_infos,
    gather_with_concurrency,
)
from utils import make_activities_file


async def get_cn_existing_timestamps(cn_client):
    """Get activity timestamps that already exist in Garmin CN to avoid duplicates.

    NOTE: COM and CN have different activity IDs for the same activity.
    We use startTimeGMT + distance to match activities across platforms.
    """
    garmin_cn = Garmin(cn_client, "CN", False)
    cn_timestamps = set()

    # Get all CN activities in batches
    start = 0
    limit = 100
    while True:
        activities = await garmin_cn.get_activities(start, limit)
        if not activities:
            break
        for act in activities:
            # Use startTimeGMT + distance as unique identifier
            start_time = act.get("startTimeGMT", "")
            distance = act.get("distance", 0) or 0
            if start_time:
                cn_timestamps.add((start_time, distance))
        if len(activities) < limit:
            break
        start += limit

    print(f"Found {len(cn_timestamps)} existing activities in Garmin CN")
    return cn_timestamps


async def download_with_cn_filter(
    com_client,
    cn_existing_timestamps,
    is_only_running,
    folder,
    file_type,
    max_activities=10000,
):
    """Download activities from COM, filtering out those that exist in CN"""
    garmin_com = Garmin(com_client, "COM", is_only_running)
    activity_ids = await get_activity_id_list(garmin_com)

    # Filter out activities that already exist in CN (match by time + distance)
    to_generate_ids = []
    to_generate_garmin_id2title = {}
    garmin_summary_infos_dict = {}

    for id in activity_ids:
        try:
            activity_summary = await garmin_com.get_activity_summary(id)
            start_time = activity_summary.get(
                "startTimeGMT", ""
            ) or activity_summary.get("summaryDTO", {}).get("startTimeGMT", "")
            distance = (
                activity_summary.get("distance", 0)
                or activity_summary.get("summaryDTO", {}).get("distance", 0)
                or 0
            )

            # Check if this activity already exists in CN (by time + distance)
            if (start_time, distance) in cn_existing_timestamps:
                continue

            activity_title = activity_summary.get("activityName", "")
            to_generate_ids.append(id)
            to_generate_garmin_id2title[id] = activity_title
            garmin_summary_infos_dict[id] = get_garmin_summary_infos(
                activity_summary, id
            )
        except Exception as e:
            print(f"Failed to get activity summary {id}: {str(e)}")
            continue

    # Apply max_activities limit only if explicitly set (not 0)
    if max_activities > 0 and len(to_generate_ids) > max_activities:
        to_generate_ids = to_generate_ids[:max_activities]
        print(
            f"{len(to_generate_ids)} new activities to be downloaded (limited to {max_activities})"
        )
    else:
        print(f"{len(to_generate_ids)} new activities to be downloaded")

    start_time = time.time()
    await gather_with_concurrency(
        10,
        [
            download_garmin_data(
                garmin_com,
                id,
                file_type=file_type,
                summary_infos=garmin_summary_infos_dict,
            )
            for id in to_generate_ids
        ],
    )
    print(f"Download finished. Elapsed {time.time()-start_time} seconds")

    return to_generate_ids, to_generate_garmin_id2title


async def upload_activities_to_garmin_cn(garmin_cn_wrapper, files):
    """Upload activities to Garmin CN using the wrapper pattern from strava_to_garmin_sync.py"""
    print(
        f"[upload_activities_to_garmin_cn] Starting upload to Garmin CN, auth domain: {garmin_cn_wrapper.auth_domain}"
    )
    await garmin_cn_wrapper.upload_activities_files(files)
    print("[upload_activities_to_garmin_cn] Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Garmin COM -> CN")
    parser.add_argument("--cn-username", dest="cn_username", help="Garmin CN username")
    parser.add_argument("--cn-password", dest="cn_password", help="Garmin CN password")
    parser.add_argument(
        "--com-username", dest="com_username", help="Garmin COM username"
    )
    parser.add_argument(
        "--com-password", dest="com_password", help="Garmin COM password"
    )
    parser.add_argument(
        "--only-run",
        dest="only_run",
        action="store_true",
        help="if is only for running",
    )
    parser.add_argument(
        "--max-activities",
        dest="max_activities",
        type=int,
        default=10000,
        help="maximum number of activities to sync (default: 10000, set to 0 for unlimited)",
    )

    options = parser.parse_args()
    is_only_running = options.only_run
    max_activities = options.max_activities

    # Priority: environment variables > command line args (same as strava_to_garmin_sync.py)
    cn_username = os.getenv("GARMIN_CN_USERNAME") or options.cn_username
    cn_password = os.getenv("GARMIN_CN_PASSWORD") or options.cn_password
    com_username = os.getenv("GARMIN_COM_USERNAME") or options.com_username
    com_password = os.getenv("GARMIN_COM_PASSWORD") or options.com_password

    print("[main] GARMIN_COM_TO_CN_SYNC START - syncing from COM to CN")
    print(
        f"[main] CN credentials set: {bool(cn_username)}, COM credentials set: {bool(com_username)}"
    )

    if not cn_username or not cn_password:
        print("Missing CN credentials: please provide --cn-username/--cn-password")
        print("Or set environment variables: GARMIN_CN_USERNAME and GARMIN_CN_PASSWORD")
        sys.exit(1)

    if not com_username or not com_password:
        print("Missing COM credentials: please provide --com-username/--com-password")
        print(
            "Or set environment variables: GARMIN_COM_USERNAME and GARMIN_COM_PASSWORD"
        )
        sys.exit(1)

    folder = FIT_FOLDER
    if not os.path.exists(folder):
        os.mkdir(folder)

    # Step 1: Login to Garmin CN
    garmin_cn_client = None
    try:
        print("[main] Logging in to Garmin CN...")
        garmin_cn_client = restore_or_login(cn_username, cn_password, "CN")
        print(f"[main] Garmin CN login successful")
    except Exception as err:
        print(f"[main] Garmin CN login failed: {err}")
        garmin_cn_client = None

    if garmin_cn_client is None:
        print("[main] Cannot proceed without CN client. Exiting.")
        sys.exit(1)

    # Step 2: Get existing activity timestamps from Garmin CN
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cn_existing_timestamps = loop.run_until_complete(
        get_cn_existing_timestamps(garmin_cn_client)
    )
    print(f"Garmin CN already has {len(cn_existing_timestamps)} activities")

    # Step 3: Login to Garmin COM and download new activities
    garmin_com_client = None
    try:
        print("[main] Logging in to Garmin COM (International)...")
        garmin_com_client = restore_or_login(com_username, com_password, "COM")
        print(f"[main] Garmin COM login successful")
    except Exception as err:
        print(f"[main] Garmin COM login failed: {err}")
        garmin_com_client = None

    if garmin_com_client is None:
        print("[main] Cannot proceed without COM client. Exiting.")
        sys.exit(1)

    future = asyncio.ensure_future(
        download_with_cn_filter(
            garmin_com_client,
            cn_existing_timestamps,
            is_only_running,
            folder,
            "fit",
            max_activities=max_activities,
        )
    )
    loop.run_until_complete(future)
    new_ids, id2title = future.result()

    # Step 4: Find files to upload
    to_upload_files = []
    for i in new_ids:
        fit_path = os.path.join(FIT_FOLDER, f"{i}.fit")
        tcx_path = os.path.join(FIT_FOLDER, f"{i}.tcx")
        gpx_path = os.path.join(GPX_FOLDER, f"{i}.gpx")
        if os.path.exists(fit_path):
            file_size = os.path.getsize(fit_path)
            if file_size > 1000:  # Skip tiny/corrupt files
                print(f"Will upload .fit: {i} ({file_size} bytes)")
                to_upload_files.append(fit_path)
            else:
                print(f"Skipping tiny .fit file: {i} ({file_size} bytes)")
        elif os.path.exists(tcx_path):
            file_size = os.path.getsize(tcx_path)
            if file_size > 1000:
                print(f"Will upload .tcx: {i} ({file_size} bytes)")
                to_upload_files.append(tcx_path)
            else:
                print(f"Skipping tiny .tcx file: {i} ({file_size} bytes)")
        elif os.path.exists(gpx_path):
            file_size = os.path.getsize(gpx_path)
            print(f"Will upload .gpx: {i} ({file_size} bytes)")
            to_upload_files.append(gpx_path)

    print(f"\nFiles to upload to CN: {len(to_upload_files)}")

    if to_upload_files:
        # Step 5: Upload to Garmin CN using wrapper pattern from strava_to_garmin_sync.py
        print("Uploading activities to Garmin CN...")
        garmin_cn_wrapper = Garmin(garmin_cn_client, "CN", is_only_running)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            future = asyncio.ensure_future(
                upload_activities_to_garmin_cn(garmin_cn_wrapper, to_upload_files)
            )
            loop.run_until_complete(future)
            print("Upload completed!")
        except Exception as err:
            print(f"[main] Upload to CN failed: {err}")
        finally:
            loop.close()
    else:
        print("No new activities to upload.")

    # Step 6: Generate track from ONLY the newly downloaded files
    # NOTE: Do NOT process all historical files - that causes thousands of log lines
    # Only process the files for activities we just downloaded
    print(f"Processing {len(new_ids)} newly synced activities...")

    # For COM->CN sync, we don't need to regenerate the full activities.json
    # The CN activities will be synced separately via garmin_sync_cn.py
    # If user needs local tracking, they can run strava_to_garmin_sync.py instead
    print("Skipping full activities.json regeneration for COM->CN sync.")
    print(
        "Run garmin_sync.py or strava_to_garmin_sync.py separately for local tracking."
    )

    print("\nSync completed!")
