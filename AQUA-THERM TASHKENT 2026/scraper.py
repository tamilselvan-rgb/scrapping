import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "AQUA_THERM_TASHKENT_2026"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
BASE_URL = "https://aquatherm-tashkent.uz"
LIST_URL = f"{BASE_URL}/en/exhibitors-list"
DATA_URL = f"{BASE_URL}/ERAForms/companies_list.php?l=en&exhibition=482"
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "company_name", "booth", "description", "city", "linkedin_url",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com", "google.com",
    "aquatherm-tashkent.uz",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def cell_text(value):
    return clean(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


def domain_url(value):
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def fetch(url, **kwargs):
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60, **kwargs)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def profile_links():
    payload = {
        "draw": "1", "start": "0", "length": "5000",
        "search[value]": "", "search[regex]": "false",
        "field1": "0", "field2": "0", "field3": "", "field4": "0",
    }
    response = requests.post(
        DATA_URL, data=payload,
        headers={**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": LIST_URL},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    records = []
    seen = set()
    for row in data.get("data", []):
        if not row or len(row) < 4:
            continue
        cell = BeautifulSoup(row[0], "html.parser").select_one("a[href]")
        if not cell:
            continue
        profile_url = urljoin(BASE_URL, cell["href"])
        if profile_url in seen:
            continue
        seen.add(profile_url)
        records.append({
            "profile_url": profile_url,
            "exhibitor_name": clean(cell.get_text(" ", strip=True)),
            "country": cell_text(row[1]),
            "booth": cell_text(row[2]),
            "location": cell_text(row[3]),
        })
    if not records:
        raise RuntimeError("No 2026 Aquatherm exhibitors found")
    return records


def profile(record):
    try:
        soup = BeautifulSoup(fetch(record["profile_url"]), "html.parser")
    except requests.RequestException as exc:
        print(f"Profile failed for {record['exhibitor_name']}: {exc}")
        return record
    heading = soup.select_one(".company__name")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    stand = soup.select_one(".company__stand")
    if stand:
        text = clean(stand.get_text(" ", strip=True))
        record["booth"] = clean(re.sub(r"^Stand Number:\s*", "", text, flags=re.I))
    description = soup.select_one(".company__description")
    record["description"] = clean(description.get_text(" ", strip=True)) if description else ""
    website = soup.select_one(".company__website a[href]")
    record["domain"] = domain_url(website.get("href")) if website else ""
    record["linkedin_url"] = ""
    for link in soup.select(".company__socials a[href*='linkedin.com/']"):
        record["linkedin_url"] = link["href"].split("?", 1)[0]
        break
    return record


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def name_tokens(name):
    return {
        token for token in re.findall(r"[a-z0-9]+", name.casefold())
        if len(token) >= 3 and token not in {"ltd", "llc", "inc", "co", "company"}
    }


def matching_domain(name, domain):
    if not domain:
        return ""
    host = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].casefold())
    tokens = name_tokens(name)
    return domain if host and tokens and any(
        token in host or host in token for token in tokens
    ) else ""


def serper_enrich(record):
    if record.get("domain"):
        record["domain"] = matching_domain(record["exhibitor_name"], record["domain"])
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": f'"{record["exhibitor_name"]}" official website {record["location"]}',
                "gl": "uz", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        candidates = [graph.get("website", "")]
        candidates.extend(item.get("link", "") for item in data.get("organic", []))
        for candidate in candidates:
            domain = matching_domain(record["exhibitor_name"], domain_url(candidate))
            if domain:
                record["domain"] = domain
                break
        if not record.get("contact_number"):
            record["contact_number"] = clean(graph.get("phone", ""))
        if not record.get("location"):
            record["location"] = clean(graph.get("address", ""))
    except requests.RequestException as exc:
        message = f"Serper failed for {record['exhibitor_name']}: {exc}"
        print(message.encode("ascii", "replace").decode("ascii"))
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = profile_links()
    print(f"Found {len(records)} 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile, records))
        records = list(pool.map(serper_enrich, records))
    for record in records:
        record["company_name"] = record["exhibitor_name"]
        record["mail"] = ""
        record["contact_number"] = record.get("contact_number", "")
        record["city"] = "Tashkent"
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    normalized = [{field: record.get(field, "") for field in FIELDS} for record in records]
    base = OUTPUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    base.with_suffix(".json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Domains found: {sum(bool(row['domain']) for row in normalized)}/{len(normalized)}")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
