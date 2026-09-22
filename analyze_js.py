import requests
import re

url = "https://maps.goeshow.com/static/js/main.f6acaaa9.js"
r = requests.get(url, timeout=15)
text = r.text
print("JS length:", len(text))

# Search for URLs or endpoints
matches = re.findall(r'https?://[^\s"\'`]+', text)
print("URLs found:", set(matches))

endpoints = re.findall(r'["\'](/[^"\']+)["\']', text)
interesting = [e for e in endpoints if any(k in e.lower() for k in ['api', 'exhibitor', 'booth', 'map', 'data', 'json', 'profile', 'list'])]
print("Interesting endpoints:", set(interesting[:30]))

# Search for keys related to exhibitor profile
keys = re.findall(r'(\b[a-zA-Z0-9_]+)\s*:\s*["\']?[^,}\n]+', text)
exh_keys = [k for k in keys if any(w in k.lower() for w in ['exhibitor', 'booth', 'company', 'address', 'phone', 'website', 'domain'])]
print("Keys:", set(exh_keys[:20]))
