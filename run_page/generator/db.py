import datetime
import json
import os
import random
import string

import polyline as mod_polyline

from config import TYPE_DICT
from geopy.geocoders import Nominatim, options
from sqlalchemy import (
    Column,
    Float,
    Integer,
    Interval,
    String,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

# Reverse-geocode results keyed by "lat3,lng3" (~110m grid). Persisted in the
# repo so CI runs don't re-query Nominatim for known points — nominatim
# .openstreetmap.org blocks GitHub runner IPs, so uncached lookups there
# mostly fail silently.
GEOCODE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "geocode_cache.json")


def _load_geocode_cache():
    try:
        with open(GEOCODE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_geocode_cache(cache):
    try:
        with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=0)
    except Exception:  # noqa: BLE001
        pass


_geocode_debug = {"miss_printed": False, "none_printed": False}


# random user name 8 letters
def randomword():
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(4))


options.default_user_agent = "workouts_page"
# reverse the location (lat, lon) -> location detail
g = Nominatim(user_agent=randomword())


ACTIVITY_KEYS = [
    "run_id",
    "name",
    "distance",
    "moving_time",
    "type",
    "start_date",
    "start_date_local",
    "location_country",
    "summary_polyline",
    "average_heartrate",
    "average_speed",
    "elevation_gain",
    "source",
]


class Activity(Base):
    __tablename__ = "activities"

    run_id = Column(Integer, primary_key=True)
    name = Column(String)
    distance = Column(Float)
    moving_time = Column(Interval)
    elapsed_time = Column(Interval)
    type = Column(String)
    start_date = Column(String)
    start_date_local = Column(String)
    location_country = Column(String)
    summary_polyline = Column(String)
    average_heartrate = Column(Float)
    average_speed = Column(Float)
    elevation_gain = Column(Float)
    streak = None
    source = Column(String)

    def to_dict(self):
        out = {}
        for key in ACTIVITY_KEYS:
            attr = getattr(self, key)
            if isinstance(attr, (datetime.timedelta, datetime.datetime)):
                out[key] = str(attr)
            else:
                out[key] = attr

        if self.streak:
            out["streak"] = self.streak

        return out


def _resolve_location_country(run_activity):
    """Resolve location_country for an activity: attribute → geocode cache → Nominatim.

    Used by BOTH the create and update branches of update_or_create_activity:
    data.db is committed by the data-sync workflow, so most runs only hit the
    update branch — geocoding must live in a shared helper or new location
    data would never be backfilled.
    """
    location_country = getattr(run_activity, "location_country", "") or ""
    start_point = getattr(run_activity, "start_latlng", None)
    if not location_country and not start_point:
        # stravalib 2.x SummaryActivity carries no start_latlng (the
        # list endpoint omits it) — fall back to the first point of
        # the GPS polyline, which matches the geocode cache keys.
        act_map = getattr(run_activity, "map", None)
        sp_poly = getattr(act_map, "summary_polyline", None)
        if sp_poly:
            try:
                lat, lon = mod_polyline.decode(sp_poly)[0]
                start_point = type("StartPoint", (), {"lat": lat, "lon": lon})()
            except Exception:  # noqa: BLE001
                start_point = None
    if not location_country and start_point:
        cache_key = f"{start_point.lat:.3f},{start_point.lon:.3f}"
        geocode_cache = _load_geocode_cache()
        if cache_key in geocode_cache:
            return geocode_cache[cache_key]
        if not _geocode_debug["miss_printed"]:
            print(
                f"[geocode] miss: key={cache_key} "
                f"start={start_point!r} cache_size={len(geocode_cache)}"
            )
            _geocode_debug["miss_printed"] = True
        try:
            location_country = str(
                g.reverse(
                    f"{start_point.lat}, {start_point.lon}",
                    language="zh-CN",  # type: ignore
                    timeout=15,
                )
            )
            geocode_cache[cache_key] = location_country
            _save_geocode_cache(geocode_cache)
            return location_country
        except Exception:  # noqa: BLE001
            pass
    elif not location_country and not _geocode_debug["none_printed"]:
        print(f"[geocode] no start_point on {getattr(run_activity, 'id', '?')}")
        _geocode_debug["none_printed"] = True
    return location_country


