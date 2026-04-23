"""
Python 3 API wrapper for Garmin Connect to get your statistics.
Uses garminconnect library for both International (COM) and China (CN) regions.
"""

import argparse
import asyncio
import datetime as dt
import logging
import os
import pickle
import sys
import time
import traceback
import zipfile

from lxml import etree

import aiofiles
from garminconnect import (
    Garmin as GarminConnectLib,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

# Import garth for CN authentication fallback
try:
    from garmin_cn_garth import GarminCngarthClient, create_garth_cn_client

    GARTH_CN_AVAILABLE = True
except ImportError:
    GARTH_CN_AVAILABLE = False
    print("[restore_or_login] Warning: garth not available for CN fallback")
from config import FOLDER_DICT, JSON_FILE, SQL_FILE
from garmin_device_adaptor import process_garmin_data
from utils import make_activities_file_only

# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

GARMIN_COM_URL_DICT = {
    "SSO_URL_ORIGIN": "https://sso.garmin.com",
    "SSO_URL": "https://sso.garmin.com/sso",
    "MODERN_URL": "https://connectapi.garmin.com",
    "SIGNIN_URL": "https://sso.garmin.com/sso/signin",
    "UPLOAD_URL": "https://connectapi.garmin.com/upload-service/upload/",
    "ACTIVITY_URL": "https://connectapi.garmin.com/activity-service/activity/{activity_id}",
}

GARMIN_CN_URL_DICT = {
    "SSO_URL_ORIGIN": "https://sso.garmin.cn",
    "SSO_URL": "https://sso.garmin.cn/sso",
    "MODERN_URL": "https://connectapi.garmin.cn",
    "SIGNIN_URL": "https://sso.garmin.cn/sso/signin",
    "UPLOAD_URL": "https://connectapi.garmin.cn/upload-service/upload/",
    "ACTIVITY_URL": "https://connectapi.garmin.cn/activity-service/activity/{activity_id}",
}

# Strava to Garmin sport type mapping (Garmin compatible format)
# Garmin typeKey reference: https://github.com/pe-st/garmin-connect-export/blob/master/json/activityTypes.json
STRAVA_TO_GARMIN_SPORT = {
    # Generic
    "Workout": "other",  # Generic workout, will try to infer from filename
    # Running
    "Run": "running",
    "Trail Run": "trail_running",
    "Street Run": "street_running",
    "Track Run": "track_running",
    "Treadmill": "treadmill_running",
    "Virtual Run": "virtual_run",
    # Cycling
    "Ride": "cycling",
    "Mountain Bike": "mountain_biking",
    "Road Bike": "road_biking",
    "EBikeRide": "e_bike_mountain",
    "VirtualRide": "virtual_ride",
    "Indoor Ride": "indoor_cycling",
    "Gravel Ride": "gravel_cycling",
    "Cyclocross": "cyclocross",
    # Winter sports
    "Ski": "resort_skiing",
    "Backcountry Ski": "backcountry_skiing",
    "Snowboard": "resort_snowboarding",
    "Backcountry Snowboard": "backcountry_snowboarding",
    "Cross Country Ski": "cross_country_skiing_ws",
    "Snowshoe": "snow_shoe_ws",
    # Water sports
    "Swim": "swimming",
    "Rowing": "rowing_v2",
    "Kayaking": "kayaking_v2",
    "Stand Up Paddling": "stand_up_paddleboarding_v2",
    "Surfing": "surfing_v2",
    "Windsurfing": "windsufing_v2",
    "Kite Surfing": "kiteboarding_v2",
    "Wakeboarding": "wakeboarding_v2",
    "Wakesurfing": "wakesurfing",
    "Water Skiing": "waterskiing",
    # Outdoor
    "Walk": "walking",
    "Hike": "hiking",
    "Rock Climbing": "rock_climbing",
    # Team sports
    "Soccer": "soccer",
    "Football": "american_football",
    "Basketball": "basketball",
    "Baseball": "baseball",
    "Volleyball": "volleyball",
    "Softball": "softball",
    "Rugby": "rugby",
    "Cricket": "cricket",
    "Ice Hockey": "ice_hockey",
    "Field Hockey": "field_hockey",
    "Lacrosse": "lacrosse",
    "Ultimate": "ultimate_disc",
    # Racket sports
    "Tennis": "tennis_v2",
    "VirtualTennis": "tennis_v2",  # Virtual tennis
    "Pickleball": "pickleball",
    "Squash": "squash",
    "Racquetball": "racquetball",
    "Badminton": "badminton",
    "Table Tennis": "table_tennis",
    "Paddle Tennis": "platform_tennis",
    "Padel": "paddelball",
    # Fitness & Gym
    "Weightlifting": "strength_training",
    "Elliptical": "elliptical",
    "Stair Stepper": "stair_climbing",
    "Rowing Machine": "indoor_rowing",
    "Yoga": "yoga",
    "Pilates": "pilates",
    "HIIT": "hiit",
    "Dance": "dance",
    "Jump Rope": "jump_rope",
    "Boxing": "boxing",
    "Martial Arts": "mixed_martial_arts",
    "Archery": "archery",
    # Other
    "Golf": "golf",
    "Inline Skating": "inline_skating",
    "Skateboarding": "other",
    "Meditation": "meditation",
    "BMX": "bmx",
    # Fallback mapping for common sport keywords
    "Virtual": "other",  # Generic virtual activities
}


def fix_tcx_sport_type(file_path, strava_sport_type=None):
    """
    Fix TCX file Sport field to Garmin compatible format.
    Strava uses formats like 'Run', 'Hike', 'Swim' which Garmin may not recognize.
    This function converts them to Garmin API compatible sport types.
    """
    import traceback

    try:
        from lxml import etree

        # Use the original file path (URL-encoded) - do NOT decode
        print(f"[fix_tcx_sport_type] Processing file: {file_path}")

        tree = etree.parse(file_path)
        root = tree.getroot()

        # Define namespace
        ns = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd"}

        # Find all Activity elements
        activities = root.findall(".//tcx:Activity", ns)
        if not activities:
            # Try without namespace (some TCX files don't use namespace)
            activities = root.findall(".//Activity")

        modified = False
        for activity in activities:
            sport_attr = activity.get("Sport")

            # Determine which sport type to use (prefer Strava type if provided)
            sport_to_convert = strava_sport_type if strava_sport_type else sport_attr

            print(
                f"[fix_tcx_sport_type] TCX file Sport: '{sport_attr}', Strava type: '{strava_sport_type}'"
            )

            if sport_to_convert and sport_to_convert in STRAVA_TO_GARMIN_SPORT:
                new_sport = STRAVA_TO_GARMIN_SPORT[sport_to_convert]
                print(f"Fixing TCX sport: {sport_to_convert} -> {new_sport}")
                activity.set("Sport", new_sport)
                modified = True
            elif sport_attr:
                # Try partial match if exact match fails
                for key, value in STRAVA_TO_GARMIN_SPORT.items():
                    if (
                        key.lower() in sport_attr.lower()
                        or sport_attr.lower() in key.lower()
                    ):
                        print(
                            f"Partial match - Fixing TCX sport: {sport_attr} -> {value}"
                        )
                        activity.set("Sport", value)
                        modified = True
                        break

        if modified:
            tree.write(
                file_path,
                encoding="utf-8",
                xml_declaration=True,
                pretty_print=True,
            )
            print(f"TCX sport type fixed: {file_path}")

    except Exception as e:
        print(f"Failed to fix TCX sport type: {e}")
        traceback.print_exc()


class Garmin:
    """
    Garmin client for both COM and CN regions using garminconnect library.
    """

    def __init__(self, client, auth_domain, is_only_running=False):
        """
        Init module
        """
        self.auth_domain = auth_domain.upper() if auth_domain else "COM"
        self.is_only_running = is_only_running
        self._client = client  # GarminConnectLib or GarthClientWrapper instance

        # Check if using garth client (CN with garth)
        self._is_garth_client = (
            hasattr(client, "_garth_client")
            or type(client).__name__ == "GarminCngarthClient"
        )

        # Select URL dict based on auth_domain
        if self.auth_domain == "CN":
            url_dict = GARMIN_CN_URL_DICT
        else:
            url_dict = GARMIN_COM_URL_DICT
        self.modern_url = url_dict.get("MODERN_URL", "")
        self.upload_url = url_dict.get("UPLOAD_URL", "")

    async def get_activities(self, start, limit):
        """
        Fetch available activities
        """
        if self._client is None:
            print("[Garmin.get_activities] No garmin client, returning empty list")
            return []

        # Handle garth client differently
        if self._is_garth_client:
            activities = await asyncio.to_thread(
                self._client.get_activities, start, limit
            )
        else:
            # Use garminconnect library
            activities = await asyncio.to_thread(
                self._client.get_activities, start, limit
            )
            # Filter by activity type if needed
            if self.is_only_running:
                activities = [
                    a
                    for a in activities
                    if a.get("activityType", {}).get("typeKey") == "running"
                ]
        return activities

    async def get_activity_summary(self, activity_id):
        """
        Fetch activity summary
        """
        if self._client is None:
            print("[Garmin.get_activity_summary] No garmin client, returning empty")
            return {}

        # Handle garth client differently
        if self._is_garth_client:
            return await asyncio.to_thread(
                self._client.get_activity_summary, activity_id
            )
        else:
            # Use garminconnect library (activity_id must be int)
            return await asyncio.to_thread(self._client.get_activity, int(activity_id))

    async def download_activity(self, activity_id, file_type="gpx"):
        """
        Download activity file (GPX, TCX, FIT)
        """
        if self._client is None:
            print("[Garmin.download_activity] No garmin client, returning empty")
            return b""

        # Handle garth client differently
        if self._is_garth_client:
            return await asyncio.to_thread(
                self._client.download_activity, int(activity_id), file_type
            )
        else:
            # Use garminconnect library
            # Convert file_type string to garminconnect enum
            fmt_map = {
                "gpx": GarminConnectLib.ActivityDownloadFormat.GPX,
                "tcx": GarminConnectLib.ActivityDownloadFormat.TCX,
                "fit": GarminConnectLib.ActivityDownloadFormat.ORIGINAL,
            }
            dl_fmt = fmt_map.get(file_type, GarminConnectLib.ActivityDownloadFormat.GPX)
            return await asyncio.to_thread(
                self._client.download_activity, int(activity_id), dl_fmt=dl_fmt
            )

    async def upload_activities_original_from_strava(
        self, datas, use_fake_garmin_device=False
    ):
        if self._client is None:
            print(
                "[Garmin.upload_activities_original_from_strava] No garmin client, skipping upload"
            )
            return
        print(
            "start upload activities to garmin!, use_fake_garmin_device:",
            use_fake_garmin_device,
        )
        for item in datas:
            # Unpack data, sport type, activity name, and start time (wrapped as tuple in strava_to_garmin_sync.py)
            # Format: (data, sport_type, activity_name, activity_start_time) or (data, sport_type, activity_start_time) or (data, sport_type) or just data
            if isinstance(item, tuple) and len(item) == 4:
                data, strava_sport_type, activity_name, activity_start_time = item
            elif isinstance(item, tuple) and len(item) == 3:
                data, strava_sport_type, activity_start_time = item
                activity_name = None
            elif isinstance(item, tuple) and len(item) == 2:
                data, strava_sport_type = item
                activity_start_time = None
                activity_name = None
            else:
                data = item
                strava_sport_type = None
                activity_start_time = None
                activity_name = None
            print(
                f"[DEBUG] Processing activity: sport_type={strava_sport_type}, name={activity_name}, start_time={activity_start_time}"
            )
            with open(data.filename, "wb") as f:
                for chunk in data.content:
                    f.write(chunk)

            # Fix TCX sport type before upload
            ext = os.path.splitext(data.filename)[-1].lower()
            if ext in [".tcx", ".TCX"]:
                fix_tcx_sport_type(data.filename, strava_sport_type)

            with open(data.filename, "rb") as f:
                file_body = process_garmin_data(f, use_fake_garmin_device)

            # Determine file extension from original filename
            ext = os.path.splitext(data.filename)[-1].lower().lstrip(".")

            # Use garminconnect (works for both COM and CN regions)
            import tempfile

            # process_garmin_data may return bytes or BytesIO
            data_bytes = file_body.read() if hasattr(file_body, "read") else file_body
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(data_bytes)
                tmp_path = tmp.name
            try:
                result = await asyncio.to_thread(self._client.upload_activity, tmp_path)
                print("garmin upload success: ", result)

                # Set correct activity type after upload
                print(
                    f"[DEBUG] Checking sport type: strava_sport_type={strava_sport_type}"
                )

                # Determine the final Garmin sport type
                garmin_sport = None

                # If strava_sport_type is in mapping, use it
                if strava_sport_type and strava_sport_type in STRAVA_TO_GARMIN_SPORT:
                    garmin_sport = STRAVA_TO_GARMIN_SPORT[strava_sport_type]
                    print(
                        f"[DEBUG] Sport type {strava_sport_type} mapped to garmin_sport={garmin_sport}"
                    )

                # If strava_sport_type maps to "other" or not in mapping, try to infer from filename
                if not garmin_sport or garmin_sport == "other":
                    # Try to infer sport type from filename (e.g., vr_tennis.tcx -> tennis)
                    filename_lower = data.filename.lower()
                    print(
                        f"[DEBUG] Trying to infer sport from filename: {data.filename}"
                    )

                    # Common filename patterns for VR activities
                    filename_to_sport = {
                        "vr_tennis": "tennis_v2",
                        "vr_riding": "virtual_ride",
                        "vr_run": "virtual_run",
                        "vr_row": "indoor_rowing",
                        "tennis": "tennis_v2",
                        "squash": "squash",
                        "badminton": "badminton",
                        "racquetball": "racquetball",
                        "table_tennis": "table_tennis",
                        "ping_pong": "table_tennis",
                        "workout": "other",
                    }

                    for pattern, sport in filename_to_sport.items():
                        if pattern in filename_lower:
                            garmin_sport = sport
                            print(
                                f"[DEBUG] Inferred sport from filename: {pattern} -> {sport}"
                            )
                            break

                if garmin_sport and garmin_sport != "other":
                    # Get activity ID from response
                    try:
                        resp_data = result.json() if hasattr(result, "json") else result
                        detailed = (
                            resp_data.get("detailedImportResult", {})
                            if isinstance(resp_data, dict)
                            else {}
                        )
                        successes = (
                            detailed.get("successes", [])
                            if isinstance(detailed, dict)
                            else []
                        )
                        upload_id = detailed.get("uploadId")
                        upload_time = detailed.get("creationDate")
                        upload_file_size = detailed.get("fileSize")
                        print(
                            f"[DEBUG] upload uploadId: {upload_id}, creationDate: {upload_time}, fileSize: {upload_file_size}"
                        )

                        activity_id = None
                        if successes:
                            activity_id = successes[0].get("internalId") or successes[
                                0
                            ].get("activityId")
                        else:
                            # Try to find activity by activity start time from Strava
                            print("[DEBUG] Finding activity by start time...")
                            if activity_start_time:
                                try:
                                    activity_id = None
                                    # Extract date from activity_start_time
                                    activity_date = (
                                        activity_start_time.split("T")[0]
                                        if "T" in str(activity_start_time)
                                        else str(activity_start_time)[:10]
                                    )
                                    print(
                                        f"[DEBUG] Looking for activity with start time: {activity_start_time}, date: {activity_date}"
                                    )

                                    # Retry with delays to wait for processing
                                    for retry in range(4):
                                        if retry > 0:
                                            wait_time = 10 * retry
                                            print(
                                                f"[DEBUG] Retry {retry}, waiting {wait_time}s..."
                                            )
                                            await asyncio.sleep(wait_time)

                                        try:
                                            # Get activities for the activity date
                                            recent = await asyncio.to_thread(
                                                self._client.get_activities_by_date,
                                                activity_date,
                                                sortorder="desc",
                                            )
                                            print(
                                                f"[DEBUG] Got {len(recent)} activities for {activity_date}"
                                            )

                                            for act in recent:
                                                act_id = act.get("activityId")
                                                act_start = act.get(
                                                    "startTimeGMT"
                                                ) or act.get("startTime")
                                                act_title = act.get(
                                                    "activityName"
                                                ) or act.get("title")
                                                print(
                                                    f"[DEBUG] Checking: {act_id}, startTime: {act_start}, title: {act_title}"
                                                )

                                                # Match by activity start time from Strava (with 5 min tolerance)
                                                if act_start and activity_start_time:
                                                    try:
                                                        from datetime import (
                                                            datetime,
                                                        )

                                                        # Parse times
                                                        # Strava: "2026-04-22T14:33:44+00:00" or "2026-04-22 11:19:38+00:00"
                                                        # Garmin: "2026-04-22 14:33:44" or "2026-04-22T14:33:44Z"
                                                        strava_str = (
                                                            str(activity_start_time)
                                                            .replace("T", " ", 1)
                                                            .split("+")[0]
                                                            .split("Z")[0]
                                                            .strip()
                                                        )
                                                        garmin_str = (
                                                            str(act_start)
                                                            .replace("T", " ", 1)
                                                            .split("+")[0]
                                                            .split("Z")[0]
                                                            .strip()
                                                        )

                                                        # Parse datetime (handle both with and without microseconds)
                                                        strava_dt = (
                                                            datetime.fromisoformat(
                                                                strava_str
                                                            )
                                                        )
                                                        if "." not in garmin_str:
                                                            garmin_dt = (
                                                                datetime.strptime(
                                                                    garmin_str,
                                                                    "%Y-%m-%d %H:%M:%S",
                                                                )
                                                            )
                                                        else:
                                                            garmin_dt = (
                                                                datetime.fromisoformat(
                                                                    garmin_str.replace(
                                                                        " ", "T"
                                                                    )
                                                                )
                                                            )

                                                        # Calculate difference in seconds
                                                        diff_seconds = abs(
                                                            (
                                                                strava_dt - garmin_dt
                                                            ).total_seconds()
                                                        )
                                                        print(
                                                            f"[DEBUG] Time comparison: strava={strava_str}, garmin={garmin_str}, diff={diff_seconds}s"
                                                        )

                                                        # Match if within 5 minutes (300 seconds)
                                                        if diff_seconds <= 300:
                                                            activity_id = act_id
                                                            print(
                                                                f"[DEBUG] Found match! Activity ID: {activity_id}, time diff: {diff_seconds}s"
                                                            )
                                                            break
                                                    except Exception as time_e:
                                                        print(
                                                            f"[DEBUG] Time parse error: {time_e}"
                                                        )

                                            if activity_id:
                                                break

                                        except Exception as get_e:
                                            print(f"[DEBUG] Error: {get_e}")

                                except Exception as get_e:
                                    print(f"[DEBUG] Failed: {get_e}")
                                    import traceback

                                    traceback.print_exc()

                        if activity_id:
                            print(
                                f"Setting activity type to {garmin_sport} for activity {activity_id}"
                            )
                            # Get activity types to find type_id and parent_type_id
                            activity_types = await asyncio.to_thread(
                                self._client.get_activity_types
                            )
                            print(
                                f"[DEBUG] Total activity types: {len(activity_types)}"
                            )

                            # Debug: print all available typeKeys
                            all_type_keys = [t.get("typeKey") for t in activity_types]
                            print(
                                f"[DEBUG] Available typeKeys: {sorted(all_type_keys)}"
                            )

                            # Find exact match first
                            sport_type_info = next(
                                (
                                    t
                                    for t in activity_types
                                    if t.get("typeKey") == garmin_sport
                                ),
                                None,
                            )
                            print(
                                f"[DEBUG] Looking for typeKey='{garmin_sport}', found: {sport_type_info}"
                            )

                            # If not found, try case-insensitive match
                            if not sport_type_info:
                                for t in activity_types:
                                    if (
                                        t.get("typeKey", "").lower()
                                        == garmin_sport.lower()
                                    ):
                                        sport_type_info = t
                                        print(
                                            f"[DEBUG] Found match (case-insensitive): {sport_type_info}"
                                        )
                                        break

                            if sport_type_info:
                                print(
                                    f"[DEBUG] Found type info: typeId={sport_type_info.get('typeId')}, parentTypeId={sport_type_info.get('parentTypeId')}"
                                )
                                try:
                                    result = await asyncio.to_thread(
                                        self._client.set_activity_type,
                                        activity_id=int(activity_id),
                                        type_id=sport_type_info.get("typeId"),
                                        type_key=garmin_sport,
                                        parent_type_id=sport_type_info.get(
                                            "parentTypeId"
                                        ),
                                    )
                                    print(f"[DEBUG] set_activity_type result: {result}")
                                    print(f"Activity type set to {garmin_sport}")
                                except Exception as api_e:
                                    print(f"[DEBUG] API call failed: {api_e}")
                            else:
                                print(
                                    f"[ERROR] Could not find type info for '{garmin_sport}' in Garmin activity types"
                                )

                            # Set activity name from Strava if provided
                            if activity_name:
                                try:
                                    name_result = await asyncio.to_thread(
                                        self._client.set_activity_name,
                                        activity_id=int(activity_id),
                                        title=activity_name,
                                    )
                                    print(
                                        f"[DEBUG] set_activity_name result: {name_result}"
                                    )
                                    print(f"Activity name set to: {activity_name}")
                                except Exception as name_e:
                                    print(f"[DEBUG] set_activity_name failed: {name_e}")
                    except Exception as type_e:
                        print(f"Failed to set activity type: {type_e}")
                        import traceback

                        traceback.print_exc()
            except Exception as e:
                print("garmin upload failed: ", e)
                continue
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

    async def upload_activity_from_file(self, file):
        print("Uploading " + str(file))
        with open(file, "rb") as f:
            file_body = f.read()

        import tempfile

        ext = os.path.splitext(file)[-1].lower().lstrip(".")
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(file_body)
            tmp_path = tmp.name
        try:
            # Use garminconnect or garth for upload depending on client type
            if self._is_garth_client:
                result = await asyncio.to_thread(self._client.upload_activity, tmp_path)
            else:
                result = await asyncio.to_thread(self._client.upload_activity, tmp_path)
            print("garmin upload success: ", result)
        except Exception as e:
            # Check if it's a 409 Conflict error (activity already exists)
            error_str = str(e)
            if "409" in error_str or "Conflict" in error_str:
                print(f"garmin upload skipped (already exists): {file}")
            else:
                print("garmin upload failed: ", e)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    async def upload_activities_files(self, files):
        print("start upload activities to garmin!")

        await gather_with_concurrency(
            10,
            [self.upload_activity_from_file(file=f) for f in files],
        )


class GarminConnectHttpError(Exception):
    def __init__(self, status):
        super(GarminConnectHttpError, self).__init__(status)
        self.status = status


def get_info_text_value(summary_infos, key_name):
    if summary_infos.get(key_name) is None:
        return ""
    return str(summary_infos.get(key_name))


def create_element(parent, tag, text):
    elem = etree.SubElement(parent, tag)
    elem.text = text
    elem.tail = "\n"
    return elem


def add_summary_info(file_data, summary_infos, fields=None):
    if summary_infos is None:
        return file_data
    try:
        root = etree.fromstring(file_data)
        extensions_node = etree.Element("extensions")
        extensions_node.text = "\n"
        extensions_node.tail = "\n"
        if fields is None:
            fields = [
                "distance",
                "average_hr",
                "average_speed",
                "start_time",
                "end_time",
                "moving_time",
                "elapsed_time",
            ]
        for field in fields:
            create_element(
                extensions_node, field, get_info_text_value(summary_infos, field)
            )
        root.insert(0, extensions_node)
        return etree.tostring(root, encoding="utf-8", pretty_print=True)
    except etree.XMLSyntaxError as e:
        print(f"Failed to parse file data: {str(e)}")
    except Exception as e:
        print(f"Failed to append summary info to file data: {str(e)}")
    return file_data


async def download_garmin_data(
    client, activity_id, file_type="gpx", summary_infos=None
):
    folder = FOLDER_DICT.get(file_type, "gpx")
    try:
        file_data = await client.download_activity(activity_id, file_type=file_type)
        if summary_infos is not None and file_type == "gpx":
            file_data = add_summary_info(file_data, summary_infos.get(activity_id))
        file_path = os.path.join(folder, f"{activity_id}.{file_type}")
        need_unzip = False
        result_type = file_type.upper()
        if file_type == "fit":
            file_path = os.path.join(folder, f"{activity_id}.zip")
            need_unzip = True
        async with aiofiles.open(file_path, "wb") as fb:
            await fb.write(file_data)
        if need_unzip:
            # Check if it's actually a ZIP file
            if file_data[:2] == b"PK":  # ZIP file signature
                try:
                    zip_file = zipfile.ZipFile(file_path, "r")
                    for file_info in zip_file.infolist():
                        zip_file.extract(file_info, folder)
                        if file_info.filename.endswith(".fit"):
                            extracted_path = os.path.join(folder, file_info.filename)
                            target_path = os.path.join(folder, f"{activity_id}.fit")
                            result_type = "FIT"
                            if extracted_path != target_path:
                                try:
                                    os.rename(extracted_path, target_path)
                                except FileExistsError:
                                    os.remove(extracted_path)
                                except Exception:
                                    import glob

                                    pattern = os.path.join(
                                        folder, f"*{activity_id}*.fit"
                                    )
                                    matches = glob.glob(pattern)
                                    if matches:
                                        try:
                                            os.rename(matches[0], target_path)
                                        except FileExistsError:
                                            os.remove(matches[0])
                        elif file_info.filename.endswith(".gpx"):
                            extracted_path = os.path.join(folder, file_info.filename)
                            target_path = os.path.join(
                                FOLDER_DICT["gpx"], f"{activity_id}.gpx"
                            )
                            result_type = "GPX"
                            if extracted_path != target_path:
                                os.rename(extracted_path, target_path)
                        elif file_info.filename.endswith(
                            ".tcx"
                        ) or file_info.filename.uppercase().endswith(".TCX"):
                            extracted_path = os.path.join(folder, file_info.filename)
                            target_path = os.path.join(folder, f"{activity_id}.tcx")
                            result_type = "TCX"
                            if extracted_path != target_path:
                                os.rename(extracted_path, target_path)
                        else:
                            extracted_path = os.path.join(folder, file_info.filename)
                            if os.path.exists(extracted_path):
                                os.remove(extracted_path)
                    zip_file.close()
                    os.remove(file_path)
                except Exception as e:
                    print(f"[DEBUG] {activity_id}: ZIP error: {e}")
            else:
                # It's a direct FIT file, just rename .zip to .fit
                result_type = "FIT"
                target_path = os.path.join(folder, f"{activity_id}.fit")
                try:
                    os.rename(file_path, target_path)
                except Exception as e:
                    print(f"[DEBUG] {activity_id}: Direct FIT rename error: {e}")
        print(f"[DEBUG] {activity_id}: Downloaded ({result_type})")
    except Exception as e:
        print(f"[DEBUG] {activity_id}: Download failed: {e}")
        traceback.print_exc()


async def get_activity_id_list(client, start=0):
    activities = await client.get_activities(start, 100)
    if len(activities) > 0:
        ids = list(map(lambda a: str(a.get("activityId", "")), activities))
        print("Syncing Activity IDs")
        return ids + await get_activity_id_list(client, start + 100)
    else:
        return []


async def gather_with_concurrency(n, tasks):
    semaphore = asyncio.Semaphore(n)

    async def sem_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*(sem_task(task) for task in tasks))


