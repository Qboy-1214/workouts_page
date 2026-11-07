import argparse
import asyncio
import os
import sys
from datetime import datetime

import requests as _req
from config import FIT_FOLDER, GPX_FOLDER, TCX_FOLDER
from garmin_sync import Garmin, restore_or_login
from garmin_sync_global_cn import (
    download_with_cn_filter,
    get_cn_latest_start_time,
    upload_activities_to_garmin_cn,
)
from strava_sync import run_strava_sync
from stravaweblib import DataFormat, WebClient

# Direct access to stravaweblib internals for cookie-based session
from stravaweblib.webclient import BASE_URL

from utils import make_strava_client


async def upload_to_activities(
    garmin_client, strava_client, strava_web_client, format, use_fake_garmin_device
):
    print(
        f"[upload_to_activities] Starting upload to Garmin, auth domain: {garmin_client.auth_domain}"
    )
    last_activity = await garmin_client.get_activities(0, 1)
    if not last_activity:
        print("no garmin activity")
        filters = {}
    else:
        # is this startTimeGMT must have ?
        after_datetime_str = last_activity[0]["startTimeGMT"]
        after_datetime = datetime.fromisoformat(after_datetime_str)
        if after_datetime.tzinfo is not None:
            after_datetime = after_datetime.astimezone().replace(tzinfo=None)
        print("garmin last activity date: ", after_datetime)
        filters = {"after": after_datetime}
    strava_activities = list(strava_client.get_activities(**filters))
    files_list = []
    print("strava activities size: ", len(strava_activities))
    if not strava_activities:
        print("no strava activity to upload")
        return files_list

    # strava rate limit
    for i in sorted(strava_activities, key=lambda i: int(i.id)):
        # Extract sport type from sport_type field (contains actual sport like Squash, Soccer)
        # Fall back to type if sport_type not available
        if hasattr(i, "sport_type") and i.sport_type:
            sport_type = (
                i.sport_type.root
                if hasattr(i.sport_type, "root")
                else str(i.sport_type)
            )
        elif hasattr(i.type, "root"):
            sport_type = i.type.root
        else:
            sport_type = str(i.type) if i.type else "other"
        # Extract activity name from Strava
        activity_name = i.name if hasattr(i, "name") and i.name else None
        # Extract activity start time (for matching after upload)
        activity_start_time = i.start_date or i.start_date_local or None
        print(
            f"[download] Getting activity data for activity ID: {i.id}, sport_type: {sport_type}, name: {activity_name}, start: {activity_start_time}"
        )
        try:
            data = strava_web_client.get_activity_data(
                i.id, fmt=format, json_fmt=DataFormat.TCX
            )
            # Wrap the data with sport type, activity name, and start time
            # Format: (data, sport_type, activity_name, activity_start_time)
            wrapped_data = (data, sport_type, activity_name, activity_start_time)
            print(
                f"[download] Got activity data: {data.filename}, sport_type: {sport_type}, name: {activity_name}, start time: {activity_start_time}"
            )
            files_list.append(wrapped_data)
        except Exception as ex:
            print("get strava data error: ", ex)
    print(f"[download] Downloaded {len(files_list)} files, starting upload...")
    await garmin_client.upload_activities_original_from_strava(
        files_list, use_fake_garmin_device
    )
    print("[upload_to_activities] Done")
    return files_list


