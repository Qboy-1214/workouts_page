"""
Sync activities from Garmin International (COM) to Garmin China (CN).

Workflow:
1. Download activities from Garmin COM
2. Upload to Garmin CN

This is used after strava_to_garmin_sync.py syncs from Strava to Garmin COM.
"""

import argparse
import asyncio
import os
import sys


from config import FIT_FOLDER, GPX_FOLDER, JSON_FILE, SQL_FILE
from garmin_sync import Garmin, get_downloaded_ids, restore_or_login
from garmin_sync import download_new_activities
from utils import make_activities_file

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

    options = parser.parse_args()
    is_only_running = options.only_run

    # Priority: environment variables > command line args
    cn_username = os.getenv("GARMIN_CN_USERNAME") or options.cn_username
    cn_password = os.getenv("GARMIN_CN_PASSWORD") or options.cn_password
    com_username = os.getenv("GARMIN_COM_USERNAME") or options.com_username
    com_password = os.getenv("GARMIN_COM_PASSWORD") or options.com_password

    if not cn_username or not cn_password or not com_username or not com_password:
        print(
            "Missing arguments: please provide --cn-username/--cn-password and --com-username/--com-password"
        )
        print(
            "Or set environment variables: GARMIN_CN_USERNAME, GARMIN_CN_PASSWORD, GARMIN_COM_USERNAME, GARMIN_COM_PASSWORD"
        )
        sys.exit(1)

    # Step 1:
    # Download activities from Garmin COM to local folder

    # load synced activity list
    downloaded_fit = get_downloaded_ids(FIT_FOLDER)
    downloaded_gpx = get_downloaded_ids(GPX_FOLDER)
    downloaded_activity = list(set(downloaded_fit + downloaded_gpx))

    folder = FIT_FOLDER
    # make gpx or tcx dir
    if not os.path.exists(folder):
        os.mkdir(folder)

    # Login to Garmin COM
    print("Logging into Garmin COM (International)...")
    garmin_com_client = restore_or_login(com_username, com_password, "COM")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    future = asyncio.ensure_future(
        download_new_activities(
            garmin_com_client,
            "COM",
            downloaded_activity,
            is_only_running,
            folder,
            "fit",
        )
    )
    loop.run_until_complete(future)
    new_ids, id2title = future.result()

    to_upload_files = []
    for i in new_ids:
        if os.path.exists(os.path.join(FIT_FOLDER, f"{i}.fit")):
            # upload fit files
            to_upload_files.append(os.path.join(FIT_FOLDER, f"{i}.fit"))
        elif os.path.exists(os.path.join(FIT_FOLDER, f"{i}.tcx")):
            # upload tcx files (garminconnect may return tcx instead of fit)
            to_upload_files.append(os.path.join(FIT_FOLDER, f"{i}.tcx"))
        elif os.path.exists(os.path.join(GPX_FOLDER, f"{i}.gpx")):
            # upload gpx files which are manually uploaded to garmin connect
            to_upload_files.append(os.path.join(GPX_FOLDER, f"{i}.gpx"))

    print(f"Files to upload to CN: {len(to_upload_files)}")
    if to_upload_files:
        print("Files: " + " ".join(to_upload_files))

    if to_upload_files:
        # Login to Garmin CN
        print("Logging into Garmin CN...")
        garmin_cn_client = restore_or_login(cn_username, cn_password, "CN")
        garmin_cn_wrapper = Garmin(garmin_cn_client, "CN", is_only_running)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        future = asyncio.ensure_future(
            garmin_cn_wrapper.upload_activities_files(to_upload_files)
        )
        loop.run_until_complete(future)

    # Step 2:
    # Generate track from fit/gpx/tcx file
    make_activities_file(
        SQL_FILE, GPX_FOLDER, JSON_FILE, file_suffix="gpx", activity_title_dict=id2title
    )
    make_activities_file(
        SQL_FILE, FIT_FOLDER, JSON_FILE, file_suffix="fit", activity_title_dict=id2title
    )
    make_activities_file(
        SQL_FILE, FIT_FOLDER, JSON_FILE, file_suffix="tcx", activity_title_dict=id2title
    )
