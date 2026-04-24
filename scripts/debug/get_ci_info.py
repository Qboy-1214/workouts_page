#!/usr/bin/env python3
"""
CI 调试工具 - 快速获取 CI 运行信息

用法:
    python get_ci_info.py [runs|jobs <run_id>|detail <job_id>]
"""

import json
import os
import sys
import urllib.request

REPO = "Qboy-1214/workouts_page"


def api_request(url):
    token = os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        print(f"API Error: {e}")
        return None


def show_runs(limit=5):
    data = api_request(f"https://api.github.com/repos/{REPO}/actions/runs")
    if not data:
        return
    print(f"\n{'最新 ' + str(limit) + ' 个 CI runs':=^60}")
    for r in data.get("workflow_runs", [])[:limit]:
        icon = "✓" if r["conclusion"] == "success" else "✗" if r["conclusion"] == "failure" else "○"
        print(f"{icon} [{r['id']}] {r['name'][:40]}")
        print(f"   Status: {r['status']} | {r['conclusion'] or 'running'}")
        print(f"   Commit: {r['head_commit']['message'][:50]}...")
        print()


def show_jobs(run_id):
    data = api_request(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs")
    if not data:
        return
    print(f"\n{'Run ' + str(run_id) + ' Jobs':=^60}")
    for j in data.get("jobs", []):
        icon = "✓" if j["conclusion"] == "success" else "✗" if j["conclusion"] == "failure" else "○"
        print(f"{icon} [{j['id']}] {j['name']}")
        print(f"   Status: {j['status']} | {j['conclusion'] or 'running'}")


def show_detail(job_id):
    data = api_request(f"https://api.github.com/repos/{REPO}/actions/jobs/{job_id}")
    if not data:
        return
    print(f"\n{'Job ' + str(job_id):=^60}")
    print(f"Name: {data['name']}")
    print(f"Conclusion: {data['conclusion']}\n")
    print("Steps:")
    for s in data.get("steps", []):
        icon = "✓" if s.get("conclusion") == "success" else "✗" if s.get("conclusion") == "failure" else "○" if s.get("conclusion") == "skipped" else " "
        print(f"  [{icon}] {s['name']}: {s.get('conclusion', 'running')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "runs"
    if cmd == "runs":
        show_runs()
    elif cmd == "jobs" and len(sys.argv) > 2:
        show_jobs(sys.argv[2])
    elif cmd == "detail" and len(sys.argv) > 2:
        show_detail(sys.argv[2])
    else:
        print("用法: python get_ci_info.py [runs|jobs <run_id>|detail <job_id>]")