def get_downloaded_ids(folder):
    return [i.split(".")[0] for i in os.listdir(folder) if not i.startswith(".")]


def get_garmin_summary_infos(activity_summary, activity_id):
    garmin_summary_infos = {}
    try:
        # garminconnect returns data at root level
        summary_dto = activity_summary.get("summaryDTO") or activity_summary
        garmin_summary_infos["distance"] = summary_dto.get("distance")
        garmin_summary_infos["average_hr"] = summary_dto.get("averageHR")
        garmin_summary_infos["average_speed"] = summary_dto.get("averageSpeed")
        start_time = dt.datetime.fromisoformat(
            summary_dto.get("startTimeGMT")[:-1] + "+00:00"
        )
        duration_second = summary_dto.get("duration")
        end_time = start_time + dt.timedelta(seconds=duration_second)
        garmin_summary_infos["start_time"] = start_time.isoformat()
        garmin_summary_infos["end_time"] = end_time.isoformat()
        garmin_summary_infos["moving_time"] = summary_dto.get("movingDuration")
        garmin_summary_infos["elapsed_time"] = summary_dto.get("elapsedDuration")
    except Exception as e:
        print(f"Failed to get activity summary {activity_id}: {str(e)}")
    return garmin_summary_infos


def restore_or_login(username, password, auth_domain):
    """
    Login to Garmin and return a GarminConnectLib client.

    For COM: Uses garminconnect library with standard OAuth flow.
    For CN: Uses garminconnect first, falls back to garth library if that fails.

    Handles 429 errors by trying to use existing token.
    """
    is_cn = auth_domain == "CN"
    domain = "garmin.cn" if is_cn else "garmin.com"
    tokenstore = os.path.expanduser(f"~/.garminconnect/{domain}")
    os.makedirs(tokenstore, exist_ok=True)

    # For CN, try garth first (more reliable for garmin.cn)
    if is_cn and GARTH_CN_AVAILABLE:
        print(f"[restore_or_login] Attempting CN login with garth library...")
        try:
            garth_client = create_garth_cn_client(username, password)
            print(f"[restore_or_login] CN login successful via garth for {auth_domain}")
            return garth_client
        except Exception as e:
            print(f"[restore_or_login] garth CN login failed: {e}")
            print("[restore_or_login] Falling back to garminconnect...")

    # Try to restore saved tokens first (for garminconnect)
    try:
        client = GarminConnectLib(username, password, is_cn=is_cn)
        client.login(tokenstore)
        print(f"Logged in using saved tokens for {auth_domain}")
        return client
    except GarminConnectTooManyRequestsError as e:
        print(f"Rate limit (429) during login for {auth_domain}: {e}")
        raise e
    except (
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
    ):
        print("No valid tokens found — logging in with credentials.")

    # Login with credentials
    print(f"Logging in to {auth_domain} with credentials...")
    max_retries = 5
    base_wait_time = 30  # seconds

    for attempt in range(max_retries):
        try:
            client = GarminConnectLib(username, password, is_cn=is_cn)
            client.login(tokenstore)
            print(f"Login successful for {auth_domain}")
            return client
        except GarminConnectTooManyRequestsError as e:
            if attempt < max_retries - 1:
                wait_time = base_wait_time * (2**attempt)
                print(
                    f"Rate limit (429) during login for {auth_domain}, "
                    f"attempt {attempt + 1}/{max_retries}. "
                    f"Waiting {wait_time}s before retry..."
                )
                time.sleep(wait_time)
            else:
                print(
                    f"Rate limit (429) persisted after {max_retries} attempts for {auth_domain}"
                )
                raise e
        except GarminConnectAuthenticationError:
            print("Wrong credentials — please check your email and password.")
            raise
        except GarminConnectConnectionError as e:
            print(f"Connection error: {e}")
            if attempt < max_retries - 1:
                wait_time = base_wait_time * (2**attempt)
                print(
                    f"Connection error for {auth_domain}, "
                    f"attempt {attempt + 1}/{max_retries}. "
                    f"Waiting {wait_time}s before retry..."
                )
                time.sleep(wait_time)
            else:
                # For CN, try garth as final fallback
                if is_cn and GARTH_CN_AVAILABLE:
                    print(
                        "[restore_or_login] garminconnect failed for CN, trying garth as final fallback..."
                    )
                    try:
                        garth_client = create_garth_cn_client(username, password)
                        print(
                            f"[restore_or_login] CN login successful via garth (final fallback) for {auth_domain}"
                        )
                        return garth_client
                    except Exception as garth_e:
                        print(
                            f"[restore_or_login] garth fallback also failed: {garth_e}"
                        )
                raise e


