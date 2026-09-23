import re
from pathlib import Path

detail = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
# find api-like paths
urls = sorted(set(re.findall(r"/api/[a-zA-Z0-9_./?-]{3,80}", detail)))
print("API PATHS")
for u in urls[:80]:
    print(u)

# social-ish keys in event store region
idx = detail.find("eventPageStore")
region = detail[idx : idx + 200000]
# unescape a bit for key scan
region2 = region.replace('\\"', '"')
keys = sorted(set(re.findall(r'"([a-zA-Z_]{2,40})"\s*:', region2)))
Path(r"d:\habsy\scrapping\expomap_event_keys.txt").write_text("\n".join(keys), encoding="utf-8")
print("keys", len(keys))

for n in ["instagram", "social", "hall", "pavilion", "vk", "facebook", "youtube", "web_page"]:
    print(n, region2.lower().count(n))
