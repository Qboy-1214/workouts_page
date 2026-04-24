"""
Sync activities from Garmin International (COM) to Garmin China (CN).

Workflow:
1. Login to Garmin COM and download new activities (not in CN)
2. Upload new activities to Garmin CN
3. Update activity name and type in CN (match by start time)

This is used after strava_to_garmin_sync.py syncs from Strava to Garmin COM.
Reference: strava_to_garmin_sync.py login and sync logic pattern.
"""

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime

from config import FIT_FOLDER, GPX_FOLDER, JSON_FILE, SQL_FILE
from garmin_sync import Garmin, restore_or_login, get_activity_id_list
from garmin_sync import (
    download_garmin_data,
    get_garmin_summary_infos,
    gather_with_concurrency,
)
from utils import make_activities_file
from activity_type_map import map_com_type_to_cn


async def get_cn_existing_timestamps(cn_client):
    """Get activity timestamps that already exist in Garmin CN to avoid duplicates.

    NOTE: COM and CN have different activity IDs for the same activity.
    We use startTimeGMT + distance to match activities across platforms.
    
    Returns a dict: normalized_time -> list of (distance, activityId)
    This PRESERVES ALL activities including those with duplicate timestamps,
    unlike a set which would lose entries.
    """
    garmin_cn = Garmin(cn_client, "CN", False)
    # Use dict to store ALL CN activities, keyed by normalized timestamp
    # Value is a list of (distance, activityId) to handle multiple activities with same timestamp
    cn_ts_dict = {}
    total_fetched = 0

    # Get all CN activities in batches
    start = 0
    limit = 100
    while True:
        activities = await garmin_cn.get_activities(start, limit)
        if not activities:
            print(f"[DEBUG] CN activities batch empty at start={start}, total fetched: {total_fetched}")
            break
        total_fetched += len(activities)
        for act in activities:
            # Use startTimeGMT + distance as unique identifier
            start_time = act.get("startTimeGMT", "")
            distance = act.get("distance", 0) or 0
            if start_time:
                # Normalize: strip sub-second precision and timezone
                import re as _re
                normalized_time = _re.sub(r'\.\d+(.*?)$', '', start_time).split('+')[0].split('Z')[0]
                if normalized_time not in cn_ts_dict:
                    cn_ts_dict[normalized_time] = []
                cn_ts_dict[normalized_time].append((distance, act.get("activityId")))
        print(f"[DEBUG] CN activities: fetched {len(activities)} (total: {total_fetched}), unique timestamps: {len(cn_ts_dict)}")
        if len(activities) < limit:
            break
        start += limit

    print(f"[DEBUG] get_cn_existing_timestamps: Found {len(cn_ts_dict)} unique timestamps ({total_fetched} total entries) in Garmin CN")

    # Debug: print first few entries
    if cn_ts_dict:
        sample = list(cn_ts_dict.items())[:3]
        print(f"[DEBUG] Sample CN timestamps: {[(t, lst[:2]) for t, lst in sample]}")
    
    return cn_ts_dict


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
    garmin_id2type = {}  # Collect activity type for post-upload CN update

    filtered_count = 0  # Track how many activities were filtered (already exist in CN)
    unmatched_debug = []  # First few unmatched COM activities for debugging

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

            # Check if this activity already exists in CN (by time + distance with tolerance)
            # Use distance tolerance of 1.0 meters to handle floating point precision differences
            # between COM and CN (GPS distance can vary slightly due to different calculation methods)
            exists_in_cn = False
            matched_cn_time = None
            if start_time:
                # Normalize COM timestamp once
                com_normalized = re.sub(r'\.\d+(.*?)$', '', start_time).split('+')[0].split('Z')[0]
                # Look up in CN dict: all CN entries with this normalized timestamp
                cn_entries = cn_existing_timestamps.get(com_normalized, [])
                for cn_dist, cn_id in cn_entries:
                    dist_diff = abs(cn_dist - distance)
                    if dist_diff < 1.0 or (cn_dist == 0 or distance == 0):
                        exists_in_cn = True
                        matched_cn_time = com_normalized
                        break
                # Debug: track first few unmatched
                if not exists_in_cn and len(unmatched_debug) < 5:
                    unmatched_debug.append((id, com_normalized, distance, cn_entries))
            if exists_in_cn:
                filtered_count += 1
                continue

            activity_title = activity_summary.get("activityName", "")
            activity_type_key = (
                activity_summary.get("activityType", {}).get("typeKey", "")
                or activity_summary.get("sportType", "")
            )
            to_generate_ids.append(id)
            to_generate_garmin_id2title[id] = activity_title
            garmin_summary_infos_dict[id] = get_garmin_summary_infos(
                activity_summary, id
            )
            garmin_id2type[id] = activity_type_key
        except Exception as e:
            print(f"Failed to get activity summary {id}: {str(e)}")
            continue
    
    print(f"[DEBUG] Filtered out {filtered_count} activities that already exist in CN (out of {len(activity_ids)} total)")
    print(f"[DEBUG] CN unique timestamps: {len(cn_existing_timestamps)}, COM total: {len(activity_ids)}")
    if unmatched_debug:
        print(f"[DEBUG] First {len(unmatched_debug)} UNMATCHED COM activities (not in CN):")
        for uid, utime, udist, uentries in unmatched_debug:
            print(f"  COM {uid}: time={utime}, dist={udist} | CN entries for this time: {uentries}")

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

    return to_generate_ids, to_generate_garmin_id2title, garmin_id2type


