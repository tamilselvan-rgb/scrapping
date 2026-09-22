import unittest
from models.company import CompanyIntelligenceReport, EnrichedField, CrawlMetadata, ContactDetails

class TestSchemas(unittest.TestCase):
    def test_enriched_field_creation(self):
        field = EnrichedField.create("ABC Company", "https://example.com/about", "official_website", 0.99)
        self.assertEqual(field.value, "ABC Company")
        self.assertEqual(field.source, "https://example.com/about")
        self.assertEqual(field.source_type, "official_website")
        self.assertEqual(field.confidence, 0.99)
        self.assertEqual(len(field.values), 1)
        self.assertEqual(field.values[0].value, "ABC Company")
        self.assertIsNone(field.status)

    def test_report_validation(self):
        meta = CrawlMetadata(
            input_url="https://example.com",
            domain="example.com",
            crawl_started="2026-08-27T09:00:00",
            crawl_completed="2026-08-27T09:10:00"
        )
        report = CompanyIntelligenceReport(
            metadata=meta,
            contact_information=ContactDetails(emails=["info@example.com"])
        )
        
        # Verify serialization
        data = report.model_dump()
        self.assertEqual(data["metadata"]["domain"], "example.com")
        self.assertIn("info@example.com", data["contact_information"]["emails"])

if __name__ == "__main__":
    unittest.main()
