"""Test upload only - skip download"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glob

from config import FIT_FOLDER

# Find recently modified .fit files
recent_files = glob.glob(os.path.join(FIT_FOLDER, "*.fit"))
recent_files = [
    f for f in recent_files if os.path.getsize(f) > 10000
]  # Filter tiny files
recent_files.sort(key=os.path.getmtime, reverse=True)

print(f"Found {len(recent_files)} .fit files in {FIT_FOLDER}")
for f in recent_files[:10]:
    print(
        f"  {os.path.basename(f)} - {os.path.getsize(f)} bytes - {os.path.getmtime(f)}"
    )

# Select 3 files to test upload
test_files = recent_files[:3]
print(f"\nWill test upload with {len(test_files)} files")
for f in test_files:
    print(f"  {f}")

# Test login and upload
from garmin_sync import Garmin, restore_or_login

cn_username = "46301168@qq.com"
cn_password = "Liteq1986"

print("\nLogging into Garmin CN...")
garmin_cn_client = restore_or_login(cn_username, cn_password, "CN")
garmin_cn_wrapper = Garmin(garmin_cn_client, "CN", False)

import asyncio

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
future = asyncio.ensure_future(garmin_cn_wrapper.upload_activities_files(test_files))
loop.run_until_complete(future)
print("Upload test completed!")