def run_cn_mirror(garmin_com_wrapper):
    """Mirror new COM activities to Garmin CN, reusing this process's COM login.

    Garmin throttles fresh COM credential logins (roughly one per ~1.5-4h
    window and each failed attempt extends the lockout), so the COM->CN mirror
    must share the COM client that logged in for the Strava->COM upload instead
    of logging in a second time. CN itself logs in via garth and is not
    throttled.
    """
    cn_username = os.getenv("GARMIN_CN_USERNAME")
    cn_password = os.getenv("GARMIN_CN_PASSWORD")
    if not cn_username or not cn_password:
        print("[mirror] GARMIN_CN_USERNAME/GARMIN_CN_PASSWORD not set — skip CN mirror")
        return

    garmin_cn_client = restore_or_login(cn_username, cn_password, "CN")
    print("[mirror] Garmin CN login successful")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        cn_latest_start_time = loop.run_until_complete(
            get_cn_latest_start_time(garmin_cn_client)
        )
        print(
            f"[mirror] CN latest activity start time: {cn_latest_start_time or 'None'}"
        )

        future = asyncio.ensure_future(
            download_with_cn_filter(
                garmin_com_wrapper,
                False,
                FIT_FOLDER,
                "tcx",
                since_start_time=cn_latest_start_time,
            )
        )
        loop.run_until_complete(future)
        new_ids, id2title, id2type, id2start_time = future.result()

        to_upload_files = []
        for i in new_ids:
            fit_path = os.path.join(FIT_FOLDER, f"{i}.fit")
            tcx_path = os.path.join(TCX_FOLDER, f"{i}.tcx")
            gpx_path = os.path.join(GPX_FOLDER, f"{i}.gpx")
            if os.path.exists(fit_path) and os.path.getsize(fit_path) > 1000:
                print(f"[mirror] Will upload .fit: {i}")
                to_upload_files.append(fit_path)
            elif os.path.exists(tcx_path) and os.path.getsize(tcx_path) > 1000:
                print(f"[mirror] Will upload .tcx: {i}")
                to_upload_files.append(tcx_path)
            elif os.path.exists(gpx_path):
                print(f"[mirror] Will upload .gpx: {i}")
                to_upload_files.append(gpx_path)

        if not to_upload_files:
            print("[mirror] No new activities to upload to CN.")
            return

        print(f"[mirror] Uploading {len(to_upload_files)} activities to Garmin CN...")
        garmin_cn_wrapper = Garmin(garmin_cn_client, "CN", False)
        upload_future = asyncio.ensure_future(
            upload_activities_to_garmin_cn(
                garmin_cn_wrapper,
                to_upload_files,
                id2title,
                id2type,
                id2start_time,
            )
        )
        loop.run_until_complete(upload_future)
        print("[mirror] Upload completed!")
    finally:
        loop.close()


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
    parser.add_argument("strava_email", nargs="?", help="email of strava")
    parser.add_argument("strava_password", nargs="?", help="password of strava")
    parser.add_argument("strava_jwt", nargs="?", help="jwt token of strava")
    parser.add_argument(
        "--session-cookie",
        dest="session_cookie",
        help="_strava4_session cookie value for strava web login",
    )
    parser.add_argument(
        "--use_fake_garmin_device",
        action="store_true",
        default=False,
        help="whether to use a faked Garmin device",
    )
    parser.add_argument(
        "--with-cn-mirror",
        dest="with_cn_mirror",
        action="store_true",
        default=False,
        help="after uploading to COM, mirror new COM activities to Garmin CN "
        "reusing the same COM login (CN credentials via GARMIN_CN_USERNAME/"
        "GARMIN_CN_PASSWORD env). One fresh COM login per run — see note below",
    )
    # Note: COM credential logins are heavily throttled by Garmin (roughly one
    # fresh login per ~1.5-4h window per account, and each failed attempt
    # extends the lockout). That is why the CN mirror must reuse this
    # process's COM login instead of running as a second login somewhere else.
    options = parser.parse_args()

    print("[main] STRAVA_TO_GARMIN_SYNC START - syncing to COM (Garmin International)")
    print(
        "  Note: For CN sync, run garmin_sync_global_cn.py separately after COM sync completes"
    )

    strava_client = make_strava_client(
        options.strava_client_id,
        options.strava_client_secret,
        options.strava_refresh_token,
    )
    # Get auth credentials from command line args
    jwt = (
        options.strava_jwt
        if hasattr(options, "strava_jwt") and options.strava_jwt
        else ""
    )
    email = options.strava_email if hasattr(options, "strava_email") else ""
    password = options.strava_password if hasattr(options, "strava_password") else ""

    # STRAVA_JWT secret may contain either:
    # 1. A real JWT token (3 dot-separated parts)
    # 2. A _strava4_session cookie value (Strava's new session mechanism)
    # Detect by format and use appropriate login method.
    if jwt:
        parts = jwt.split(".")
        if len(parts) == 3:
            print("Using JWT for Strava web login (passwordless mode)")
            strava_web_client = WebClient(
                access_token=strava_client.access_token,
                jwt=jwt,
            )
        else:
            # Treat as _strava4_session cookie - directly create session without WebClient __init__
            print(
                "Using _strava4_session cookie for Strava web login (JWT secret contains session cookie)"
            )
            print(f"[main] Session cookie value length: {len(jwt)}")

            # Create a minimal web client by subclassing to bypass __init__
            class _SessionClient(WebClient):
                pass  # __init__ not called - we'll set everything manually

            strava_web_client = _SessionClient.__new__(_SessionClient)
            # Set required stravalib.Client attributes that would be set in __init__
            strava_web_client.protocol = "https"
            strava_web_client.host = "www.strava.com"
            strava_web_client._session = _req.Session()
            strava_web_client._session.headers.update(
                {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
            )
            # Set the _strava4_session cookie
            strava_web_client._session.cookies.set(
                "_strava4_session", jwt, domain=".strava.com", secure=True
            )
            # Verify by fetching /me to get athlete ID
            try:
                print(f"[main] Verifying session cookie via {BASE_URL}/me...")
                resp = strava_web_client._session.get(
                    f"{BASE_URL}/me", allow_redirects=False
                )
                print(
                    f"[main] /me response status: {resp.status_code}, location: {resp.headers.get('Location', 'none')}"
                )
                if resp.status_code == 302:
                    redirect_url = resp.headers.get("Location", "")
                    # Extract athlete ID from redirect URL like https://www.strava.com/athletes/140877474
                    if "/athletes/" in redirect_url:
                        athlete_id = redirect_url.split("/athletes/")[-1].split("?")[0]
                        strava_web_client._session.cookies.set(
                            "strava_remember_id",
                            athlete_id,
                            domain=".strava.com",
                            secure=True,
                        )
                        print(
                            f"[main] Session cookie verified, athlete ID: {athlete_id}"
                        )
                    else:
                        print(
                            f"[main] WARNING: /me redirected to unexpected URL: {redirect_url}"
                        )
                elif resp.status_code == 200:
                    print(
                        f"[main] WARNING: /me returned 200 (not authenticated), body snippet: {resp.text[:200]}"
                    )
                else:
                    print(
                        f"[main] WARNING: /me returned unexpected status {resp.status_code}"
                    )
                strava_web_client._session.cookies.set(
                    "strava_remember_token", jwt, domain=".strava.com", secure=True
                )
            except Exception as e:
                print(f"Warning: couldn't verify session cookie: {e}")
    elif email and password:
        print("Using email + password for Strava web login")
        strava_web_client = WebClient(
            access_token=strava_client.access_token,
            email=email,
            password=password,
        )
    else:
        raise ValueError(
            "Must provide STRAVA_JWT (can be JWT token or _strava4_session cookie), or both STRAVA_EMAIL and STRAVA_PASSWORD"
        )

    # Always sync to COM (Garmin International)
    garmin_auth_domain = "COM"

    # Priority: environment variables > command line args
    garmin_username = os.getenv("GARMIN_COM_USERNAME") or options.garmin_username
    garmin_password = os.getenv("GARMIN_COM_PASSWORD") or options.garmin_password

    print(
        f"[main] Garmin auth domain: {garmin_auth_domain}, username set: {bool(garmin_username)}, password set: {bool(garmin_password)}"
    )

    if not garmin_username or not garmin_password:
        print(
            "Missing Garmin credentials: please provide --garmin-username/--garmin-password"
        )
        print(
            "Or set environment variables: GARMIN_COM_USERNAME and GARMIN_COM_PASSWORD"
        )
        sys.exit(1)

    garmin_client = None
    try:
        print(f"[main] Logging in to Garmin {garmin_auth_domain}...")
        garmin_client = restore_or_login(
            garmin_username, garmin_password, garmin_auth_domain
        )
        print(
            f"[main] Garmin login successful, client type: {type(garmin_client).__name__}"
        )
    except Exception as err:
        print(f"[main] Garmin login failed: {err}")
        garmin_client = None

    garmin_wrapper = None
    if garmin_client is None:
        print("[main] Skipping upload_to_activities (no garmin client)")
    else:
        garmin_wrapper = Garmin(garmin_client, garmin_auth_domain, False)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            future = asyncio.ensure_future(
                upload_to_activities(
                    garmin_wrapper,
                    strava_client,
                    strava_web_client,
                    DataFormat.ORIGINAL,
                    options.use_fake_garmin_device,
                )
            )
            loop.run_until_complete(future)
        except Exception as err:
            print(f"[main] Upload to activities failed: {err}")
        finally:
            loop.close()

    # Step 4: mirror new COM activities down to Garmin CN with the SAME COM
    # login (a second fresh COM login would trip Garmin's throttle).
    if options.with_cn_mirror:
        if garmin_wrapper is None:
            print("[mirror] Skip CN mirror (no COM client)")
        else:
            try:
                run_cn_mirror(garmin_wrapper)
            except Exception as err:
                print(f"[mirror] CN mirror failed: {err}")

    print("[main] Running strava sync...")
    run_strava_sync(
        options.strava_client_id,
        options.strava_client_secret,
        options.strava_refresh_token,
    )
    print("[main] STRAVA_TO_GARMIN_SYNC COMPLETE")
