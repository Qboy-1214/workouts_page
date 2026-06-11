#!/usr/bin/env python3
"""
CI 调试工具集 - 用于获取 GitHub Actions CI 运行信息

使用方法:
    python scripts/debug/get_ci_runs.py              # 获取最新的 CI runs
    python scripts/debug/get_ci_jobs.py <run_id>    # 获取指定 run 的 jobs
    python scripts/debug/get_job_detail.py <job_id> # 获取 job 详情
    python scripts/debug/get_job_logs.py <job_id>    # 获取 job 日志

注意: 需要设置 GITHUB_TOKEN 环境变量或修改脚本中的 token
"""

import json
import sys
import urllib.request

# 配置
REPO = "Qboy-1214/workouts_page"
TOKEN = ""  # 在此填入你的 GitHub Token，或设置环境变量 GITHUB_TOKEN

# Garmin 帐号配置
# Garmin 国际区 (garmin.com)
GARMIN_COM_USERNAME = ""  # 国际区用户名/邮箱
GARMIN_COM_PASSWORD = ""  # 国际区密码

# Garmin 中国区 (garmin.com.cn)
GARMIN_CN_USERNAME = ""  # 中国区用户名/邮箱
GARMIN_CN_PASSWORD = ""  # 中国区密码


def get_token():
    """获取 GitHub Token"""
    import os

    return TOKEN or os.environ.get("GITHUB_TOKEN", "")


def api_request(url):
    """发送 GitHub API 请求"""
    token = get_token()
    if not token:
        print("Error: 请设置 GITHUB_TOKEN 环境变量或修改脚本中的 TOKEN")
        sys.exit(1)

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")

    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"Error: {e.code} - {e.reason}")
        print(f"URL: {url}")
        return None


def get_latest_runs(limit=5):
    """获取最新的 workflow runs"""
    url = f"https://api.github.com/repos/{REPO}/actions/runs"
    data = api_request(url)

    if not data:
        return

    print(f"最新 {limit} 个 CI runs:")
    print("=" * 80)
    for run in data.get("workflow_runs", [])[:limit]:
        status = run.get("status", "")
        conclusion = run.get("conclusion", "")
        commit = run.get("head_commit", {}).get("message", "")[:60]
        print(f"\n[{'✓' if conclusion == 'success' else '✗' if conclusion == 'failure' else '○'}] {run['name']}")
        print(f"  ID: {run['id']}")
        print(f"  Status: {status} | Conclusion: {conclusion}")
        print(f"  Commit: {commit}...")
        print(f"  URL: {run['html_url']}")


def get_run_jobs(run_id):
    """获取指定 run 的所有 jobs"""
    url = f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs"
    data = api_request(url)

    if not data:
        return

    print(f"Run ID: {run_id}")
    print(f"Jobs: {len(data.get('jobs', []))}")
    print("=" * 80)
    for job in data.get("jobs", []):
        status = job.get("status", "")
        conclusion = job.get("conclusion", "")
        icon = "✓" if conclusion == "success" else "✗" if conclusion == "failure" else "○" if conclusion == "cancelled" else "?"
        print(f"\n[{icon}] {job['name']}")
        print(f"  ID: {job['id']}")
        print(f"  Status: {status} | Conclusion: {conclusion}")
        print(f"  URL: {job['html_url']}")


def get_job_detail(job_id):
    """获取 job 详情和步骤"""
    url = f"https://api.github.com/repos/{REPO}/actions/jobs/{job_id}"
    data = api_request(url)

    if not data:
        return

    print(f"Job: {data.get('name')}")
    print(f"Conclusion: {data.get('conclusion')}")
    print(f"Started: {data.get('started_at')}")
    print(f"Completed: {data.get('completed_at')}")
    print("\nSteps:")
    print("-" * 60)
    for step in data.get("steps", []):
        icon = (
            "✓" if step.get("conclusion") == "success" else "✗" if step.get("conclusion") == "failure" else "○" if step.get("conclusion") == "skipped" else " "
        )
        print(f"  [{icon}] {step.get('name')}: {step.get('conclusion', 'running')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        get_latest_runs()
    elif sys.argv[1] == "runs":
        get_latest_runs(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif sys.argv[1] == "jobs" and len(sys.argv) > 2:
        get_run_jobs(sys.argv[2])
    elif sys.argv[1] == "detail" and len(sys.argv) > 2:
        get_job_detail(sys.argv[2])
    else:
        print(__doc__)
        print("\n示例命令:")
        print("  python get_ci_runs.py                    # 查看最新 runs")
        print("  python get_ci_runs.py jobs <run_id>       # 查看 run 的 jobs")
        print("  python get_ci_runs.py detail <job_id>     # 查看 job 详情")
