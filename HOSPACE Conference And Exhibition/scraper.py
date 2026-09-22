import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT_NAME = "HOSPACE Conference And Exhibition"
EVENT_YEAR = 2026
LISTING_URL = "https://www.hospace.org/exhibitors"
PROFILE_URL = "https://hospace.org/exhibitor-profiles"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HOSPACE-2026-exhibitor-research/1.0)"
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def root_domain(url):
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def get(url):
    try:
        response = SESSION.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return ""


def listing_records(html):
    soup = BeautifulSoup(html, "html.parser")
    websites = {}
    pending_slug = ""
    for link in soup.find_all("a", href=True):
        label = clean(link.get_text(" ", strip=True))
        if label == "Exhibitor Profile":
            pending_slug = link["href"].split("#", 1)[-1].lower()
        elif label == "Exhibitor Website" and pending_slug:
            websites[pending_slug] = link["href"]
            pending_slug = ""
    return websites


def profile_descriptions(html):
    soup = BeautifulSoup(html, "html.parser")
    descriptions = [
        clean(node.get_text(" ", strip=True))
        for node in soup.select('[data-testid="richTextElement"]')
    ]
    # Each profile has a heading rich-text node followed by its description.
    return [text for text in descriptions if len(text) >= 150]


def profile_items(html):
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select('[data-testid="richTextElement"]')
    items = []
    for index in range(2, len(nodes) - 1, 2):
        name = clean(nodes[index].get_text(" ", strip=True))
        description = clean(nodes[index + 1].get_text(" ", strip=True))
        if name and len(description) >= 150:
            items.append({"name": name, "description": description})
    return items


def load_api_key():
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def serper_search(api_key, name, domain):
    if not api_key:
        return {}
    try:
        response = SESSION.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={
                "q": f'"{name}" official website contact address phone email {EVENT_YEAR}',
                "gl": "uk",
                "hl": "en",
                "num": 10,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return {}
    # Prefer first-party results; directory/social snippets are excluded.
    excluded = (
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "wikipedia.org",
        "youtube.com",
        "yellowpages",
        "yelp.com",
    )
    official = []
    for result in data.get("organic", []):
        link = result.get("link", "")
        if domain and domain in urlparse(link).netloc.lower():
            official.append(result)
    if not domain:
        for result in data.get("organic", []):
            host = urlparse(result.get("link", "")).netloc.lower()
            if host and not any(blocked in host for blocked in excluded):
                official.append(result)
    return {"knowledgeGraph": data.get("knowledgeGraph") or {}, "organic": official}


def first_email(text):
    matches = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or "")
    return next((x.lower() for x in matches if not x.endswith("@example.com")), "")


def first_phone(text):
    patterns = re.findall(
        r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text or ""
    )
    for value in patterns:
        normalized = clean(value)
        digits = re.sub(r"\D", "", normalized)
        if re.search(r"\b(?:19|20)\d{2}[-–]\d{2,4}\b", normalized):
            continue
        if not any(marker in normalized for marker in ("+", " ", "(", ")", "-")):
            continue
        if 8 <= len(digits) <= 16:
            return normalized
    return ""


def website_contact(url):
    if not url:
        return {}
    html = get(url)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    return {"mail": first_email(text), "contact_number": first_phone(text)}


def record_for(item, description, api_key):
    domain_overrides = {
        # The portal links to the HOSPA sponsorship page instead of Planet's
        # company site; use Planet's official root domain.
        "Planet": "planetpayment.com",
    }
    domain = domain_overrides.get(item["name"], root_domain(item["website"]))
    contact = {} if item["name"] == "Planet" else website_contact(item["website"])
    search = serper_search(api_key, item["name"], domain)
    kg = search.get("knowledgeGraph", {})
    if not domain:
        website = kg.get("website", "")
        if not website and search.get("organic"):
            website = search["organic"][0].get("link", "")
        domain = root_domain(website)
    official_text = " ".join(
        clean(x.get("snippet", ""))
        for x in search.get("organic", [])
    )
    combined = f"{official_text} {json.dumps(kg, ensure_ascii=False)}"
    mail = contact.get("mail") or first_email(combined)
    phone = contact.get("contact_number") or first_phone(combined)
    address = clean(kg.get("address", ""))
    city = ""
    country = "United Kingdom"
    if address:
        parts = [clean(x) for x in re.split(r"[,|]", address) if clean(x)]
        if len(parts) >= 2:
            city = parts[-2] if parts[-1].lower() in {
                "united kingdom", "uk", "england", "great britain"
            } else parts[-1]
    linkedin = ""
    return {
        "exhibitor_name": item["name"],
        "domain": domain,
        "contact_number": phone,
        "mail": mail,
        "location": address,
        "country": country,
        "booth_no": "",
        "desc": description,
        "email": mail,
        "phone": phone,
        "address": address,
        "city": city,
        "linkedin_url": linkedin,
        "event_year": EVENT_YEAR,
        "source_profile": f"{PROFILE_URL}#{item['slug']}",
        "source_website": item["website"],
    }


def main():
    listing = get(LISTING_URL)
    profiles = get(PROFILE_URL)
    websites = listing_records(listing)
    items = profile_items(profiles)
    aliases = {
        "Adyen": "exhibadyen",
        "HOSPA Professional Development": "hospapd",
        "Discover Network and Diners Club International": "discovernetwork",
        "Focus on Hospitality": "focus",
        "RUCKUS Networks": "ruckus",
    }
    for item in items:
        item["slug"] = aliases.get(
            item["name"], re.sub(r"[^a-z0-9]", "", item["name"].lower())
        )
        item["website"] = websites.get(item["slug"], "")
    if len(items) != 27:
        raise RuntimeError(
            f"Expected 27 official 2026 profiles, got {len(items)}"
        )
    api_key = load_api_key()
    records = []
    for item in items:
        records.append(record_for(item, item["description"], api_key))
        time.sleep(0.2)

    json_path = OUTPUT / "HOSPACE_CONFERENCE_AND_EXHIBITION_2026_exhibitors.json"
    csv_path = OUTPUT / "HOSPACE_CONFERENCE_AND_EXHIBITION_2026_exhibitors.csv"
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "email", "phone", "address", "city",
        "linkedin_url", "event_year", "source_profile", "source_website",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    print(f"Exported {len(records)} exhibitors")
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()
