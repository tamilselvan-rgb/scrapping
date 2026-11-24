from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse

OUT = Path(__file__).parent
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BAD_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
}


def domain(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == bad or host.endswith("." + bad) for bad in BAD_DOMAINS):
        return ""
    return "https://" + host


def company_name(value: str) -> str:
    # The floorplan app appends ASI supplier IDs to exhibitor names.
    value = re.sub(r"^\s*\*+\s*", "", value or "").strip()
    value = re.sub(r",\s*ASI/\d+\s*$", "", value, flags=re.I).strip()
    return value


def main() -> None:
    raw = json.loads((OUT / "source_exhibitors.json").read_text(encoding="utf-8"))
    grouped: dict[str, dict] = {}
    for item in raw:
        name = company_name(item.get("name") or item.get("displayName"))
        if not name or "\x00" in name:
            continue
        key = name.casefold()
        row = grouped.setdefault(key, {
            field: "" for field in FIELDS
        })
        row["company_name"] = name
        booth = str(item.get("boothNumber") or "").strip()
        if booth and booth not in row["booth"].split("; "):
            row["booth"] = "; ".join(x for x in [row["booth"], booth] if x)
        row["domain"] = row["domain"] or domain(item.get("website", ""))
        row["description"] = row["description"] or (item.get("profile") or "").strip()
        row["email"] = row["email"] or (item.get("email") or "").strip()
        row["mobile_primary"] = row["mobile_primary"] or (item.get("phone") or "").strip()
        row["full_address"] = ", ".join(
            x for x in [
                item.get("address1", ""), item.get("address2", ""),
                item.get("city", ""), item.get("state", ""),
                item.get("zip", ""), item.get("country", ""),
            ] if x
        )
        row["city"] = row["city"] or (item.get("city") or "").strip()
        row["linkedin_url"] = row["linkedin_url"] or ""
    output = list(grouped.values())
    assert all(list(row) == FIELDS for row in output)
    with (OUT / "ASI_SHOW_ORLANDO_2027_exhibitors.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    (OUT / "ASI_SHOW_ORLANDO_2027_exhibitors.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Exported {len(output)} unique exhibitors from {len(raw)} floorplan records; "
        f"{sum(bool(x['domain']) for x in output)} domains"
    )


if __name__ == "__main__":
    main()
