import json
import os
import logging
from typing import Dict, Any
from models.company import CompanyIntelligenceReport

logger = logging.getLogger("company_intelligence.exporters.json_exporter")

class JsonExporter:
    @staticmethod
    def export(report: CompanyIntelligenceReport, output_dir: str):
        """
        Saves the structured company data to company_data.json inside output_dir.
        """
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "company_data.json")
        
        try:
            # Pydantic dump
            data = report.model_dump()
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
            logger.info(f"JSON saved successfully: {file_path}")
        except Exception as e:
            logger.error(f"Failed to export JSON report: {e}")

    @staticmethod
    def export_crawl_report(stats: Dict[str, Any], output_dir: str):
        """
        Saves crawl-specific metrics and failures to crawl_report.json inside output_dir.
        """
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "crawl_report.json")
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=4, ensure_ascii=False)
                
            logger.info(f"Crawl report saved successfully: {file_path}")
        except Exception as e:
            logger.error(f"Failed to export crawl report: {e}")
