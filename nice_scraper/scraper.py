import os
import re
import csv
import ssl
import logging
from urllib.parse import urlparse
import urllib.request
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_URL = "https://nice-nusantaraconvex.com"
EVENTS_LIST_URL = "https://nice-nusantaraconvex.com/events?page={page}"
TOTAL_PAGES = 3

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "nice_events.csv")

MONTH_MAP = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}

# Location details for NICE Nusantara Convex
VENUE_NAME = "Nusantara International Convention Exhibition (NICE)"
CITY_NAME = "Tangerang"
COUNTRY_NAME = "Indonesia"

def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def fetch_html(url, ssl_context):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, context=ssl_context, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")

def clean_domain(url_or_domain):
    if not url_or_domain:
        return ""
    val = url_or_domain.strip()
    if not val.startswith("http://") and not val.startswith("https://"):
        val = "https://" + val
    try:
        parsed = urlparse(val)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url_or_domain.strip()

def parse_dates(badge_text, cal_text):
    """
    badge_text: e.g. "19 - 20 Sep" or "02 - 04 Oct"
    cal_text: e.g. "Saturday, 19 September 2026"
    """
    year = "2026"
    # Find year from cal_text if present
    year_match = re.search(r"\b(20\d{2})\b", cal_text)
    if year_match:
        year = year_match.group(1)

    start_date = ""
    end_date = ""

    # Parse badge text like "19 - 20 Sep"
    badge_clean = badge_text.strip()
    match_badge = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s*([a-zA-Z]+)", badge_clean)
    if match_badge:
        start_day = int(match_badge.group(1))
        end_day = int(match_badge.group(2))
        month_str = match_badge.group(3).lower()
        month_num = MONTH_MAP.get(month_str, "01")
        start_date = f"{year}-{month_num}-{start_day:02d}"
        end_date = f"{year}-{month_num}-{end_day:02d}"
    else:
        # Fallback to single day in badge or cal_text
        single_badge = re.search(r"(\d{1,2})\s*([a-zA-Z]+)", badge_clean)
        if single_badge:
            day = int(single_badge.group(1))
            month_str = single_badge.group(2).lower()
            month_num = MONTH_MAP.get(month_str, "01")
            start_date = f"{year}-{month_num}-{day:02d}"
            end_date = start_date
        elif cal_text:
            cal_match = re.search(r"(\d{1,2})\s+([a-zA-Z]+)\s+(20\d{2})", cal_text)
            if cal_match:
                day = int(cal_match.group(1))
                month_str = cal_match.group(2).lower()
                month_num = MONTH_MAP.get(month_str, "01")
                year_found = cal_match.group(3)
                start_date = f"{year_found}-{month_num}-{day:02d}"
                end_date = start_date

    return start_date, end_date

