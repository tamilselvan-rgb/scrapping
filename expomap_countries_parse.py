import re
from pathlib import Path
from bs4 import BeautifulSoup

html = Path(r"d:\habsy\scrapping\expomap_country_index.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
rows = []
for a in soup.find_all("a", href=True):
    h = a["href"]
    if re.fullmatch(r"/en/expo/country/[a-z0-9-]+/?", h):
        rows.append((h, a.get_text(" ", strip=True)))
# unique preserve order
seen = set()
uniq = []
for h, t in rows:
    if h not in seen:
        seen.add(h)
        uniq.append((h, t))
Path(r"d:\habsy\scrapping\expomap_countries.txt").write_text(
    "\n".join(f"{h}\t{t}" for h, t in uniq), encoding="utf-8"
)
print(len(uniq))
