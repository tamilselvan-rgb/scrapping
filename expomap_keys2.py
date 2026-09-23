from pathlib import Path

detail = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
needle = '\\"web_page_url\\"'
idx = detail.find(needle)
print("escaped idx", idx)
if idx < 0:
    idx = detail.find("web_page_url")
    print("plain", idx)
else:
    chunk = detail[max(0, idx - 4000) : idx + 2500]
    Path(r"d:\habsy\scrapping\expomap_event_json_chunk.txt").write_text(chunk, encoding="utf-8")
    print("wrote", len(chunk))

# also look for instagram escaped
for n in ["instagram", "halls", "pavilion", "venue_name", "place_name", "city_name"]:
    print(n, detail.lower().count(n.lower()))