async def download_new_activities(
    client,
    auth_domain,
    downloaded_ids,
    is_only_running,
    folder,
    file_type,
    max_activities=10,
):
    garmin_client = Garmin(client, auth_domain, is_only_running)
    # because I don't find a para for after time, so I use garmin-id as filename
    # to find new run to generate
    activity_ids = await get_activity_id_list(garmin_client)
    to_generate_garmin_ids = list(set(activity_ids) - set(downloaded_ids))
    # Limit to most recent activities
    to_generate_garmin_ids = to_generate_garmin_ids[:max_activities]
    print(
        f"{len(to_generate_garmin_ids)} new activities to be downloaded (limited to {max_activities} most recent)"
    )

    to_generate_garmin_id2title = {}
    garmin_summary_infos_dict = {}
    for id in to_generate_garmin_ids:
        try:
            activity_summary = await garmin_client.get_activity_summary(id)
            activity_title = activity_summary.get("activityName", "")
            to_generate_garmin_id2title[id] = activity_title
            garmin_summary_infos_dict[id] = get_garmin_summary_infos(
                activity_summary, id
            )
        except Exception as e:
            print(f"Failed to get activity summary {id}: {str(e)}")
            continue

    start_time = time.time()
    await gather_with_concurrency(
        10,
        [
            download_garmin_data(
                garmin_client,
                id,
                file_type=file_type,
                summary_infos=garmin_summary_infos_dict,
            )
            for id in to_generate_garmin_ids
        ],
    )
    print(f"Download finished. Elapsed {time.time()-start_time} seconds")

    return to_generate_garmin_ids, to_generate_garmin_id2title


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "secret_string", nargs="?", help="secret_string from get_garmin_secret.py"
    )
    parser.add_argument(
        "--is-cn",
        dest="is_cn",
        action="store_true",
        help="if garmin account is cn",
    )
    parser.add_argument(
        "--only-run",
        dest="only_run",
        action="store_true",
        help="if is only for running",
    )
    parser.add_argument(
        "--tcx",
        dest="download_file_type",
        action="store_const",
        const="tcx",
        default="gpx",
        help="to download personal documents or ebook",
    )
    parser.add_argument(
        "--fit",
        dest="download_file_type",
        action="store_const",
        const="fit",
        default="gpx",
        help="to download personal documents or ebook",
    )
    parser.add_argument(
        "--max-activities",
        dest="max_activities",
        type=int,
        default=10,
        help="maximum number of activities to download (default: 10)",
    )
    options = parser.parse_args()
    secret_string = options.secret_string
    auth_domain = "CN" if options.is_cn else "COM"  # Default to COM if not specified
    file_type = options.download_file_type
    is_only_running = options.only_run
    max_activities = options.max_activities

    # Priority: environment variables > secret_string
    if auth_domain == "CN":
        email_env = os.getenv("GARMIN_CN_USERNAME")
        password_env = os.getenv("GARMIN_CN_PASSWORD")
    else:
        email_env = os.getenv("GARMIN_COM_USERNAME")
        password_env = os.getenv("GARMIN_COM_PASSWORD")

    if email_env and password_env:
        print(f"Using credentials from environment variables for {auth_domain}...")
        garmin_client = restore_or_login(email_env, password_env, auth_domain)
    elif secret_string:
        # secret_string is not used for garminconnect library
        # Need username and password, so fall back to env variables
        print(
            "secret_string not supported for garminconnect. Please use environment variables."
        )
        print(
            f"  Set GARMIN_{auth_domain}_USERNAME and GARMIN_{auth_domain}_PASSWORD environment variables"
        )
        sys.exit(1)
    else:
        print(
            f"Missing credentials: please set "
            f"GARMIN_{auth_domain}_USERNAME and GARMIN_{auth_domain}_PASSWORD environment variables"
        )
        print(
            "Usage: python garmin_sync.py <username> <password> [--is-cn] [--only-run]"
        )
        sys.exit(1)

    folder = FOLDER_DICT.get(file_type, "gpx")
    # make gpx or tcx dir
    if not os.path.exists(folder):
        os.mkdir(folder)
    downloaded_ids = get_downloaded_ids(folder)

    if file_type == "fit":
        gpx_folder = FOLDER_DICT["gpx"]
        if not os.path.exists(gpx_folder):
            os.mkdir(gpx_folder)
        downloaded_gpx_ids = get_downloaded_ids(gpx_folder)
        # merge downloaded_ids:list
        downloaded_ids = list(set(downloaded_ids + downloaded_gpx_ids))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    future = asyncio.ensure_future(
        download_new_activities(
            garmin_client,
            auth_domain,
            downloaded_ids,
            is_only_running,
            folder,
            file_type,
            max_activities=max_activities,
        )
    )
    loop.run_until_complete(future)
    new_ids, id2title = future.result()
    # fit may contain gpx(maybe upload by user)
    if file_type == "fit":
        make_activities_file_only(
            SQL_FILE,
            FOLDER_DICT["gpx"],
            JSON_FILE,
            file_suffix="gpx",
            activity_title_dict=id2title,
        )
    make_activities_file_only(
        SQL_FILE, folder, JSON_FILE, file_suffix=file_type, activity_title_dict=id2title
    )
