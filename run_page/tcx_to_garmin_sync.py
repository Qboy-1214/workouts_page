import argparse
import asyncio
import os
import sys
from datetime import datetime

from config import TCX_FOLDER
from garmin_sync import Garmin, restore_or_login
from tcxreader.tcxreader import TCXReader


def get_to_generate_files(last_time):
    """
    return to one sorted list for next time upload
    """
    file_names = os.listdir(TCX_FOLDER)
    tcx = TCXReader()
    tcx_files = [
        (
            tcx.read(os.path.join(TCX_FOLDER, i), only_gps=False),
            os.path.join(TCX_FOLDER, i),
        )
        for i in file_names
        if i.endswith(".tcx")
    ]
    tcx_files_dict = {
        int(i[0].trackpoints[0].time.timestamp()): i[1]
        for i in tcx_files
        if len(i[0].trackpoints) > 0
        and int(i[0].trackpoints[0].time.timestamp()) > last_time
    }

    dict(sorted(tcx_files_dict.items()))

    return tcx_files_dict.values()


async def upload_tcx_files_to_garmin(options):
    print("Need to load all tcx files maybe take some time")
    garmin_auth_domain = "CN" if options.is_cn else "COM"

    # Priority: environment variables > command line args
    if garmin_auth_domain == "CN":
        garmin_username = os.getenv("GARMIN_CN_USERNAME") or getattr(
            options, "garmin_username", None
        )
        garmin_password = os.getenv("GARMIN_CN_PASSWORD") or getattr(
            options, "garmin_password", None
        )
    else:
        garmin_username = os.getenv("GARMIN_COM_USERNAME") or getattr(
            options, "garmin_username", None
        )
        garmin_password = os.getenv("GARMIN_COM_PASSWORD") or getattr(
            options, "garmin_password", None
        )

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

    last_time = 0
    if not options.all:
        print("upload new tcx to Garmin")
        last_activity = await garmin_wrapper.get_activities(0, 1)
        if not last_activity:
            print("no garmin activity")
        else:
            after_datetime_str = last_activity[0]["startTimeGMT"]
            after_datetime = datetime.fromisoformat(after_datetime_str)
            if after_datetime.tzinfo is not None:
                after_datetime = after_datetime.astimezone().replace(tzinfo=None)
            last_time = datetime.timestamp(after_datetime)
    else:
        print("Need to load all tcx files maybe take some time")
    to_upload_dict = get_to_generate_files(last_time)

    await garmin_wrapper.upload_activities_files(to_upload_dict)


if __name__ == "__main__":
    if not os.path.exists(TCX_FOLDER):
        os.mkdir(TCX_FOLDER)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--garmin-username", dest="garmin_username", help="Garmin username (email)"
    )
    parser.add_argument(
        "--garmin-password", dest="garmin_password", help="Garmin password"
    )
    parser.add_argument(
        "--all",
        dest="all",
        action="store_true",
        help="if upload to strava all without check last time",
    )
    parser.add_argument(
        "--is-cn",
        dest="is_cn",
        action="store_true",
        help="if garmin account is cn",
    )
    loop = asyncio.get_event_loop()
    future = asyncio.ensure_future(upload_tcx_files_to_garmin(parser.parse_args()))
    loop.run_until_complete(future)
