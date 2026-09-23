import re
from pathlib import Path

html = Path(r"d:\habsy\scrapping\expomap_germany_probe.html").read_text(encoding="utf-8")
print("web_page_url", html.count("web_page_url"))
print("instagram", html.lower().count("instagram"))
print("hall_name", html.count("hall"))

# find a chunk of embedded event json on detail page
detail = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
idx = detail.find('"web_page_url"')
print("detail idx", idx)
chunk = detail[idx - 2500 : idx + 1500]
Path(r"d:\habsy\scrapping\expomap_event_json_chunk.txt").write_text(chunk, encoding="utf-8")
print("chunk written", len(chunk))

# look for keys around web_page
keys = sorted(set(re.findall(r'"([a-zA-Z_]{3,40})":', detail[idx - 8000 : idx + 4000])))
Path(r"d:\habsy\scrapping\expomap_event_keys.txt").write_text("\n".join(keys), encoding="utf-8")
print("keys", len(keys))
