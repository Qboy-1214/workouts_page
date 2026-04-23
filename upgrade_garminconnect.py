import subprocess
import sys

# Upgrade garminconnect
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "--upgrade", "garminconnect"],
    capture_output=True,
    text=True,
)
print("=== pip install output ===")
print(result.stdout)
print(result.stderr)
print(f"Exit code: {result.returncode}")

# Check version
import garminconnect

print(f"\n=== garminconnect info ===")
print(f"Module file: {garminconnect.__file__}")

# Check for is_cn parameter
import inspect

sig = inspect.signature(garminconnect.Garmin.__init__)
print(f"Garmin.__init__ signature: {sig}")
print(f"Parameters: {list(sig.parameters.keys())}")

# Check client file for CN support
client_file = "C:\\Users\\Yong\\AppData\\Roaming\\Python\\Python314\\site-packages\\garminconnect\\client.py"
with open(client_file, "r", encoding="utf-8") as f:
    content = f.read()
    if "garmin.cn" in content or "is_cn" in content:
        print("\n=== Found CN-related code ===")
        for i, line in enumerate(content.split("\n"), 1):
            if "garmin.cn" in line or "is_cn" in line:
                print(f"Line {i}: {line.strip()}")
