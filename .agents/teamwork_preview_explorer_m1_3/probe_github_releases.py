import urllib.request
import json

url = "https://api.github.com/repos/RapidAI/RapidTable/releases"
req = urllib.request.Request(url, headers={"User-Agent": "Python/3.14"})
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print(f"Found {len(data)} releases")
        for rel in data:
            print("Release:", rel.get("tag_name"))
            for asset in rel.get("assets", []):
                print("  asset:", asset.get("name"), asset.get("browser_download_url"))
except Exception as e:
    print("Error:", e)
