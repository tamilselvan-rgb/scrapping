import unittest
from utils.url_utils import normalize_url, is_internal_url, should_ignore_url, get_domain

class TestUrlUtils(unittest.TestCase):
    def test_normalize_url(self):
        # Resolve relative URLs
        self.assertEqual(normalize_url("/about", "https://example.com"), "https://example.com/about")
        # Lowercase scheme and domain
        self.assertEqual(normalize_url("HTTP://EXAMPLE.COM/About"), "http://example.com/About")
        # Strip trailing fragments
        self.assertEqual(normalize_url("https://example.com/about#team"), "https://example.com/about")
        # Strip tracking query params
        self.assertEqual(normalize_url("https://example.com/about?utm_source=news&ref=123"), "https://example.com/about?ref=123")
        # Normalize trailing slashes
        self.assertEqual(normalize_url("https://example.com/about/"), "https://example.com/about")
        self.assertEqual(normalize_url("https://example.com/"), "https://example.com")

    def test_get_domain(self):
        self.assertEqual(get_domain("https://sub.example.com/page"), "example.com")
        self.assertEqual(get_domain("https://example.co.uk/page"), "example.co.uk")

    def test_is_internal_url(self):
        self.assertTrue(is_internal_url("https://example.com/about", "https://example.com"))
        self.assertTrue(is_internal_url("https://sub.example.com/page", "https://example.com"))
        self.assertFalse(is_internal_url("https://google.com", "https://example.com"))

    def test_should_ignore_url(self):
        self.assertTrue(should_ignore_url("https://example.com/logo.png"))
        self.assertTrue(should_ignore_url("https://example.com/style.css"))
        self.assertTrue(should_ignore_url("https://example.com/doc.pdf"))
        self.assertFalse(should_ignore_url("https://example.com/about"))

if __name__ == "__main__":
    unittest.main()
