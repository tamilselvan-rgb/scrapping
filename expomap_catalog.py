from pathlib import Path

html = Path(r"d:\habsy\scrapping\expomap_germany_probe.html").read_text(encoding="utf-8")
idx = html.find("catalogStore")
print("catalogStore", idx)
if idx > 0:
    Path(r"d:\habsy\scrapping\expomap_catalog_chunk.txt").write_text(html[idx:idx+3000], encoding="utf-8")

# pagination total
for n in ["pagination", "totalCount", "pageCount", "eventsCount", "hasNext"]:
    print(n, html.count(n))

idx2 = html.find("eventsCount")
print("eventsCount idx", idx2)
if idx2 > 0:
    print(html[idx2-100:idx2+200])