def scrape_events():
    ssl_context = create_ssl_context()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_events = []
    seen_urls = set()

    for page in range(1, TOTAL_PAGES + 1):
        page_url = EVENTS_LIST_URL.format(page=page)
        logging.info(f"Scraping list page {page}/{TOTAL_PAGES}: {page_url}")

        try:
            html = fetch_html(page_url, ssl_context)
            soup = BeautifulSoup(html, "html.parser")
            
            cards = soup.find_all("a", href=re.compile(r"/events/[^?]+$"))
            logging.info(f"Found {len(cards)} event cards on page {page}")

            for card in cards:
                event_href = card.get("href")
                if not event_href:
                    continue
                if not event_href.startswith("http"):
                    event_url = BASE_URL + event_href
                else:
                    event_url = event_href

                if event_url in seen_urls:
                    continue
                seen_urls.add(event_url)

                # Card title
                title_elem = card.find("p", class_=re.compile(r"line-clamp-2"))
                title = title_elem.get_text(strip=True) if title_elem else ""

                # Date badge on card (e.g. "19 - 20 Sep")
                badge_elem = card.find("div", class_=re.compile(r"bg-\[#171C8F\]"))
                badge_text = badge_elem.get_text(separator=" ", strip=True) if badge_elem else ""

                # Hall / location on card
                hall_elem = card.find("p", class_="truncate")
                card_hall = hall_elem.get_text(strip=True) if hall_elem else ""

                # Fetch detail page
                logging.info(f"Fetching details for: {title} ({event_url})")
                try:
                    detail_html = fetch_html(event_url, ssl_context)
                    detail_soup = BeautifulSoup(detail_html, "html.parser")

                    # Detail container under Back button
                    back = detail_soup.find("a", href="/events")
                    container = back.find_parent("div") if back else detail_soup

                    # Title from detail if better
                    detail_title_elem = container.find("p", class_=re.compile(r"font-bold.*font-erode"))
                    if detail_title_elem and detail_title_elem.get_text(strip=True):
                        title = detail_title_elem.get_text(strip=True)

                    # Hall
                    loc_icon = container.find("i", class_=re.compile(r"location-dot"))
                    detail_hall = loc_icon.find_next("p").get_text(strip=True) if loc_icon and loc_icon.find_next("p") else card_hall

                    # Calendar text
                    cal_icon = container.find("i", class_=re.compile(r"calendar"))
                    cal_text = cal_icon.find_next("p").get_text(strip=True) if cal_icon and cal_icon.find_next("p") else ""

                    # Globe / Website
                    globe_icon = container.find("i", class_=re.compile(r"globe"))
                    globe_link = globe_icon.find_next("a")["href"].strip() if globe_icon and globe_icon.find_next("a") else ""

                    # Instagram
                    insta_icon = container.find("i", class_=re.compile(r"photo-film|instagram"))
                    insta_link = insta_icon.find_next("a")["href"].strip() if insta_icon and insta_icon.find_next("a") else ""

                except Exception as e:
                    logging.warning(f"Failed to fetch/parse detail for {event_url}: {e}")
                    detail_hall = card_hall
                    cal_text = ""
                    globe_link = ""
                    insta_link = ""

                start_date, end_date = parse_dates(badge_text, cal_text)
                domain = clean_domain(globe_link)

                # Format venue name with Hall if available
                hall_clean = detail_hall.strip() if detail_hall else card_hall.strip()
                if hall_clean and hall_clean.lower() != "nice":
                    venue_full = f"{VENUE_NAME} - {hall_clean}"
                else:
                    venue_full = VENUE_NAME

                all_events.append({
                    "s_no": len(all_events) + 1,
                    "event_name": title,
                    "domain": domain,
                    "start_date": start_date,
                    "end_date": end_date,
                    "venue": venue_full,
                    "city": CITY_NAME,
                    "country": COUNTRY_NAME,
                    "website_url": globe_link,
                    "instagram_url": insta_link,
                    "hall": hall_clean,
                    "event_page_url": event_url
                })

        except Exception as e:
            logging.error(f"Error scraping page {page}: {e}")

    # Write output to CSV
    logging.info(f"Writing {len(all_events)} events to {OUTPUT_CSV}")

    # User requested format: s,no, event name, domain, start date, end date, venue, city contry
    fieldnames = [
        "s_no",
        "event_name",
        "domain",
        "start_date",
        "end_date",
        "venue",
        "city",
        "country"
    ]

    with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in all_events:
            writer.writerow(item)

    # Also write comprehensive CSV with extra debug columns (website_url, instagram_url, event_page_url)
    extended_csv = os.path.join(OUTPUT_DIR, "nice_events_detailed.csv")
    extended_fields = [
        "s_no",
        "event_name",
        "domain",
        "website_url",
        "start_date",
        "end_date",
        "venue",
        "hall",
        "city",
        "country",
        "instagram_url",
        "event_page_url"
    ]
    with open(extended_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=extended_fields)
        writer.writeheader()
        for item in all_events:
            writer.writerow(item)

    logging.info("Scraping completed successfully!")
    return all_events

if __name__ == "__main__":
    events = scrape_events()
    print(f"\nSuccessfully scraped {len(events)} events.")
    for ev in events:
        print(f"[{ev['s_no']}] {ev['event_name']} | Domain: {ev['domain']} | {ev['start_date']} to {ev['end_date']} | {ev['venue']}")
