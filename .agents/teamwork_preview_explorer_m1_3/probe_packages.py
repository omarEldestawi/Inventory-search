import sys
import os

print("Python:", sys.version)
print("Executable:", sys.executable)

packages = [
    "fitz",
    "customtkinter",
    "rapidocr_onnxruntime",
    "rapid_table",
    "pyinstaller",
    "pytest",
    "rapidfuzz",
    "pandas",
    "openpyxl",
    "PIL",
    "cv2",
    "onnxruntime",
]

for pkg in packages:
    try:
        mod = __import__(pkg)
        ver = getattr(mod, "__version__", getattr(mod, "version", "installed"))
        print(f"OK: {pkg} -> {ver}")
    except Exception as exc:
        print(f"FAIL: {pkg} -> {exc}")
