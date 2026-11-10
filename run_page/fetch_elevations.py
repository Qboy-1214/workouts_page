"""Fetch altitude streams for activities and cache them for GPX generation.

Strava 的逐点海拔需要按活动单独调用 streams API——本脚本只为 data.db 里
有 GPS 轨迹且尚未缓存海拔的活动拉取（约 0.4s/次），结果写入
run_page/elevation_cache.json（随 "Push new runs" 提交进仓库），
供 vite 构建生成带 <ele> 的 GPX。首次运行约 5 分钟，之后每次只补新活动。

Usage:
    python run_page/fetch_elevations.py <client_id> <client_secret> <refresh_token>
"""

import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

from stravalib import Client

CACHE_FILE = os.path.join(HERE, "elevation_cache.json")


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def extract_altitude(streams):
    """兼容 stravalib 0.10（dict）与 2.x（StreamSet 属性访问）两种返回形态"""
    if streams is None:
        return None
    alt = None
    if isinstance(streams, dict):
        s = streams.get("altitude")
        if s is not None:
            alt = getattr(s, "data", None)
    else:
        s = getattr(streams, "altitude", None)
        if s is not None:
            alt = getattr(s, "data", None)
    if not alt:
        return None
    try:
        values = [float(x) for x in alt]
    except (TypeError, ValueError):
        return None
    return values or None


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: python fetch_elevations.py <client_id> <client_secret> <refresh_token>"
        )
        sys.exit(1)

    from utils import make_strava_client

    cache = load_cache()

    import sqlite3

    conn = sqlite3.connect(os.path.join(HERE, "data.db"))
    rows = conn.execute(
        "SELECT run_id, name FROM activities "
        "WHERE summary_polyline IS NOT NULL AND summary_polyline != '' "
        "ORDER BY start_date_local DESC"
    ).fetchall()
    conn.close()

    todo = [r for r in rows if str(r[0]) not in cache]
    print(f"[elevation] GPS 活动 {len(rows)} 条, 待抓取 {len(todo)} 条")

    if not todo:
        print("[elevation] 缓存已完整，无需抓取")
        return

    client = make_strava_client(sys.argv[1], sys.argv[2], sys.argv[3])

    fetched = 0
    failed = 0
    for i, (run_id, name) in enumerate(todo):
        try:
            streams = client.get_activity_streams(
                int(run_id), types=["altitude"]
            )
            alt = extract_altitude(streams)
            if alt:
                cache[str(run_id)] = alt
                fetched += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"[elevation] {run_id} 失败: {type(e).__name__}: {e}")
        if (i + 1) % 20 == 0:
            print(f"[elevation] 进度 {i + 1}/{len(todo)}, 成功 {fetched}")
            save_cache(cache)
        time.sleep(0.4)

    save_cache(cache)
    print(
        f"[elevation] 完成: 新增 {fetched}, 失败 {failed}, "
        f"缓存共 {len(cache)} 条 -> {CACHE_FILE}"
    )


if __name__ == "__main__":
    main()
