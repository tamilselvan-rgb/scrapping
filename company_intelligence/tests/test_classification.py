import unittest
from extractors.page_extractor import PageExtractor

class TestClassification(unittest.TestCase):
    def setUp(self):
        self.extractor = PageExtractor("https://example.com")

    def test_classify_page_type(self):
        # Homepage
        self.assertEqual(self.extractor.classify_page_type("https://example.com", "Home", "Welcome to our website"), "homepage")
        self.assertEqual(self.extractor.classify_page_type("https://example.com/", "", ""), "homepage")
        
        # Contact
        self.assertEqual(self.extractor.classify_page_type("https://example.com/contact-us", "Contact Us", "Get in touch with our team"), "contact")
        
        # About
        self.assertEqual(self.extractor.classify_page_type("https://example.com/company/about", "About Us", "We are a company specializing in tech"), "about")
        
        # Careers
        self.assertEqual(self.extractor.classify_page_type("https://example.com/careers/jobs", "Careers", "Work at our company"), "careers")
        
        # Team
        self.assertEqual(self.extractor.classify_page_type("https://example.com/team", "Our Leadership Team", "Meet our founders and directors"), "leadership")

if __name__ == "__main__":
    unittest.main()