def update_or_create_activity(session, run_activity):
    created = False
    try:
        activity = (
            session.query(Activity).filter_by(run_id=int(run_activity.id)).first()
        )
        # In stravalib 2.x, activity.type is a pydantic model object (RelaxedActivityType).
        # Use .root attribute to get the actual string value for dict key lookup.
        activity_type_value = run_activity.type.root if run_activity.type else ""
        type = activity_type_value
        source = "strava"
        if activity_type_value in TYPE_DICT:
            type = TYPE_DICT[activity_type_value]

        current_elevation_gain = 0.0  # default value

        # https://github.com/stravalib/stravalib/blob/main/src/stravalib/strava_model.py#L639C1-L643C41
        if (
            hasattr(run_activity, "total_elevation_gain")
            and run_activity.total_elevation_gain is not None
        ):
            current_elevation_gain = float(run_activity.total_elevation_gain)
        elif (
            hasattr(run_activity, "elevation_gain")
            and run_activity.elevation_gain is not None
        ):
            current_elevation_gain = float(run_activity.elevation_gain)

        # In stravalib 2.x, moving_time and elapsed_time are Duration (int subclass).
        # Convert to datetime.timedelta using .timedelta() method.
        moving_time = (
            run_activity.moving_time.timedelta()
            if hasattr(run_activity.moving_time, "timedelta")
            else run_activity.moving_time
        )
        elapsed_time = (
            run_activity.elapsed_time.timedelta()
            if hasattr(run_activity.elapsed_time, "timedelta")
            else run_activity.elapsed_time
        )

        if not activity:
            location_country = _resolve_location_country(run_activity)

            activity = Activity(
                run_id=run_activity.id,
                name=run_activity.name,
                distance=run_activity.distance,
                moving_time=moving_time,
                elapsed_time=elapsed_time,
                type=type,
                start_date=run_activity.start_date,
                start_date_local=run_activity.start_date_local,
                location_country=location_country,
                average_heartrate=run_activity.average_heartrate,
                average_speed=float(run_activity.average_speed),
                elevation_gain=current_elevation_gain,
                summary_polyline=(
                    run_activity.map and run_activity.map.summary_polyline or ""
                ),
                source=source,
            )
            session.add(activity)
            created = True
        else:
            activity.name = run_activity.name
            activity.distance = float(run_activity.distance)
            activity.moving_time = moving_time
            activity.elapsed_time = elapsed_time
            activity.type = type
            activity.average_heartrate = run_activity.average_heartrate
            activity.average_speed = float(run_activity.average_speed)
            activity.elevation_gain = current_elevation_gain
            activity.summary_polyline = (
                run_activity.map and run_activity.map.summary_polyline or ""
            )
            activity.source = source
            # Backfill location for rows created before geocoding existed —
            # data.db is committed between runs, so this branch is the hot path.
            if not activity.location_country:
                activity.location_country = _resolve_location_country(run_activity)
    except Exception as e:  # noqa: BLE001
        print(f"something wrong with {run_activity.id}")
        print(str(e))

    return created


def add_missing_columns(engine, model):
    inspector = inspect(engine)
    table_name = model.__tablename__
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    missing_columns = []

    for column in model.__table__.columns:
        if column.name not in columns:
            missing_columns.append(column)
    if missing_columns:
        with engine.connect() as conn:
            for column in missing_columns:
                column_type = str(column.type)
                conn.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column.name} {column_type}"
                    )
                )


def init_db(db_path):
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)

    # check missing columns
    add_missing_columns(engine, Activity)

    sm = sessionmaker(bind=engine)
    session = sm()
    # apply the changes
    session.commit()
    return session
