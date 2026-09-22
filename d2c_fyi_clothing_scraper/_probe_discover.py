import re
import json
import httpx

html = open(r"d:\habsy\scrapping\d2c_fyi_clothing_scraper\_discover.html", encoding="utf-8").read()
print("len", len(html))

for pat in ["api/", "brand", "fashion", "graphql", "supabase", "strapi"]:
    print(pat, html.lower().count(pat))

chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
print("chunks", len(chunks))
for c in chunks:
    if "brand" in c.lower() or "fashion" in c.lower():
        print(c[:2000])
        print("---")

# try common API endpoints
urls = [
    "https://discoveringbrands.com/api/brands",
    "https://discoveringbrands.com/api/brands?category=fashion",
    "https://discoveringbrands.com/api/categories/fashion/brands",
]
headers = {"User-Agent": "Mozilla/5.0"}
for url in urls:
    try:
        r = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        print(url, r.status_code, r.text[:300])
    except Exception as e:
        print(url, e)
