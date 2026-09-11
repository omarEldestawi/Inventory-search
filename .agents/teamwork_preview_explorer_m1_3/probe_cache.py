import os

home = os.path.expanduser("~")
print("User home:", home)

for name in [".cache", ".rapid_table", "AppData/Local/rapid_table", "AppData/Roaming/rapid_table"]:
    p = os.path.join(home, name)
    if os.path.exists(p):
        print("Found dir:", p)
        for root, dirs, files in os.walk(p):
            for f in files:
                if "slanet" in f.lower() or f.endswith(".onnx"):
                    print("  found:", os.path.join(root, f))
