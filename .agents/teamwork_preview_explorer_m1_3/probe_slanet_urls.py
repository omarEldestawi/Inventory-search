import urllib.request
import json

urls_to_test = [
    "https://huggingface.co/RapidAI/RapidTable/resolve/main/slanet-plus.onnx",
    "https://github.com/RapidAI/RapidTable/releases",
    "https://raw.githubusercontent.com/RapidAI/RapidTable/main/default_models.yaml",
]

for url in urls_to_test:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        print("OK:", url, resp.status)
    except Exception as e:
        print("FAIL:", url, e)
