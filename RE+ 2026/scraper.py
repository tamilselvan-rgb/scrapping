import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

OUT = Path(__file__).parent
ENDPOINT = "https://connect.re-plus.events/api/graphql"
VIEW_ID = "RXZlbnRWaWV3XzEyMjk2Nzk="
SOURCE = "https://www.re-plus.com/exhibitors/"
QUERY = """query($viewId: ID!, $endCursor: String) {
  view: Core_eventExhibitorListView(viewId: $viewId) {
    id
    exhibitors(cursor: {first: 50, after: $endCursor}) {
      nodes { name description booth }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""
BAD = {"linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
       "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com"}


def domain(url):
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if not host or any(host == x or host.endswith("." + x) for x in BAD):
            return ""
        return "https://" + host
    except Exception:
        return ""


def fetch_all():
    rows, cursor = [], None
    while True:
        r = requests.post(ENDPOINT, json={"query": QUERY, "variables": {
            "viewId": VIEW_ID, "endCursor": cursor}}, timeout=60)
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        page = payload["data"]["view"]["exhibitors"]
        rows.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return rows
        cursor = page["pageInfo"]["endCursor"]


def serper_missing(rows):
    if os.getenv("SKIP_SERPER") == "1":
        return {}
    env = Path(__file__).resolve().parents[1] / ".env"
    key = os.getenv("SERPER_API_KEY", "")
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        return {}
    found = {}
    for row in rows:
        if row["domain"]:
            continue
        try:
            result = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": f'"{row["company_name"]}" RE+ 2026 official website'},
                timeout=30,
            ).json()
            candidates = []
            kg = result.get("knowledgeGraph") or {}
            if kg.get("website"):
                candidates.append(kg["website"])
            candidates.extend(x.get("link", "") for x in result.get("organic", [])[:5])
            tokens = [x for x in re.findall(r"[a-z0-9]+", row["company_name"].lower()) if len(x) > 2]
            for candidate in candidates:
                d = domain(candidate)
                if d and (not tokens or any(t in d for t in tokens)):
                    found[row["company_name"]] = d
                    break
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.05)
    return found


def main():
    raw = fetch_all()
    rows = []
    for item in raw:
        urls = re.findall(r"https?://[^\s<>\])}]+", item.get("description") or "")
        rows.append({
            "company_name": (item.get("name") or "").strip(),
            "domain": next((domain(x.rstrip(".,;")) for x in urls if domain(x.rstrip(".,;"))), ""),
            "booth": (item.get("booth") or "").strip(),
            "description": (item.get("description") or "").strip(),
            "event_year": 2026,
            "source_url": SOURCE,
        })
    extra = serper_missing(rows)
    for row in rows:
        row["domain"] = row["domain"] or extra.get(row["company_name"], "")
    fields = ["company_name", "domain", "booth", "description", "event_year", "source_url"]
    with (OUT / "RE_PLUS_2026_exhibitors.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "RE_PLUS_2026_exhibitors.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(rows)} exhibitors; {sum(bool(x['domain']) for x in rows)} domains")


if __name__ == "__main__":
    main()
