"""
Python 3 API wrapper for Garmin Connect to get your statistics.
International (COM): uses garminconnect library
China (CN): uses garth library (暂时保留)
"""

import argparse
import asyncio
import datetime as dt
import logging
import os
import sys
import time
import traceback
import zipfile

from lxml import etree

import aiofiles
import httpx
from garminconnect import (
    Garmin as GarminConnectLib,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from config import FOLDER_DICT, JSON_FILE, SQL_FILE
from garmin_device_adaptor import process_garmin_data
from utils import make_activities_file_only

# garth is only used for China region
import garth

# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

TIME_OUT = httpx.Timeout(240.0, connect=360.0)
GARMIN_COM_URL_DICT = {
    "SSO_URL_ORIGIN": "https://sso.garmin.com",
    "SSO_URL": "https://sso.garmin.com/sso",
    "MODERN_URL": "https://connectapi.garmin.com",
    "SIGNIN_URL": "https://sso.garmin.com/sso/signin",
    "UPLOAD_URL": "https://connectapi.garmin.com/upload-service/upload/",
    "ACTIVITY_URL": "https://connectapi.garmin.com/activity-service/activity/{activity_id}",
}

GARMIN_CN_URL_DICT = {
    "SSO_URL_ORIGIN": "https://sso.garmin.com",
    "SSO_URL": "https://sso.garmin.cn/sso",
    "MODERN_URL": "https://connectapi.garmin.cn",
    "SIGNIN_URL": "https://sso.garmin.cn/sso/signin",
    "UPLOAD_URL": "https://connectapi.garmin.cn/upload-service/upload/",
    "ACTIVITY_URL": "https://connectapi.garmin.cn/activity-service/activity/{activity_id}",
}


# Strava to Garmin sport type mapping (Garmin compatible format)
# Garmin typeKey reference: https://github.com/pe-st/garmin-connect-export/blob/master/json/activityTypes.json
STRAVA_TO_GARMIN_SPORT = {
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
    "Cross Country Ski": "cross_country_skiing_ws",
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
        import urllib.parse

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
            
            print(f"[fix_tcx_sport_type] TCX file Sport: '{sport_attr}', Strava type: '{strava_sport_type}'")
            
            if sport_to_convert and sport_to_convert in STRAVA_TO_GARMIN_SPORT:
                new_sport = STRAVA_TO_GARMIN_SPORT[sport_to_convert]
                print(f"Fixing TCX sport: {sport_to_convert} -> {new_sport}")
                activity.set("Sport", new_sport)
                modified = True
            elif sport_attr:
                # Try partial match if exact match fails
                for key, value in STRAVA_TO_GARMIN_SPORT.items():
                    if key.lower() in sport_attr.lower() or sport_attr.lower() in key.lower():
                        print(f"Partial match - Fixing TCX sport: {sport_attr} -> {value}")
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
    Garmin client for both COM (garminconnect) and CN (garth) regions.
    COM uses garminconnect library, CN uses garth library.
    """

    def __init__(self, client, auth_domain, is_only_running=False):
        """
        Init module
        """
        self.auth_domain = auth_domain.upper() if auth_domain else "COM"
        self.is_only_running = is_only_running
        self._client = client  # may be None if login failed

        if client is None:
            # Login failed or not attempted
            if self.auth_domain == "CN":
                self._use_garminconnect = False
                self.URL_DICT = GARMIN_CN_URL_DICT
                self.modern_url = self.URL_DICT.get("MODERN_URL")
                self.upload_url = self.URL_DICT.get("UPLOAD_URL")
                self.activity_url = self.URL_DICT.get("ACTIVITY_URL")
            else:
                # COM uses garminconnect
                self._use_garminconnect = True
                self.modern_url = GARMIN_COM_URL_DICT.get("MODERN_URL")
                self.upload_url = GARMIN_COM_URL_DICT.get("UPLOAD_URL")
            return

        if self.auth_domain == "CN":
            # CN uses garth
            self._use_garminconnect = False
            self.req = httpx.AsyncClient(timeout=TIME_OUT)
            self.URL_DICT = GARMIN_CN_URL_DICT
            garth.configure(domain="garmin.cn", ssl_verify=False)
            garth.client.loads(client)  # client is secret_string for garth
            if garth.client.oauth2_token.expired:
                garth.client.refresh_oauth2()
            self.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36",
                "origin": self.URL_DICT.get("SSO_URL_ORIGIN"),
                "nk": "NT",
                "Authorization": str(garth.client.oauth2_token),
            }
            self.upload_url = self.URL_DICT.get("UPLOAD_URL")
            self.activity_url = self.URL_DICT.get("ACTIVITY_URL")
            self.modern_url = self.URL_DICT.get("MODERN_URL")
        else:
            # COM uses garminconnect
            self._use_garminconnect = True
            self.modern_url = GARMIN_COM_URL_DICT.get("MODERN_URL")
            self.upload_url = GARMIN_COM_URL_DICT.get("UPLOAD_URL")

    async def fetch_data(self, url, retrying=False):
        """
        Fetch and return data (only for CN region using garth)
        """
        try:
            response = await self.req.get(url, headers=self.headers)
            if response.status_code == 429:
                raise GarminConnectTooManyRequestsError("Too many requests")
            logger.debug(f"fetch_data got response code {response.status_code}")
            response.raise_for_status()
            return response.json()
        except Exception as err:
            print(err)
            if retrying:
                logger.debug(
                    "Exception occurred during data retrieval, relogin without effect: %s"
                    % err
                )
                raise GarminConnectConnectionError("Error connecting") from err
            else:
                logger.debug(
                    "Exception occurred during data retrieval - perhaps session expired - trying relogin: %s"
                    % err
                )
                await self.fetch_data(url, retrying=True)

    async def get_activities(self, start, limit):
        """
        Fetch available activities
        """
        if self._client is None:
            print("[Garmin.get_activities] No garmin client, returning empty list")
            return []
        if self._use_garminconnect:
            # COM: use garminconnect
            activities = self._client.get_activities(start, limit)
            # Filter by activity type if needed
            if self.is_only_running:
                activities = [
                    a
                    for a in activities
                    if a.get("activityType", {}).get("typeKey") == "running"
                ]
            return activities
        else:
            # CN: use garth via httpx
            url = f"{self.modern_url}/activitylist-service/activities/search/activities?start={start}&limit={limit}"
            if self.is_only_running:
                url = url + "&activityType=running"
            return await self.fetch_data(url)

    async def get_activity_summary(self, activity_id):
        """
        Fetch activity summary
        """
        if self._client is None:
            print("[Garmin.get_activity_summary] No garmin client, returning empty")
            return {}
        if self._use_garminconnect:
            # COM: use garminconnect
            # activity_id must be int for garminconnect
            return self._client.get_activity(int(activity_id))
        else:
            # CN: use garth via httpx
            url = f"{self.modern_url}/activity-service/activity/{activity_id}"
            return await self.fetch_data(url)

    async def download_activity(self, activity_id, file_type="gpx"):
        """
        Download activity file (GPX, TCX, FIT)
        """
        if self._use_garminconnect:
            # COM: use garminconnect
            # activity_id must be int for garminconnect
            # Convert file_type string to garminconnect enum
            fmt_map = {
                "gpx": GarminConnectLib.ActivityDownloadFormat.GPX,
                "tcx": GarminConnectLib.ActivityDownloadFormat.TCX,
                "fit": GarminConnectLib.ActivityDownloadFormat.ORIGINAL,
            }
            dl_fmt = fmt_map.get(file_type, GarminConnectLib.ActivityDownloadFormat.GPX)
            return self._client.download_activity(int(activity_id), dl_fmt=dl_fmt)
        else:
            # CN: use garth via httpx
            url = f"{self.modern_url}/download-service/export/{file_type}/activity/{activity_id}"
            if file_type == "fit":
                url = f"{self.modern_url}/download-service/files/activity/{activity_id}"
            logger.info(f"Download activity from {url}")
            response = await self.req.get(url, headers=self.headers)
            response.raise_for_status()
            return response.read()

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
            # Unpack data and sport type (wrapped as tuple in strava_to_garmin_sync.py)
            if isinstance(item, tuple) and len(item) == 2:
                data, strava_sport_type = item
            else:
                data = item
                strava_sport_type = None
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

            if self._use_garminconnect:
                # COM: use garminconnect (requires file path, not raw data)
                import tempfile

                # process_garmin_data may return bytes or BytesIO
                data_bytes = (
                    file_body.read()
                    if hasattr(file_body, "read")
                    else file_body
                )
                with tempfile.NamedTemporaryFile(
                    suffix=f".{ext}", delete=False
                ) as tmp:
                    tmp.write(data_bytes)
                    tmp_path = tmp.name
                try:
                    result = self._client.upload_activity(tmp_path)
                    print("garmin upload success: ", result)
                    
                    # Set correct activity type after upload
                    print(f"[DEBUG] Checking sport type: strava_sport_type={strava_sport_type}")
                    if strava_sport_type and strava_sport_type in STRAVA_TO_GARMIN_SPORT:
                        print(f"[DEBUG] Sport type {strava_sport_type} is in mapping, garmin_sport={STRAVA_TO_GARMIN_SPORT[strava_sport_type]}")
                        garmin_sport = STRAVA_TO_GARMIN_SPORT[strava_sport_type]
                        # Get activity ID from response
                        try:
                            resp_data = result.json() if hasattr(result, 'json') else result
                            detailed = resp_data.get('detailedImportResult', {}) if isinstance(resp_data, dict) else {}
                            successes = detailed.get('successes', []) if isinstance(detailed, dict) else []
                            upload_id = detailed.get('uploadId')
                            upload_time = detailed.get('creationDate')
                            upload_file_size = detailed.get('fileSize')
                            print(f"[DEBUG] upload uploadId: {upload_id}, creationDate: {upload_time}, fileSize: {upload_file_size}")
                            
                            activity_id = None
                            if successes:
                                activity_id = successes[0].get('internalId') or successes[0].get('activityId')
                            else:
                                # Try to find activity by creation time from recent activities
                                print("[DEBUG] Fetching activities by date to match...")
                                if upload_time:
                                    # Get recent activities to find the one we just uploaded
                                    # Use date-based search with retry since new uploads need time to process
                                    print("[DEBUG] Fetching activities by date to match...")
                                    try:
                                        # Extract date from creationDate (format: "2026-04-22 14:58:27.716 GMT")
                                        upload_date = upload_time.split(' ')[0] if upload_time else None
                                        print(f"[DEBUG] Searching for activities on date: {upload_date}")
                                        
                                        activity_id = None
                                        search_dates = [upload_date]
                                        # Also check previous day in case of timezone difference
                                        if upload_date:
                                            from datetime import datetime, timedelta
                                            prev_date = (datetime.strptime(upload_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                                            search_dates.append(prev_date)
                                        
                                        # Retry with delays to wait for processing
                                        for retry in range(3):
                                            if retry > 0:
                                                wait_time = 5 * retry
                                                print(f"[DEBUG] Retry {retry}, waiting {wait_time}s for activity to process...")
                                                time.sleep(wait_time)
                                            
                                            for search_date in search_dates:
                                                try:
                                                    recent = self._client.get_activities_by_date(search_date, sortorder="desc")
                                                    print(f"[DEBUG] Got {len(recent)} activities for {search_date}")
                                                    for act in recent:
                                                        act_start_time = act.get('startTimeGMT') or act.get('startTime')
                                                        act_file_size = act.get('fileSize')
                                                        print(f"[DEBUG] Checking activity: {act.get('activityId')}, startTime: {act_start_time}, fileSize: {act_file_size}")
                                                        # Match by creation time (if available) or file size
                                                        if act_start_time == upload_time:
                                                            activity_id = act.get('activityId')
                                                            print(f"[DEBUG] Found matching activity by time: {activity_id}")
                                                            break
                                                        elif upload_file_size and act_file_size and act_file_size == upload_file_size:
                                                            # Fallback: match by file size
                                                            activity_id = act.get('activityId')
                                                            print(f"[DEBUG] Found matching activity by file size: {activity_id}")
                                                            break
                                                    if activity_id:
                                                        break
                                                except Exception as date_e:
                                                    print(f"[DEBUG] Error getting activities for {search_date}: {date_e}")
                                            if activity_id:
                                                break
                                    except Exception as get_e:
                                        print(f"[DEBUG] Failed to get activities: {get_e}")
                                        import traceback
                                        traceback.print_exc()
                            
                            if activity_id:
                                print(f"Setting activity type to {garmin_sport} for activity {activity_id}")
                                # Get activity types to find type_id and parent_type_id
                                activity_types = self._client.get_activity_types()
                                sport_type_info = next((t for t in activity_types if t.get('typeKey') == garmin_sport), None)
                                if sport_type_info:
                                    self._client.set_activity_type(
                                        activity_id=str(activity_id),
                                        type_id=sport_type_info.get('typeId'),
                                        type_key=garmin_sport,
                                        parent_type_id=sport_type_info.get('parentTypeId')
                                    )
                                    print(f"Activity type set to {garmin_sport}")
                                else:
                                    print(f"Could not find type info for {garmin_sport}")
                        except Exception as type_e:
                            print(f"Failed to set activity type: {type_e}")
                            import traceback
                            traceback.print_exc()
                except Exception as e:
                    print("garmin upload failed: ", e)
                finally:
                    os.remove(tmp_path)
            else:
                # CN: use httpx
                files = {"file": (data.filename, file_body)}
                try:
                    res = await self.req.post(
                        self.upload_url, files=files, headers=self.headers
                    )
                    os.remove(data.filename)
                except Exception as e:
                    print("garmin upload failed: ", e)
                    continue
                try:
                    resp = res.json()["detailedImportResult"]
                    print("garmin upload success: ", resp)
                except Exception as e:
                    print("garmin upload failed: ", e)
        if not self._use_garminconnect:
            await self.req.aclose()

        async def upload_activity_from_file(self, file):
            print("Uploading " + str(file))
            with open(file, "rb") as f:
                file_body = f.read()

            if self._use_garminconnect:
                # COM: use garminconnect (requires file path, not raw data)
                import tempfile

                ext = os.path.splitext(file)[-1].lower().lstrip(".")
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                    tmp.write(file_body)
                    tmp_path = tmp.name
                try:
                    result = self._client.upload_activity(tmp_path)
                    print("garmin upload success: ", result)
                except Exception as e:
                    print("garmin upload failed: ", e)
                finally:
                    os.remove(tmp_path)
            else:
                # CN: use httpx
                files = {"file": (file, file_body)}
                try:
                    res = await self.req.post(
                        self.upload_url, files=files, headers=self.headers
                    )
                except Exception as e:
                    print(str(e))
                    return
                try:
                    resp = res.json()["detailedImportResult"]
                    print("garmin upload success: ", resp)
                except Exception as e:
                    print("garmin upload failed: ", e)

        async def upload_activities_files(self, files):
            print("start upload activities to garmin!")

            await gather_with_concurrency(
                10,
                [self.upload_activity_from_file(file=f) for f in files],
            )

            if not self._use_garminconnect:
                await self.req.aclose()


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
        if file_type == "fit":
            file_path = os.path.join(folder, f"{activity_id}.zip")
            need_unzip = True
        async with aiofiles.open(file_path, "wb") as fb:
            await fb.write(file_data)
        if need_unzip:
            zip_file = zipfile.ZipFile(file_path, "r")
            for file_info in zip_file.infolist():
                zip_file.extract(file_info, folder)
                if file_info.filename.endswith(".fit"):
                    os.rename(
                        os.path.join(folder, f"{activity_id}_ACTIVITY.fit"),
                        os.path.join(folder, f"{activity_id}.fit"),
                    )
                elif file_info.filename.endswith(".gpx"):
                    os.rename(
                        os.path.join(folder, f"{activity_id}_ACTIVITY.gpx"),
                        os.path.join(FOLDER_DICT["gpx"], f"{activity_id}.gpx"),
                    )
                else:
                    os.remove(os.path.join(folder, file_info.filename))
            os.remove(file_path)
    except Exception as e:
        print(f"Failed to download activity {activity_id}: {str(e)}")
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
        # garminconnect returns data at root level, garth wraps in summaryDTO
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
    Login to Garmin and return the appropriate client.

    For COM: returns a GarminConnectClient (garminconnect library)
    For CN: returns a secret_string (garth library, unchanged)

    Handles 429 errors by trying to use existing token.
    """
    import pickle
    import time

    domain = "garmin.cn" if auth_domain == "CN" else "garmin.com"
    token_file = f".token_{domain.replace('.', '_')}.pkl"

    # Use garminconnect for COM, garth for CN
    if auth_domain == "CN":
        # CN: use garth (unchanged)
        garth.configure(domain=domain, ssl_verify=False)

        # Try to load existing token first
        if os.path.exists(token_file):
            try:
                with open(token_file, "rb") as f:
                    token_data = f.read()
                if token_data:
                    garth.client.loads(token_data)
                    if not garth.client.oauth2_token.expired:
                        print(f"Loaded existing token for {auth_domain}")
                        return token_data
            except Exception:
                pass

        # Login with credentials
        print(f"Logging in to {auth_domain} with credentials...")
        max_retries = 5
        base_wait_time = 30  # seconds

        for attempt in range(max_retries):
            try:
                garth.client.login(username, password)
                secret_string = garth.client.dumps()
                with open(token_file, "wb") as f:
                    pickle.dump(secret_string, f)
                print(f"Saved token to {token_file}")
                return secret_string
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too many requests" in error_msg:
                    if os.path.exists(token_file):
                        try:
                            with open(token_file, "rb") as f:
                                token_data = f.read()
                            if token_data:
                                garth.client.loads(token_data)
                                if not garth.client.oauth2_token.expired:
                                    print(
                                        f"Using saved token after 429 for {auth_domain}"
                                    )
                                    return token_data
                        except Exception:
                            pass

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
                else:
                    raise e
    else:
        # COM: use garminconnect
        tokenstore = os.path.expanduser(f"~/.garminconnect/{domain}")
        os.makedirs(tokenstore, exist_ok=True)

        # Try to restore saved tokens
        try:
            client = GarminConnectLib(username, password)
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
                client = GarminConnectLib(username, password)
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
                    raise e


async def download_new_activities(
    secret_string, auth_domain, downloaded_ids, is_only_running, folder, file_type
):
    client = Garmin(secret_string, auth_domain, is_only_running)
    # because I don't find a para for after time, so I use garmin-id as filename
    # to find new run to generate
    activity_ids = await get_activity_id_list(client)
    to_generate_garmin_ids = list(set(activity_ids) - set(downloaded_ids))
    print(f"{len(to_generate_garmin_ids)} new activities to be downloaded")

    to_generate_garmin_id2title = {}
    garmin_summary_infos_dict = {}
    for id in to_generate_garmin_ids:
        try:
            activity_summary = await client.get_activity_summary(id)
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
                client, id, file_type=file_type, summary_infos=garmin_summary_infos_dict
            )
            for id in to_generate_garmin_ids
        ],
    )
    print(f"Download finished. Elapsed {time.time()-start_time} seconds")

    # Only close req for CN region (uses httpx), COM uses garminconnect
    if hasattr(client, "req"):
        await client.req.aclose()
    return to_generate_garmin_ids, to_generate_garmin_id2title


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "secret_string", nargs="?", help="secret_string fro get_garmin_secret.py"
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
    options = parser.parse_args()
    secret_string = options.secret_string
    auth_domain = "CN" if options.is_cn else "COM"  # Default to COM if not specified
    file_type = options.download_file_type
    is_only_running = options.only_run

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
        garmin_client = restore_or_login(secret_string, None, auth_domain)
    else:
        print(
            f"Missing argument: please provide secret_string OR set "
            f"GARMIN_{auth_domain}_USERNAME/GARMIN_{auth_domain}_PASSWORD environment variables"
        )
        print("Usage: python garmin_sync.py <secret_string> [--is-cn] [--only-run]")
        print(
            f"  Or set environment variables: GARMIN_{auth_domain}_USERNAME and "
            f"GARMIN_{auth_domain}_PASSWORD"
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
