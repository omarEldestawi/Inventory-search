import subprocess
import sys

res = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_e2e_procurement.py", "-v", "--tb=short"],
    capture_output=True,
    text=True,
)
print("Return code:", res.returncode)
print(res.stdout)
