import subprocess
import sys

res = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True)
print("PIP LIST:")
for line in res.stdout.splitlines():
    if any(k in line.lower() for k in ["rapid", "tqdm", "pyinstaller", "onnx", "torch", "custom", "table", "fitz", "pymupdf"]):
        print(" ", line)
