import re
import json
from urllib.parse import unquote

html = open(r"d:\habsy\scrapping\d2c_fyi_clothing_scraper\_discover.html", encoding="utf-8").read()

# Extract all RSC chunks
chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
print("chunks", len(chunks))

for i, c in enumerate(chunks):
    decoded = c.encode("utf-8").decode("unicode_escape")
    if "website" in decoded.lower() or "brandName" in decoded or '"slug"' in decoded:
        print(f"=== chunk {i} ===")
        print(decoded[:5000])

# Search for brand-like JSON objects
for m in re.finditer(r'\{"_id":"[a-f0-9]{24}","name":"[^"]+","slug":"[^"]+"', html):
    print("brand obj:", m.group(0)[:200])

# count brand profile paths
slugs = set(re.findall(r'/brand/([a-z0-9-]+)', html, re.I))
print("brand slugs in html", len(slugs), list(slugs)[:20])

# look for website fields
websites = re.findall(r'"website":"(https?://[^"]+)"', html)
print("websites found", len(websites), websites[:10])

# category brand arrays
for pat in [r'"brands":\[', r'brandList', r'fashionBrands']:
    if pat in html:
        print("found pattern", pat)
