import sys
import os
import asyncio
from bs4 import BeautifulSoup

# Ensure correct import paths
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.url_utils import normalize_url, resolve_url, get_domain
from utils.text_utils import normalize_company_name, clean_text
from enrichment.website_verifier import WebsiteVerifier
from extractors.list_extractor import ListExtractor
from extractors.profile_extractor import ProfileExtractor

def test_url_utils():
    print("Testing URL Utils...")
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("http://www.google.com/test/?utm_source=feed&ref=abc") == "http://www.google.com/test"
    assert resolve_url("https://myfair.com/exhibitors", "/exhibitor/abc") == "https://myfair.com/exhibitor/abc"
    assert get_domain("https://www.google.com/search") == "google.com"
    print("[OK] URL Utils Passed!")

def test_text_utils():
    print("Testing Text Utils...")
    assert clean_text("  hello   world  \x00") == "hello world"
    assert normalize_company_name("Google Inc.") == "google"
    assert normalize_company_name("Acme Co., Ltd.") == "acme"
    assert normalize_company_name("Software Private Limited") == "software"
    print("[OK] Text Utils Passed!")

def test_website_verifier():
    print("Testing Website Verifier...")
    company = "Alpha BioTech"
    candidates = [
        {"url": "https://www.alphabiotech.com", "title": "Alpha BioTech - Official Website", "snippet": "Welcome to Alpha BioTech homepage. We provide biology solutions."},
        {"url": "https://www.linkedin.com/company/alphabiotech", "title": "Alpha BioTech | LinkedIn", "snippet": "Alpha BioTech LinkedIn profile"},
    ]
    meta = {"country": "USA", "industry": "Biotech"}
    web_url, src, conf, reason = WebsiteVerifier.verify_candidate(company, candidates, meta)
    print(f"Verified Website: {web_url}, Source: {src}, Confidence: {conf}, Reason: {reason}")
    assert web_url == "https://www.alphabiotech.com"
    assert conf == "high"
    print("[OK] Website Verifier Passed!")

def test_extractors():
    print("Testing Profile and List Extractors...")
    mock_list_html = """
    <html>
        <body>
            <div class="exhibitor-card">
                <a href="/exhibitor/abc-company">ABC Company</a>
                <span>Booth: A-12</span>
            </div>
            <div class="exhibitor-card">
                <a href="/exhibitor/xyz-corp">XYZ Corp</a>
                <span>Stand: B-45</span>
            </div>
        </body>
    </html>
    """
    le = ListExtractor("https://event.com/exhibitors")
    discovered = le.extract(mock_list_html)
    print(f"Discovered Exhibitors: {discovered}")
    assert len(discovered) == 2
    assert discovered[0]["exhibitor_profile_url"] == "https://event.com/exhibitor/abc-company"

    mock_profile_html = """
    <html>
        <head>
            <title>ABC Company | My Event</title>
            <meta name="description" content="ABC Company is a leading manufacturer of widgets.">
        </head>
        <body>
            <h1>ABC Company</h1>
            <a href="mailto:info@abccompany.com">Email Us</a>
            <a href="tel:+123456789">Call Us</a>
            <a href="https://www.abccompany.com">Official Website</a>
            <a href="https://www.facebook.com/abccompany">Facebook</a>
            <span>Booth Number: A-12</span>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "ABC Company LLC",
                "telephone": "+123456789",
                "email": "info@abccompany.com",
                "url": "https://www.abccompany.com"
            }
            </script>
        </body>
    </html>
    """
    pe = ProfileExtractor("https://event.com/exhibitor/abc-company")
    profile = pe.extract(mock_profile_html)
    print(f"Parsed Profile: {profile}")
    assert profile["company_name"] == "ABC Company LLC"
    assert profile["email"] == "info@abccompany.com"
    assert profile["phone"] == "+123456789"
    assert profile["website"] == "https://www.abccompany.com"
    assert profile["facebook"] == "https://www.facebook.com/abccompany"
    print("[OK] Extractors Passed!")

def run_tests():
    test_url_utils()
    test_text_utils()
    test_website_verifier()
    test_extractors()
    print("All tests executed successfully!")

if __name__ == "__main__":
    run_tests()
