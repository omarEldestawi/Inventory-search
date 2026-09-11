import os
import shutil
import subprocess
import sys

print("--- 1. PyInstaller Check ---")
try:
    res = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
    print("PyInstaller module:", res.stdout.strip())
except Exception as e:
    print("PyInstaller module error:", e)

pyinstaller_bin = shutil.which("pyinstaller")
print("pyinstaller on PATH:", pyinstaller_bin)

print("\n--- 2. Inno Setup Compiler (ISCC.exe) Check ---")
iscc_bin = shutil.which("ISCC") or shutil.which("iscc.exe") or shutil.which("ISCC.exe")
print("ISCC on PATH:", iscc_bin)

if not iscc_bin:
    # Check standard Inno Setup installation paths on Windows
    possible_paths = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    ]
    for p in possible_paths:
        if os.path.exists(p):
            print("Found ISCC at:", p)
            iscc_bin = p
            break

if iscc_bin:
    try:
        res = subprocess.run([iscc_bin, "/?"], capture_output=True, text=True)
        # First line of ISCC output
        print("ISCC version banner:", res.stdout.splitlines()[0] if res.stdout else res.stderr.splitlines()[0])
    except Exception as e:
        print("ISCC run error:", e)
else:
    print("WARNING: ISCC.exe not found on PATH or standard paths!")

print("\n--- 3. Git Check ---")
git_env_path = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")
print(f"Checking {git_env_path} exists: {os.path.exists(git_env_path)}")

git_bin = shutil.which("git") or (git_env_path if os.path.exists(git_env_path) else None)
print("Git binary:", git_bin)

if git_bin:
    try:
        res = subprocess.run([git_bin, "--version"], capture_output=True, text=True)
        print("Git version:", res.stdout.strip())
        res_remote = subprocess.run([git_bin, "remote", "-v"], capture_output=True, text=True)
        print("Git remotes:\n", res_remote.stdout.strip())
        res_branch = subprocess.run([git_bin, "branch", "-a"], capture_output=True, text=True)
        print("Git branches:\n", res_branch.stdout.strip())
    except Exception as e:
        print("Git error:", e)

print("\n--- 4. Existing build/packaging files ---")
for fn in ["PharmaProcurement.spec", "installer.iss", "setup.iss"]:
    print(f"{fn} exists: {os.path.exists(fn)}")
