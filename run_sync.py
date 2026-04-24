"""Run garmin sync with credentials from temp file"""

import os
import subprocess
import sys

# Read .env file and set environment variables
env_file = os.path.join(os.path.dirname(__file__), ".temp_garmin.env")
with open(env_file, "r") as f:
    for line in f:
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

# Run the sync script
result = subprocess.run(
    [sys.executable, "run_page/sync_com_to_cn.py", "--limit", "10"],
    capture_output=False,
)
sys.exit(result.returncode)
