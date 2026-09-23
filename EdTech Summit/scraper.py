import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT_YEAR = 2026
LISTING_URL = "https://edtech.schoolsandacademiesshow.co.uk/exhibitors"
WIDGET_BASE = (
    "https://app.swapcard.com/widget/event/"
    "the-schools-and-academies-show-birmingham-2026/exhibitor/"
)
VIEW_ID = "RXZlbnRWaWV3XzEyNzI5MDM="
EVENT_ID = "RXZlbnRfNDQyODIyNQ=="
GRAPHQL_URL = "https://api.swapcard.com/graphql"
SERPER_DOMAIN_CACHE = {
    "Able Canopies Ltd.": "https://www.ablecanopies.co.uk/",
    "Aidos": "https://aidosprotects.com/",
    "CHG-MERIDIAN": "https://www.chg-meridian.com/global-en/",
}
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\ufffd", "")).strip()


def root_domain(url):
    host = urlparse(url or "").netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def request_text(url):
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; EdTech-Summit-2026/1.0)"},
            timeout=35,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text
    except requests.RequestException:
        return ""


def graphql(query, variables):
    try:
        response = requests.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers={
                "Origin": "https://app.swapcard.com",
                "x-client-app": "web-user",
                "Content-Type": "application/json",
            },
            timeout=35,
        )
        response.raise_for_status()
        return response.json().get("data", {})
    except (requests.RequestException, ValueError):
        return {}


def serper_domain(name):
    env_file = Path(__file__).resolve().parents[1] / ".env"
    api_key = ""
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
    if not api_key:
        return ""
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{name}" official website {EVENT_YEAR}', "gl": "uk", "hl": "en"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return ""
    kg = data.get("knowledgeGraph") or {}
    if kg.get("website"):
        return kg["website"]
    blocked = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com",
               "x.com", "wikipedia.org", "youtube.com", "yellowpages", "yelp.com")
    for result in data.get("organic", []):
        link = result.get("link", "")
        host = urlparse(link).netloc.lower()
        if link and not any(item in host for item in blocked):
            return link
    return ""


LIST_QUERY = """
query EventExhibitorList(
  $viewId: ID!
  $endCursor: String
) {
  view: Core_eventExhibitorListView(viewId: $viewId) {
    exhibitors(cursor: { first: 50, after: $endCursor }) {
      nodes {
        id: _id
        name
        htmlDescription
        type
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


def list_exhibitors():
    exhibitors = []
    cursor = None
    while True:
        data = graphql(LIST_QUERY, {"viewId": VIEW_ID, "endCursor": cursor})
        connection = data.get("view", {}).get("exhibitors", {})
        exhibitors.extend(connection.get("nodes", []))
        page_info = connection.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            raise RuntimeError("Swapcard returned a next page without a cursor")
    return exhibitors


def address_values(address):
    address = address or {}
    parts = [
        address.get("street"), address.get("place"), address.get("city"),
        address.get("state"), address.get("zipCode"), address.get("country"),
    ]
    location = clean(", ".join(clean(x) for x in parts if clean(x)))
    return location, clean(address.get("city")), clean(address.get("country"))


def profile_record(exhibitor):
    profile_url = WIDGET_BASE + exhibitor["id"]
    html = request_text(profile_url)
    soup = BeautifulSoup(html, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    state = {}
    if next_data:
        try:
            payload = json.loads(next_data.get_text())
            state = payload.get("props", {}).get("apolloState", {})
        except (TypeError, ValueError):
            pass
    entity = next(
        (value for key, value in state.items() if key.startswith("Core_Exhibitor:")),
        {},
    )
    website = (
        entity.get("websiteUrl")
        or SERPER_DOMAIN_CACHE.get(exhibitor["name"])
        or serper_domain(exhibitor["name"])
    )
    address, city, country = address_values(entity.get("address"))
    phone_values = entity.get("phoneNumbers") or []
    phones = []
    for value in phone_values:
        if isinstance(value, dict):
            value = value.get("number") or value.get("value") or value.get("phone")
        if clean(value):
            phones.append(clean(value))
    social = entity.get("socialNetworks") or []
    linkedin = ""
    for value in social:
        if isinstance(value, dict) and str(value.get("type", "")).upper() == "LINKEDIN":
            profile = clean(value.get("profile"))
            linkedin = profile if profile.startswith("http") else f"https://www.linkedin.com/{profile}"
    event_data = entity.get(f'withEvent({{"eventId":"{EVENT_ID}"}})') or {}
    booth = event_data.get("booth") or {}
    booth_name = booth.get("name", "") if isinstance(booth, dict) else str(booth)
    description = clean(
        entity.get("description")
        or BeautifulSoup(entity.get("htmlDescription") or "", "html.parser").get_text(" ")
        or exhibitor.get("htmlDescription", "")
    )
    return {
        "exhibitor_name": clean(entity.get("name") or exhibitor["name"]),
        "domain": root_domain(website),
        "contact_number": "; ".join(phones),
        "mail": clean(entity.get("email")),
        "location": address,
        "country": country,
        "booth_no": clean(booth_name),
        "desc": description,
        "email": clean(entity.get("email")),
        "phone": "; ".join(phones),
        "address": address,
        "city": city,
        "linkedin_url": linkedin,
        "event_year": EVENT_YEAR,
        "source_profile": profile_url,
        "source_website": website,
        "exhibitor_type": clean(entity.get("type") or exhibitor.get("type")),
    }


def main():
    # Confirm the official 2026 page is reachable before using its widget.
    if not request_text(LISTING_URL):
        raise RuntimeError("The official 2026 EdTech Summit listing could not be loaded")
    exhibitors = list_exhibitors()
    if len(exhibitors) < 20:
        raise RuntimeError(f"Expected the populated 2026 directory, found {len(exhibitors)}")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile_record, exhibitors))
    base = "EDTECH_SUMMIT_2026_exhibitors"
    (OUTPUT / f"{base}.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "email", "phone", "address", "city",
        "linkedin_url", "event_year", "source_profile", "source_website",
        "exhibitor_type",
    ]
    with (OUTPUT / f"{base}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    print(f"Exported {len(records)} exhibitors")


if __name__ == "__main__":
    main()