async def upload_activities_to_garmin_cn(garmin_cn_wrapper, files, id2title, id2type):
    """Upload activities to Garmin CN and update name/type (match by start time).

    Args:
        garmin_cn_wrapper: Garmin CN wrapper instance
        files: List of file paths to upload
        id2title: Dict mapping COM activity ID -> activity name
        id2type: Dict mapping COM activity ID -> activity type key
    """
    print(
        f"[upload_activities_to_garmin_cn] Starting upload to Garmin CN, auth domain: {garmin_cn_wrapper.auth_domain}"
    )
    await garmin_cn_wrapper.upload_activities_files(files)
    print("[upload_activities_to_garmin_cn] Upload done. Updating name/type...")

    # Update name and type for each uploaded activity
    # Extract COM activity ID from filename (e.g., "123456789.fit" -> 123456789)
    for filepath in files:
        try:
            filename = os.path.basename(filepath)
            com_id_str = os.path.splitext(filename)[0]
            try:
                com_id = int(com_id_str)
            except ValueError:
                print(f"  [update] Could not parse activity ID from {filename}")
                continue

            activity_name = id2title.get(com_id, "")
            com_type_key = id2type.get(com_id, "")
            cn_type_key = map_com_type_to_cn(com_type_key)

            # Find the newly uploaded activity in CN by start time
            start_time = None
            if com_id in id2title:
                # Get start time from garmin_summary_infos if available
                # For simplicity, search by activity name pattern (recent uploads first)
                pass

            # Get start time from the activity's summary info in the FIT/GPX file
            # Use the uploaded file to extract start time
            start_time_iso = _extract_start_time_from_file(filepath)
            if not start_time_iso:
                print(f"  [update] Could not extract start time from {filename}, skipping name/type update")
                continue

            # Search CN activities to find the matching one (search up to 1000 entries)
            found_cn_id = None
            current_cn_name = None
            current_cn_type = None

            for offset in range(0, 1000, 100):
                cn_activities = await garmin_cn_wrapper.get_activities(offset, 100)
                if not cn_activities:
                    break

                for act in cn_activities:
                    act_start = act.get("startTimeGMT", "")
                    if act_start:
                        # Normalize CN timestamp the same way as _extract_start_time_from_file
                        act_start_norm = re.sub(r'\.\d+(.*?)$', '', act_start).split('+')[0].split('Z')[0]
                        if act_start_norm == start_time_iso:
                            found_cn_id = act.get("activityId")
                            current_cn_name = act.get("activityName", "")
                            current_cn_type = (
                                act.get("activityType", {}).get("typeKey", "")
                                or act.get("activityType", {}).get("typeGui", "")
                            )
                            break

                if found_cn_id:
                    break

            if not found_cn_id:
                print(f"  [update] Could not find CN activity for {filename} (start: {start_time_iso}), skipping")
                continue

            print(
                f"  [update] CN activity {found_cn_id}: name='{current_cn_name}' -> '{activity_name}', type='{current_cn_type}' -> '{cn_type_key}'"
            )

            # Update name if different
            if activity_name and activity_name != current_cn_name:
                try:
                    await asyncio.to_thread(
                        garmin_cn_wrapper._client.update_activity_name,
                        found_cn_id,
                        activity_name,
                    )
                    print(f"    Updated name to: '{activity_name}'")
                except Exception as name_err:
                    print(f"    Could not update name: {name_err}")

            # Update type if different
            if cn_type_key and cn_type_key != current_cn_type:
                try:
                    types = await asyncio.to_thread(
                        garmin_cn_wrapper._client.get_activity_types
                    )
                    type_id = None
                    parent_type_id = None
                    for t in types:
                        if t.get("typeKey") == cn_type_key:
                            type_id = t.get("id")
                            parent_type_id = t.get("parentId")
                            break

                    if type_id:
                        await asyncio.to_thread(
                            garmin_cn_wrapper._client.update_activity_type,
                            found_cn_id,
                            cn_type_key,
                            type_id,
                            parent_type_id,
                        )
                        print(f"    Updated type to: '{cn_type_key}'")
                    else:
                        print(f"    CN type '{cn_type_key}' not found in available types")
                except Exception as type_err:
                    print(f"    Could not update type: {type_err}")

        except Exception as e:
            print(f"  [update] Error updating {filepath}: {e}")

    print("[upload_activities_to_garmin_cn] Done")


