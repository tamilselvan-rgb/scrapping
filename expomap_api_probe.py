import httpx

urls = [
    "https://expomap.ru/api/events/innotrans",
    "https://expomap.ru/en/expo/innotrans.json",
    "https://expomap.ru/expo/innotrans.json",
    "https://expomap.ru/api/v1/expo/innotrans",
    "https://expomap.ru/api/catalog/events?country=jordan",
]
headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
    for u in urls:
        try:
            r = client.get(u)
            print(r.status_code, r.headers.get("content-type", "")[:40], len(r.content), u)
        except Exception as e:
            print("ERR", type(e).__name__, u)
