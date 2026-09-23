import re
from pathlib import Path
from bs4 import BeautifulSoup

html = Path(r"d:\habsy\scrapping\expomap_country_index.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")
for slug in ["china", "russia", "turkey", "uganda", "ethiopia", "usa"]:
    print("====", slug)
    for a in soup.find_all("a", href=True):
        if f"/en/expo/country/{slug}" in a["href"]:
            print(repr(a["href"]), repr(a.get_text(" ", strip=True)[:80]))
