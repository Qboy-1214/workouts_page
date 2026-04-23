"""
Garmin CN authentication and API wrapper using garth.

Strategy:
1. Use garth for CN authentication (OAuth1 flow works reliably for garmin.cn)
2. Use garth's API for all operations (download, upload, activity list)

garth has:
- Activity.list() - list activities
- Activity.get() - get activity details
- client.download() - download activity files
- client.upload() - upload activity files

This gives us reliable CN authentication with full API support.
"""

import warnings
from typing import Any, Optional

# Suppress garth deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*is deprecated.*")

import garth
from garth.data import Activity as GarthActivity


class GarminCngarthClient:
    """
    CN client using garth for authentication and API.

    garth provides reliable CN authentication via OAuth1 flow,
    and supports activity operations via its API methods.
    """

    def __init__(self, username: str, password: str, is_cn: bool = True):
        """
        Initialize the CN client.

        Args:
            username: Garmin CN email
            password: Garmin CN password
            is_cn: Always True for this class (CN only)
        """
        self.username = username
        self.password = password
        self.is_cn = is_cn
        self._is_logged_in = False

        # garth client for authentication and API
        self._garth_client: Optional[garth.Client] = None

        self.domain = "garmin.cn"

    def login(self, tokenstore: str = None) -> None:
        """
        Login to Garmin CN using garth.

        Args:
            tokenstore: Path for token persistence
        """
        import os

        # Configure garth for CN
        garth.configure(domain="garmin.cn")

        # Create new garth client
        self._garth_client = garth.Client()
        self._garth_client.configure(domain="garmin.cn")

        # Set home for token persistence
        garth_home = tokenstore or os.path.expanduser("~/.garth")
        self._garth_client._garth_home = garth_home

        # Try to load existing tokens first
        try:
            self._garth_client.load(garth_home)
            print("[GarminCngarthClient] Loaded existing garth tokens")
        except Exception:
            # No existing tokens, need to login
            print("[GarminCngarthClient] No existing tokens, logging in with garth...")
            self._garth_client.login(self.username, self.password)
            self._garth_client.dump(garth_home)
            print("[GarminCngarthClient] garth login successful, tokens saved")

        self._is_logged_in = True
        print("[GarminCngarthClient] Login complete")

    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self._is_logged_in and self._garth_client is not None

    @property
    def garth(self) -> garth.Client:
        """Get the garth client."""
        return self._garth_client

    def get_activities(self, start: int = 0, limit: int = 100):
        """
        Get activities from Garmin CN.

        Returns list of activity dictionaries compatible with garminconnect format.
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        try:
            # Use garth's Activity.list()
            activities = GarthActivity.list(
                limit=limit, start=start, client=self._garth_client
            )

            # Convert to dict format compatible with garminconnect
            result = []
            for act in activities:
                act_dict = {
                    "activityId": act.activity_id,
                    "activityName": act.activity_name,
                    "activityType": {
                        "typeKey": (
                            act.activity_type.type_key
                            if act.activity_type
                            else "unknown"
                        ),
                        "typeGui": (
                            act.activity_type.type_key
                            if act.activity_type
                            else "unknown"
                        ),
                    },
                    "startTimeGMT": (
                        act.start_time_gmt.isoformat() if act.start_time_gmt else None
                    ),
                    "startTimeLocal": (
                        act.start_time_local.isoformat()
                        if act.start_time_local
                        else None
                    ),
                }
                # Add summary fields if available
                if act.summary:
                    act_dict.update(
                        {
                            "distance": act.summary.distance,
                            "duration": act.summary.duration,
                            "averageHR": act.summary.average_hr,
                            "averageSpeed": act.summary.average_speed,
                        }
                    )
                result.append(act_dict)

            return result
        except Exception as e:
            print(f"[GarminCngarthClient] get_activities failed: {e}")
            import traceback

            traceback.print_exc()
            return []

    def get_activity(self, activity_id: int or str):
        """
        Get activity details by ID.

        Returns dict compatible with garminconnect format.
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        try:
            # Use garth's Activity.get()
            act = GarthActivity.get(int(activity_id), client=self._garth_client)

            # Convert to dict format
            act_dict = {
                "activityId": act.activity_id,
                "activityName": act.activity_name,
                "activityType": {
                    "typeKey": (
                        act.activity_type.type_key if act.activity_type else "unknown"
                    ),
                },
                "startTimeGMT": (
                    act.start_time_gmt.isoformat() if act.start_time_gmt else None
                ),
            }

            # Add full summary
            if act.summary:
                s = act.summary
                act_dict["summaryDTO"] = {
                    "distance": s.distance,
                    "duration": s.duration,
                    "movingDuration": s.moving_duration,
                    "elapsedDuration": s.elapsed_duration,
                    "averageHR": s.average_hr,
                    "maxHR": s.max_hr,
                    "averageSpeed": s.average_speed,
                    "maxSpeed": s.max_speed,
                    "elevationGain": s.elevation_gain,
                    "elevationLoss": s.elevation_loss,
                    "startTimeGMT": (
                        s.start_time_gmt.isoformat() if s.start_time_gmt else None
                    ),
                }

            return act_dict
        except Exception as e:
            print(f"[GarminCngarthClient] get_activity failed: {e}")
            return {}

    def get_activity_summary(self, activity_id):
        """Alias for get_activity to maintain compatibility."""
        return self.get_activity(activity_id)

    def download_activity(self, activity_id, file_type="fit"):
        """
        Download activity file.

        Args:
            activity_id: The activity ID
            file_type: File format (fit, gpx, tcx)

        Returns:
            File content as bytes
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        try:
            # Use garth's download method
            # garth downloads FIT format by default via /activity-service/activity/{id}/download
            path = f"/activity-service/activity/{int(activity_id)}/download"

            if file_type == "gpx":
                path = f"/activity-service/activity/{int(activity_id)}/download"
            elif file_type == "tcx":
                path = f"/activity-service/activity/{int(activity_id)}/download"
            # Default to FIT

            data = self._garth_client.download(path)
            print(f"[GarminCngarthClient] Downloaded {activity_id} ({len(data)} bytes)")
            return data
        except Exception as e:
            print(f"[GarminCngarthClient] download_activity failed: {e}")
            import traceback

            traceback.print_exc()
            return None

    def upload_activity(
        self, filepath: str, activity_type: str = None, title: str = None
    ):
        """
        Upload activity file to Garmin CN.

        Args:
            filepath: Path to the activity file
            activity_type: Activity type (optional)
            title: Activity title (optional)

        Returns:
            Upload result dict, or raises GarthHTTPError for 409 Conflict
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        from garth.exc import GarthHTTPError

        try:
            with open(filepath, "rb") as f:
                result = self._garth_client.upload(f)
            print(f"[GarminCngarthClient] Upload result: {result}")
            return result
        except GarthHTTPError as e:
            # Re-raise GarthHTTPError so it can be caught by caller
            raise
        except Exception as e:
            print(f"[GarminCngarthClient] upload_activity failed: {e}")
            import traceback

            traceback.print_exc()
            raise

    def update_activity_name(self, activity_id, name: str):
        """
        Update activity name.

        Args:
            activity_id: The activity ID
            name: New activity name
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        try:
            GarthActivity.update(int(activity_id), name=name, client=self._garth_client)
            print(
                f"[GarminCngarthClient] Updated activity {activity_id} name to: {name}"
            )
        except Exception as e:
            print(f"[GarminCngarthClient] update_activity_name failed: {e}")
            raise

    def get_activity_types(self):
        """
        Get all available activity types for CN.

        CN API doesn't support this endpoint, so we return known CN types.

        Returns:
            List of activity type dicts with 'typeKey', 'id', 'parentId' keys.
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        # CN doesn't support activity types API
        # Return a predefined list of common CN activity types
        # These IDs are standard Garmin IDs that should work across regions
        return [
            {"typeKey": "running", "id": 1, "parentId": 1},
            {"typeKey": "trail_running", "id": 2, "parentId": 1},
            {"typeKey": "track_running", "id": 3, "parentId": 1},
            {"typeKey": "treadmill_running", "id": 4, "parentId": 1},
            {"typeKey": "walking", "id": 9, "parentId": 9},
            {"typeKey": "hiking", "id": 8, "parentId": 9},
            {"typeKey": "cycling", "id": 2, "parentId": 2},  # 骑行
            {"typeKey": "road_biking", "id": 2, "parentId": 2},
            {"typeKey": "mountain_biking", "id": 3, "parentId": 2},
            {"typeKey": "cyclocross", "id": 4, "parentId": 2},
            {"typeKey": "gravel_cycling", "id": 45, "parentId": 2},
            {"typeKey": "indoor_cycling", "id": 5, "parentId": 2},
            {"typeKey": "swimming", "id": 6, "parentId": 6},
            {"typeKey": "rowing", "id": 10, "parentId": 10},
            {"typeKey": "strength_training", "id": 17, "parentId": 17},
            {"typeKey": "yoga", "id": 21, "parentId": 17},
            {"typeKey": "soccer", "id": 40, "parentId": 28},  # 足球
            {"typeKey": "squash", "id": 58, "parentId": 17},  # 壁球
            {"typeKey": "tennis", "id": 73, "parentId": 28},  # 网球
            {"typeKey": "fitness_equipment", "id": 26, "parentId": 17},  # 健身器械
            {"typeKey": "badminton", "id": 224, "parentId": 219},  # 羽毛球
            {"typeKey": "table_tennis", "id": 220, "parentId": 219},  # 乒乓球
            {"typeKey": "dance", "id": 316, "parentId": 17},  # 舞蹈
            {"typeKey": "other", "id": 247, "parentId": 247},
        ]

    def update_activity_type(self, activity_id, type_key, type_id, parent_type_id=None):
        """
        Update activity type.

        Args:
            activity_id: The activity ID
            type_key: The activity type key (e.g., 'soccer', 'badminton')
            type_id: The new activity type ID (COM's typeId)
            parent_type_id: The parent type ID (optional)
        """
        if not self._is_logged_in or not self._garth_client:
            raise Exception("Not logged in")

        try:
            path = f"/activity-service/activity/{int(activity_id)}"
            payload = {
                "activityId": int(activity_id),
                "activityTypeDTO": {
                    "typeId": type_id,
                    "typeKey": type_key,
                    "parentTypeId": parent_type_id,
                },
            }
            self._garth_client.connectapi(path, method="PUT", json=payload)
            print(
                f"[GarminCngarthClient] Updated activity {activity_id} type to {type_key}"
            )
        except Exception as e:
            print(f"[GarminCngarthClient] update_activity_type failed: {e}")
            raise


def create_garth_cn_client(username: str, password: str) -> GarminCngarthClient:
    """
    Factory function to create a CN client with garth.

    Args:
        username: Garmin CN email
        password: Garmin CN password

    Returns:
        GarminCngarthClient instance (logged in)
    """
    client = GarminCngarthClient(username, password, is_cn=True)
    client.login()
    return client
