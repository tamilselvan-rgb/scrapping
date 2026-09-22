import logging
from typing import Dict
from models.company import CompanyIntelligenceReport, EnrichedField

logger = logging.getLogger("company_intelligence.enrichment.source_validator")

class SourceValidator:
    @staticmethod
    def calculate_confidence(report: CompanyIntelligenceReport) -> Dict[str, float]:
        """
        Calculates a data quality / confidence score (from 0.0 to 1.0) for different sections
        of the company profile, and a total average confidence score.
        """
        co = report.company
        
        # 1. Company Core Info Section
        core_fields = [
            co.name, co.legal_name, co.description, co.industry, co.sub_industry,
            co.founded_year, co.company_type, co.headquarters, co.employee_count,
            co.company_size, co.revenue
        ]
        
        core_score = 0.0
        filled_core = 0
        for field in core_fields:
            if field.value is not None:
                # If there are conflicts, reduce confidence
                conf = field.confidence or 0.5
                if field.status == "conflicting_sources":
                    conf *= 0.7 # Apply penalty
                core_score += conf
                filled_core += 1
                
        core_confidence = core_score / len(core_fields) if len(core_fields) > 0 else 0.0
        
        # 2. Offerings Section (Products, Services, Solutions)
        offering_confidence = 0.0
        total_offerings = len(report.products) + len(report.services) + len(report.solutions)
        if total_offerings > 0:
            # Average confidence of offerings
            sum_conf = sum(p.confidence for p in report.products) + \
                       sum(s.confidence for s in report.services) + \
                       sum(sol.confidence for sol in report.solutions)
            offering_confidence = sum_conf / total_offerings
        elif co.description.value:
            offering_confidence = 0.5 # Neutral if description exists but lists are empty
            
        # 3. Contacts Section
        contacts = report.contact_information
        contact_confidence = 0.0
        contact_points = 0
        if contacts.emails:
            contact_points += 1
        if contacts.phones:
            contact_points += 1
        if contacts.addresses:
            contact_points += 1
        if report.social_media:
            contact_points += 1
            
        contact_confidence = contact_points / 4.0
        
        # 4. Market & People (Customers, Partners, Competitors, Leadership)
        rel_confidence = 0.0
        rel_items = len(report.customers) + len(report.partners) + len(report.competitors) + len(report.leadership)
        if rel_items > 0:
            sum_rel_conf = sum(c.confidence for c in report.customers) + \
                           sum(p.confidence for p in report.partners) + \
                           sum(comp.confidence for comp in report.competitors) + \
                           sum(l.confidence for l in report.leadership)
            rel_confidence = sum_rel_conf / rel_items
        elif core_confidence > 0.5:
            rel_confidence = 0.4
            
        # Overall Score
        overall = (core_confidence * 0.4) + (offering_confidence * 0.25) + (contact_confidence * 0.20) + (rel_confidence * 0.15)
        
        confidence_summary = {
            "company_core_info": round(core_confidence, 2),
            "products_and_services": round(offering_confidence, 2),
            "contact_information": round(contact_confidence, 2),
            "relationships_and_market": round(rel_confidence, 2),
            "overall_data_quality": round(overall, 2)
        }
        
        report.confidence_summary = confidence_summary
        logger.info(f"Calculated profile confidence: {confidence_summary}")
        return confidence_summary
