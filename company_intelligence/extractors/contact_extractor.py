import re
from typing import Dict, List, Set
from urllib.parse import urlparse

# RegEx Patterns
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# A regex that matches common phone formats (e.g. +1 123-456-7890, (123) 456 7890, +91 98765 43210)
# We limit digits to avoid long number strings (like tracking codes or serial numbers)
PHONE_REGEX = re.compile(
    r"(?:\+?[1-9]\d{0,3}[-.\s]*)?\(?\d{2,4}\)?[-.\s]*\d{3,4}[-.\s]*\d{3,4}"
)

SOCIAL_DOMAINS = {
    "linkedin.com": "LinkedIn",
    "facebook.com": "Facebook",
    "twitter.com": "X/Twitter",
    "x.com": "X/Twitter",
    "youtube.com": "YouTube",
    "instagram.com": "Instagram",
    "github.com": "GitHub"
}

class ContactExtractor:
    @staticmethod
    def extract_emails(text: str) -> List[str]:
        """
        Extracts all valid emails from text.
        """
        if not text:
            return []
        emails = EMAIL_REGEX.findall(text)
        # Simple cleanup
        cleaned = []
        for e in emails:
            e_clean = e.strip().strip(".-_")
            # Filter out common false positives
            if e_clean and not e_clean.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
                cleaned.append(e_clean)
        return list(set(cleaned))

    @staticmethod
    def extract_phones(text: str) -> List[str]:
        """
        Extracts valid looking phone numbers from text.
        """
        if not text:
            return []
        
        candidates = PHONE_REGEX.findall(text)
        cleaned = []
        for c in candidates:
            # Strip trailing/leading spaces and punctuation
            c_clean = c.strip("-. ")
            
            # Simple length check on digit count (typically 8 to 15 digits)
            digits = "".join(filter(str.isdigit, c_clean))
            if 8 <= len(digits) <= 15:
                # Avoid fake numbers like '2026-08-27'
                if "-" in c_clean and c_clean.count("-") == 2:
                    parts = c_clean.split("-")
                    if len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2:
                        continue # Date-like structure
                cleaned.append(c_clean)
                
        return list(set(cleaned))

    @staticmethod
    def extract_socials(urls: List[str]) -> Dict[str, str]:
        """
        Filters and groups social media urls from a list of page links.
        Returns a dict of platform_name -> URL.
        """
        social_profiles = {}
        for url in urls:
            parsed = urlparse(url.lower())
            netloc = parsed.netloc
            # Check if domain matches any of the social domains
            for domain, platform in SOCIAL_DOMAINS.items():
                if domain in netloc:
                    # Ignore generic links like sharing links or main domain URLs
                    path = parsed.path
                    if path == "" or path == "/" or "share" in url or "intent" in url:
                        continue
                    
                    # Store the original casing URL
                    social_profiles[platform] = url.strip()
                    break
        return social_profiles
