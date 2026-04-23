"""
Garmin COM to CN Activity Type Mapping

Garmin uses different activity type keys in different regions.
This module provides mapping between COM and CN activity types.
"""

# Map COM activity types to CN-compatible types
COM_TO_CN_TYPE_MAP = {
    # Cycling types
    "cycling": "cycling",
    "street_running": "running",
    "trail_running": "trail_running",
    "track_running": "track_running",
    "treadmill_running": "treadmill_running",
    "virtual_run": "virtual_run",
    # VR Sports - CN limited support, try direct mapping
    "soccer": "soccer",
    "squash": "squash",  # 壁球 - 直接映射
    "tennis": "tennis",
    "badminton": "badminton",  # 羽毛球 - 直接映射
    "table_tennis": "table_tennis",  # 乒乓球 - 直接映射
    "dance": "dance",  # 舞蹈 - 直接映射
    # Other common types
    "swimming": "swimming",
    "walking": "walking",
    "hiking": "hiking",
    "rowing": "rowing",
    "strength_training": "strength_training",
    "yoga": "yoga",
    "other": "other",
    "running": "running",
    "road_biking": "road_biking",
    "mountain_biking": "mountain_biking",
    "gravel_cycling": "gravel_cycling",
    "e_biking": "e_biking",
    "skiing": "skiing",
    "snowboarding": "snowboarding",
    "cross_country_skiing": "cross_country_skiing",
}


def map_com_type_to_cn(com_type_key: str) -> str:
    """
    Map a COM activity type to CN-compatible type.

    Args:
        com_type_key: Activity type key from Garmin COM

    Returns:
        CN-compatible activity type key, or 'other' if not found
    """
    return COM_TO_CN_TYPE_MAP.get(com_type_key, "other")


def get_all_cn_types() -> list:
    """
    Get list of all available CN activity types.

    Returns:
        List of known CN-compatible activity types
    """
    return list(set(COM_TO_CN_TYPE_MAP.values()))
