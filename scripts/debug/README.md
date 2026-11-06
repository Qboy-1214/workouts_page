# CI 调试工具说明

用于快速查看和调试 GitHub Actions CI 运行状态。

## 文件说明

| 文件 | 说明 |
|------|------|
| `get_ci_info.py` | 快速查看 CI 运行的简化脚本 |
| `__init__.py` | 完整的 CI 调试工具集 |

## 快速使用

```bash
cd scripts/debug
```

### 1. 查看最新 CI runs

```bash
python get_ci_info.py runs
```

输出示例:
```
=========== 最新 5 个 CI runs ============
✓ [24902644296] Run Data Sync
   Status: completed | success
   Commit: fix: resolve CI lint failures by adjusting ruff/black conf...

✗ [24902644289] CI
   Status: completed | failure
   Commit: fix: resolve CI lint failures by adjusting ruff/black conf...
```

### 2. 查看指定 Run 的 Jobs

```bash
python get_ci_info.py jobs <run_id>
```

示例:
```bash
python get_ci_info.py jobs 24902644289
```

输出:
```
============ Run 24902644289 Jobs =============
✓ [72923981907] node_lint_and_test (24)
   Status: completed | success
✗ [72923981927] python_lint_and_test (3.13)
   Status: completed | failure
```

### 3. 查看 Job 详情和步骤

```bash
python get_ci_info.py detail <job_id>
```

示例:
```bash
python get_ci_info.py detail 72923981927
```

输出:
```
============= Job 72923981927 =============
Name: python_lint_and_test (3.13)
Conclusion: failure

Steps:
  [✓] Set up job
  [✓] Run actions/checkout@v4
  [✓] Set up Python 3.13
  [✓] Install dependencies
  [✓] Run GPX sync test
  [✗] Check formatting (black)
  [○] Lint with Ruff
```

## 工作流程

1. 先用 `runs` 查看最新的 CI 运行
2. 找到失败的 run ID
3. 用 `jobs <run_id>` 查看该 run 的所有 jobs
4. 用 `detail <job_id>` 查看具体失败的 job 详情

## Garmin 帐号配置

在 `__init__.py` 中配置你的 Garmin 帐号信息：

```python
# Garmin 国际区 (garmin.com)
GARMIN_COM_USERNAME = "your_email@example.com"
GARMIN_COM_PASSWORD = "your_password"

# Garmin 中国区 (garmin.com.cn)
GARMIN_CN_USERNAME = "your_email@example.com"
GARMIN_CN_PASSWORD = "your_password"
```

## 环境变量

如需使用自己的 GitHub Token:

```bash
export GITHUB_TOKEN=your_token_here
python get_ci_info.py runs
```

Token 需要有 `repo` 或 `workflow` 权限。

## GitHub 网页直接查看

- 查看所有 runs: https://github.com/Qboy-1214/workouts_page/actions
- 查看单个 run: https://github.com/Qboy-1214/workouts_page/actions/runs/<run_id>
- 查看单个 job: https://github.com/Qboy-1214/workouts_page/actions/runs/<run_id>/job/<job_id>
