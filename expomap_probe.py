import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

html = Path(r"d:\habsy\scrapping\expomap_germany_probe.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
out = []
scripts = soup.find_all("script", type="application/ld+json")
out.append(f"ldjson count {len(scripts)}")
for i, s in enumerate(scripts[:4]):
    txt = s.string or ""
    out.append(f"--- script {i} len {len(txt)} ---")
    out.append(txt[:4000])

pages = sorted(set(re.findall(r'href="([^"]*page=[^"]*)"', html)))
out.append("PAGES")
out.extend(pages[:40])

links = []
for a in soup.find_all("a", href=True):
    h = a["href"]
    if "/en/expo/" in h and "/country/" not in h and "/theme/" not in h and "/city/" not in h:
        links.append((h, a.get_text(" ", strip=True)[:100]))
out.append(f"event-like links {len(links)} unique {len({x[0] for x in links})}")
for h, t in links[:20]:
    out.append(f"{h} | {t}")

# country links from index if present
country_html_path = Path(r"d:\habsy\scrapping\expomap_country_index.html")
if not country_html_path.exists():
    out.append("NO COUNTRY INDEX YET")

Path(r"d:\habsy\scrapping\expomap_probe_parse.txt").write_text("\n".join(out), encoding="utf-8")
print("ok", len(out))
