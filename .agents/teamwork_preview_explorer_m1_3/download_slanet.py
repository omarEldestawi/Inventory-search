import urllib.request
import rapid_table
from pathlib import Path
import hashlib

url = "https://github.com/RapidAI/RapidTable/releases/download/assets/slanet-plus.onnx"
target_dir = Path(rapid_table.__file__).resolve().parent / "models"
target_dir.mkdir(parents=True, exist_ok=True)
target_path = target_dir / "slanet-plus.onnx"

print(f"Downloading from {url} to {target_path}...")
req = urllib.request.Request(url, headers={"User-Agent": "Python/3.14"})
with urllib.request.urlopen(req) as resp, open(target_path, "wb") as f:
    total_size = int(resp.headers.get("Content-Length", 0))
    print(f"Total size: {total_size / (1024*1024):.2f} MB")
    downloaded = 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        f.write(chunk)
        downloaded += len(chunk)

print(f"Downloaded {downloaded} bytes.")
h = hashlib.sha256(target_path.read_bytes()).hexdigest()
print(f"SHA256: {h}")
expected = "d57a942af6a2f57d6a4a0372573c696a2379bf5857c45e2ac69993f3b334514b"
print(f"Matches expected ({expected})? {h == expected}")
