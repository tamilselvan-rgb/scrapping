"""Scrape the official Automotive Management Live 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

EVENT_NAME = "Automotive Management Live"
EVENT_YEAR = "2026"
SOURCE_URL = "https://automotivemanagementlive.co.uk/exhibitors"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "AUTOMOTIVE_MANAGEMENT_LIVE_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "AUTOMOTIVE_MANAGEMENT_LIVE_2026_exhibitors.json"
SITE_HOST = "automotivemanagementlive.co.uk"
BLOCKED = {
    SITE_HOST, "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
    "x.com", "youtube.com", "tiktok.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year", "categories", "source_url",
]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "").replace("\xa0", " ")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value).strip(" .;,")
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED):
        return ""
    return host


def profile_pages() -> list[str]:
    urls = []
    for page_number in range(1, 6):
        page_url = f"{SOURCE_URL}?page={page_number}"
        response = requests.get(page_url, headers=HEADERS, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all(
            "a",
            class_="m-exhibitors-list__list__items__item__header__title__link",
            href=True,
        ):
            urls.append(urljoin("https://automotivemanagementlive.co.uk/", anchor["href"]))
    unique = list(dict.fromkeys(urls))
    if len(unique) != 84:
        raise RuntimeError(f"Expected 84 2026 profiles, found {len(unique)}")
    return unique


def listing_record(profile_url: str, page_html: str) -> dict[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    anchor = soup.find(
        "a",
        class_="m-exhibitors-list__list__items__item__header__title__link",
        href=lambda value: value and urljoin(
            "https://automotivemanagementlive.co.uk/", value
        ).rstrip("/") == profile_url.rstrip("/"),
    )
    if not anchor:
        anchor = soup.find(
            "a",
            class_="m-exhibitors-list__list__items__item__header__title__link",
            href=True,
        )
    return {}


def parse_listing_pages() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for page_number in range(1, 6):
        response = requests.get(
            f"{SOURCE_URL}?page={page_number}", headers=HEADERS, timeout=45
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for card in soup.find_all("article", role="listitem"):
            anchor = card.find(
                "a",
                class_="m-exhibitors-list__list__items__item__header__title__link",
                href=True,
            )
            if not anchor:
                continue
            name = clean(anchor.get_text(" ", strip=True))
            profile_url = urljoin(
                "https://automotivemanagementlive.co.uk/", anchor["href"]
            )
            if name == ".":
                name = "Tennants"
            stand_node = card.find(
                class_="m-exhibitors-list__list__items__item__header__meta__stand"
            )
            booth = clean(stand_node.get_text(" ", strip=True) if stand_node else "")
            booth = re.sub(r"^Stand:\s*", "", booth, flags=re.I)
            category_box = card.find(
                class_="m-exhibitors-list__list__items__item__body__categories"
            )
            categories = [
                clean(item.get_text(" ", strip=True))
                for item in category_box.find_all("li")
            ] if category_box else []
            records.append({
                "exhibitor_name": name,
                "domain": "",
                "contact_number": "",
                "mail": "",
                "location": "Birmingham, England, United Kingdom",
                "country": "United Kingdom",
                "booth_no": booth,
                "name": name,
                "desc": "",
                "email": "",
                "phone": "",
                "address": "",
                "city": "Birmingham",
                "linkedin_url": "",
                "profile_url": profile_url,
                "source_year": EVENT_YEAR,
                "categories": "; ".join(categories),
                "source_url": SOURCE_URL,
            })
    unique: dict[str, dict[str, str]] = {}
    for record in records:
        unique[record["profile_url"]] = record
    records = list(unique.values())
    if len(records) != 84:
        raise RuntimeError(f"Expected 84 unique exhibitors, found {len(records)}")
    return records


def parse_profile(record: dict[str, str], page_html: str) -> dict[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    title = (
        soup.find("h1", class_="m-exhibitor-entry__item__header__infos__title")
        or soup.find("h1", class_="m-exhibitor-entry__item__header__title")
    )
    if title and clean(title.get_text(" ", strip=True)) not in {".", ""}:
        record["exhibitor_name"] = record["name"] = clean(
            title.get_text(" ", strip=True)
        )
    description = soup.find("div", class_="m-exhibitor-entry__item__body__description")
    if description:
        record["desc"] = clean(description.get_text(" ", strip=True))
    if not record["desc"]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("description"):
                record["desc"] = clean(data["description"])
                break
    website = next(
        (
            a.get("href", "") for a in soup.find_all("a", href=True)
            if "visit website" in clean(a.get_text(" ", strip=True)).lower()
            and normalize_domain(a.get("href", ""))
        ),
        "",
    )
    record["domain"] = normalize_domain(website)
    record["linkedin_url"] = next(
        (
            a.get("href", "") for a in soup.find_all("a", href=True)
            if "linkedin.com" in a.get("href", "").lower()
            and "automotive-management-live" not in a.get("href", "").lower()
        ),
        "",
    )
    record["contact_number"] = next(
        (
            clean(a.get("href", "")[4:])
            for a in soup.find_all("a", href=True)
            if a.get("href", "").lower().startswith("tel:")
        ),
        "",
    )
    record["mail"] = next(
        (
            clean(a.get("href", "")[7:].split("?", 1)[0])
            for a in soup.find_all("a", href=True)
            if a.get("href", "").lower().startswith("mailto:")
            and "bauer" not in a.get("href", "").lower()
        ),
        "",
    )
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        entity = data.get("mainEntity", {}) if isinstance(data, dict) else {}
        address = entity.get("address", {}) if isinstance(entity, dict) else {}
        if isinstance(address, dict) and address.get("streetAddress"):
            record["address"] = clean(address.get("streetAddress", ""))
            record["city"] = clean(
                address.get("addressLocality", "") or record["city"]
            )
            record["country"] = clean(
                address.get("addressCountry", "") or record["country"]
            )
            record["location"] = ", ".join(
                part for part in (
                    record["address"], record["city"], record["country"]
                ) if part
            )
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def crawl_website(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for url in [base] + [urljoin(base, path) for path in (
        "contact/", "contact-us/", "about/", "about-us/", "impressum/",
    )]:
        try:
            response = session.get(url, timeout=12)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
            if match and "bauer" not in match.group(0).lower():
                record["mail"] = match.group(0)
        if not record["contact_number"]:
            tel = next(
                (
                    clean(a.get("href", "")[4:])
                    for a in soup.find_all("a", href=True)
                    if a.get("href", "").lower().startswith("tel:")
                ),
                "",
            )
            match = re.search(
                r"(?:phone|tel(?:ephone)?|mobile|call|contact)"
                r"[^0-9]{0,25}((?:\+|00)?\d[\d\s()./-]{7,}\d)",
                body,
                re.I,
            )
            record["contact_number"] = tel or (clean(match.group(1)) if match else "")
        if not record["address"] and soup.find("address"):
            record["address"] = clean(soup.find("address").get_text(" ", strip=True))
        if record["mail"] and record["contact_number"] and record["address"]:
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"] and record["location"].startswith("Birmingham"):
        record["location"] = record["address"]
    return record


def serper_fallback(records: list[dict[str, str]], api_key: str) -> None:
    if not api_key:
        return
    session = requests.Session()
    session.headers.update(HEADERS)
    for record in records:
        if record["domain"]:
            continue
        query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Birmingham'
        try:
            response = session.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 8},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            continue
        knowledge = data.get("knowledgeGraph") or {}
        record["domain"] = normalize_domain(knowledge.get("website", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = normalize_domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
        if not record["contact_number"]:
            record["contact_number"] = clean(knowledge.get("phone", ""))
        if not record["address"]:
            record["address"] = clean(knowledge.get("address", ""))
        record["phone"] = record["contact_number"]
        record["email"] = record["mail"]
        if record["address"] and record["location"].startswith("Birmingham"):
            record["location"] = record["address"]


def write_outputs(records: list[dict[str, str]]) -> None:
    records = sorted(records, key=lambda row: row["exhibitor_name"].casefold())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME,
        "year": EVENT_YEAR,
        "source": SOURCE_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records),
        "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    records = parse_listing_pages()
    with ThreadPoolExecutor(max_workers=10) as executor:
        jobs = []
        for record in records:
            try:
                response = requests.get(
                    record["profile_url"], headers=HEADERS, timeout=30
                )
                response.raise_for_status()
                jobs.append(executor.submit(parse_profile, record, response.text))
            except requests.RequestException:
                jobs.append(executor.submit(lambda value: value, record))
        enriched = [job.result() for job in as_completed(jobs)]
        website_jobs = [executor.submit(crawl_website, record) for record in enriched]
        enriched = [job.result() for job in as_completed(website_jobs)]
    serper_fallback(enriched, os.getenv("SERPER_API_KEY", ""))
    write_outputs(enriched)
    print(f"Saved {len(enriched)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
