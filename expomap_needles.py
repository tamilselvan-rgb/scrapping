import re
from pathlib import Path

html = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
out = []
for needle in [
    "instagram",
    "Instagram",
    "facebook",
    "vk.com",
    "telegram",
    "hall",
    "Hall",
    "pavilion",
    "Pavilion",
    "innotrans.com",
    "official",
    "website",
    "Messe Berlin",
    "social",
]:
    idxs = [m.start() for m in re.finditer(re.escape(needle), html, re.I)]
    out.append(f"{needle}: {len(idxs)}")
    for i in idxs[:3]:
        out.append(html[max(0, i - 120) : i + 180].replace("\n", " "))
        out.append("---")

Path(r"d:\habsy\scrapping\expomap_event_needles.txt").write_text("\n".join(out), encoding="utf-8")
print("done")
