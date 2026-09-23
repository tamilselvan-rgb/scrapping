import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

html = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
out = []

scripts = soup.find_all("script", type="application/ld+json")
out.append(f"ldjson {len(scripts)}")
for i, s in enumerate(scripts):
    txt = s.string or ""
    out.append(f"--- {i} {len(txt)} ---")
    out.append(txt[:5000])

# external links
out.append("EXTERNAL")
seen = set()
for a in soup.find_all("a", href=True):
    h = a["href"]
    if h.startswith("http") and "expomap" not in h:
        key = (h, a.get_text(" ", strip=True)[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{h} | {key[1]}")

out.append("TEXT SNIPPETS")
text = soup.get_text("\n", strip=True)
for needle in ["Instagram", "instagram", "Website", "Hall", "Pavilion", "Venue", "Organizer"]:
    i = text.lower().find(needle.lower())
    out.append(f"needle {needle} at {i}")
    if i >= 0:
        out.append(text[max(0, i - 80) : i + 200])

Path(r"d:\habsy\scrapping\expomap_event_parse.txt").write_text("\n".join(out), encoding="utf-8")
print("ok", len(seen), "external")
