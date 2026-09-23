from pathlib import Path

html = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
needle = "eventPageStore"
idxs = []
start = 0
while True:
    i = html.find(needle, start)
    if i < 0:
        break
    idxs.append(i)
    start = i + len(needle)
print("count", len(idxs))
Path(r"d:\habsy\scrapping\expomap_markers.txt").write_text(
    "\n\n".join(f"{i}\n{html[i:i+120]}" for i in idxs),
    encoding="utf-8",
)
print("done")
