import subprocess
import sys

res = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
print("PIP CHECK RETURN CODE:", res.returncode)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)

res2 = subprocess.run([sys.executable, "-m", "pip", "show", "rapid_table"], capture_output=True, text=True)
print("RAPID TABLE INFO:\n", res2.stdout)
