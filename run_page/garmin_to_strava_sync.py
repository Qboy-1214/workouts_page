"""
new garmin ids to strava;
not the same logic as nike_to_strava_sync
"""

import argparse
import asyncio
import os
import sys
import time

from config import FOLDER_DICT
from garmin_sync import (
    Garmin,
    download_new_activities,
    get_downloaded_ids,
    restore_or_login,
)
from strava_sync import run_strava_sync
from utils import make_strava_client, upload_file_to_strava

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("strava_client_id", help="strava client id")
    parser.add_argument("strava_client_secret", help="strava client secret")
    parser.add_argument("strava_refresh_token", help="strava refresh token")
    parser.add_argument(
        "--garmin-username", dest="garmin_username", help="Garmin username (email)"
    )
    parser.add_argument(
        "--garmin-password", dest="garmin_password", help="Garmin password"
    )
    parser.add_argument(
        "--is-cn",
        dest="is_cn",
        action="store_true",
        help="if garmin account is cn",
    )
    parser.add_argument(
        "--tcx",
        dest="download_file_type",
        action="store_const",
        const="tcx",
        default="gpx",
        help="to download personal documents or ebook",
    )
    options = parser.parse_args()
    strava_client = make_strava_client(
        options.strava_client_id,
        options.strava_client_secret,
        options.strava_refresh_token,
    )
    garmin_auth_domain = "CN" if options.is_cn else "COM"
    file_type = options.download_file_type

    # Priority: environment variables > command line args
    if garmin_auth_domain == "CN":
        garmin_username = os.getenv("GARMIN_CN_USERNAME") or options.garmin_username
        garmin_password = os.getenv("GARMIN_CN_PASSWORD") or options.garmin_password
    else:
        garmin_username = os.getenv("GARMIN_COM_USERNAME") or options.garmin_username
        garmin_password = os.getenv("GARMIN_COM_PASSWORD") or options.garmin_password

    if not garmin_username or not garmin_password:
        print(f"Missing Garmin credentials for {garmin_auth_domain}")
        print(
            "Set environment variables: GARMIN_{DOMAIN}_USERNAME and GARMIN_{DOMAIN}_PASSWORD"
        )
        sys.exit(1)

    print(f"[main] Logging in to Garmin {garmin_auth_domain}...")
    garmin_client = restore_or_login(
        garmin_username, garmin_password, garmin_auth_domain
    )
    garmin_wrapper = Garmin(garmin_client, garmin_auth_domain)

    is_only_running = False
    folder = FOLDER_DICT.get(file_type, "gpx")
    downloaded_ids = get_downloaded_ids(folder)

    loop = asyncio.get_event_loop()
    future = asyncio.ensure_future(
        download_new_activities(
            garmin_wrapper,
            garmin_auth_domain,
            downloaded_ids,
            is_only_running,
            folder,
            file_type,
        )
    )
    loop.run_until_complete(future)
    new_ids, id2title = future.result()
    print(f"To upload to strava {len(new_ids)} files")
    index = 1
    for i in new_ids:
        f = os.path.join(folder, f"{i}.{file_type}")
        upload_file_to_strava(strava_client, f, file_type, False)
        if index % 10 == 0:
            print("For the rate limit will sleep 10s")
            time.sleep(10)
        index += 1
        time.sleep(1)

    # Run the strava sync
    run_strava_sync(
        options.strava_client_id,
        options.strava_client_secret,
        options.strava_refresh_token,
    )