def _extract_start_time_from_file(filepath):
    """Extract start time from FIT/GPX/TCX file for CN activity matching."""
    import datetime as dt
    import struct

    ext = os.path.splitext(filepath)[-1].lower()

    try:
        if not os.path.exists(filepath):
            print(f"  [extract] File not found: {filepath}")
            return None

        if ext == ".fit":
            with open(filepath, "rb") as f:
                data = f.read()

            # FIT epoch: 631065600000 ms since Jan 1, 1989 00:00:00 UTC
            # We search for uint32 values that fall in a reasonable timestamp range
            FIT_EPOCH_MS = 631065600000
            min_ts_ms = int(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
            max_ts_ms = int(dt.datetime(2030, 12, 31, tzinfo=dt.timezone.utc).timestamp() * 1000)

            # Search for uint32 values that could be FIT ms timestamps
            data_words = struct.unpack(f"<{len(data)//4}I", data[:(len(data)//4)*4])
            candidates = []
            for val in data_words:
                if min_ts_ms <= val <= max_ts_ms:
                    unix_sec = (val - FIT_EPOCH_MS) / 1000.0
                    start_dt = dt.datetime.fromtimestamp(unix_sec, tz=dt.timezone.utc)
                    candidates.append(start_dt)
            if candidates:
                # Return the earliest timestamp (usually the activity start time)
                earliest = min(candidates)
                return earliest.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                print(f"  [extract] FIT: no valid timestamps in range (file size: {len(data)} bytes)")
                return None

        elif ext == ".tcx":
            try:
                import xml.etree.ElementTree as ET

                tree = ET.parse(filepath)
                root = tree.getroot()

                # In TCX, <Id> at Activity level contains the activity start time
                # Format: <Id>2026-04-21T14:33:44Z</Id>
                found_times = []
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "Id" and elem.text:
                        time_str = elem.text.strip()
                        try:
                            dt_obj = dt.datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                            found_times.append(dt_obj.strftime("%Y-%m-%dT%H:%M:%S"))
                        except ValueError:
                            print(f"  [extract] TCX: could not parse <Id>: '{time_str}'")
                if found_times:
                    return found_times[0]
                else:
                    # Fallback: check for <Time> trackpoints if <Id> not found
                    for elem in root.iter():
                        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if tag == "Time" and elem.text:
                            time_str = elem.text.strip()
                            try:
                                dt_obj = dt.datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                                return dt_obj.strftime("%Y-%m-%dT%H:%M:%S")
                            except ValueError:
                                pass
                    print(f"  [extract] TCX: no <Id> or <Time> element found in {filepath}")
                    return None
            except Exception as e:
                print(f"  [extract] TCX parse error for {filepath}: {e}")
                return None

        elif ext == ".gpx":
            try:
                import xml.etree.ElementTree as ET

                tree = ET.parse(filepath)
                root = tree.getroot()

                # GPX: <time> element at track/segment level
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "time" and elem.text:
                        time_str = elem.text.strip()
                        try:
                            dt_obj = dt.datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                            return dt_obj.strftime("%Y-%m-%dT%H:%M:%S")
                        except ValueError:
                            pass
                print(f"  [extract] GPX: no <time> element found in {filepath}")
                return None
            except Exception as e:
                print(f"  [extract] GPX parse error for {filepath}: {e}")
                return None

    except Exception as e:
        print(f"  [extract] Unexpected error parsing {filepath}: {e}")
        return None

    return None


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
    new_ids, id2title, id2type = future.result()

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
                upload_activities_to_garmin_cn(garmin_cn_wrapper, to_upload_files, id2title, id2type)
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
