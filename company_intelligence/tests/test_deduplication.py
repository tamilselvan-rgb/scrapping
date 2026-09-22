import unittest
from utils.deduplication import deduplicate_strings, deduplicate_contacts

class TestDeduplication(unittest.TestCase):
    def test_deduplicate_strings(self):
        items = [
            "Cloud Computing",
            "Cloud Computing Services",
            "Cloud Services",
            "On-premise Services",
            "On-premise"
        ]
        # Cloud Computing Services is more descriptive and should merge similar items
        deduped = deduplicate_strings(items, threshold=0.7)
        self.assertIn("Cloud Computing Services", deduped)
        # Should reduce count
        self.assertTrue(len(deduped) < len(items))

    def test_deduplicate_contacts(self):
        emails = ["info@example.com", "INFO@example.com ", " sales@example.com"]
        self.assertEqual(deduplicate_contacts(emails), ["info@example.com", "sales@example.com"])
        
        phones = ["+1 (123) 456-7890", "1234567890", "+1 123 456 7890"]
        # Standardizing formats should treat duplicates correctly
        deduped_phones = deduplicate_contacts(phones)
        self.assertEqual(len(deduped_phones), 2) # '+1 (123) 456-7890' (since digits are standard 11234567890) and '1234567890' (digits 1234567890)

if __name__ == "__main__":
    unittest.main()
