import logging
import json
import datetime
from typing import List, Dict, Any

from .web_search import WebSearcher
from ai.llm_extractor import LlmExtractor
from models.company import (
    CompanyIntelligenceReport,
    ExternalSource,
    SourceValue,
    EnrichedField,
    ProductServiceItem,
    CompetitorItem,
    LeadershipItem,
    CustomerItem,
    PartnerItem,
    AwardItem,
    CertificationItem
)

logger = logging.getLogger("company_intelligence.enrichment.company_enrichment")

class CompanyEnricher:
    def __init__(self, searcher: WebSearcher, llm_extractor: LlmExtractor):
        self.searcher = searcher
        self.llm = llm_extractor

    def _get_flat_company_json(self, report: CompanyIntelligenceReport) -> str:
        flat = {}
        for name, field in report.company:
            if hasattr(field, "value"):
                flat[name] = field.value
            else:
                flat[name] = field
        return json.dumps(flat, indent=2)

    async def enrich(self, report: CompanyIntelligenceReport) -> CompanyIntelligenceReport:
        """
        Performs web search queries to enrich the crawled company data,
        runs LLM processing to structure the search snippet information, and merging.
        """
        if not self.llm.is_active():
            logger.warning("LLM is not active. Skipping external data enrichment.")
            return report
            
        company_name = report.company.name.value
        if not company_name:
            # Try to get domain if name is not set
            company_name = report.metadata.domain
            
        logger.info(f"Starting external data enrichment for: {company_name}")
        
        # 1. Plan queries
        queries = [
            f"{company_name} company overview industry headquarters",
            f"{company_name} employees count revenue funding",
            f"{company_name} founders CEO leadership team",
            f"{company_name} LinkedIn official page"
        ]
        
        compiled_results = []
        
        for query in queries:
            try:
                results = await self.searcher.search(query, num_results=4)
                
                # Format search results for LLM
                snippet_text = ""
                for idx, r in enumerate(results):
                    snippet_text += f"[{idx+1}] Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}\n\n"
                    
                    # Store external sources in the report metadata
                    report.external_sources.append(ExternalSource(
                        query=query,
                        url=r['url'],
                        title=r['title'],
                        snippet=r['snippet'],
                        scraped_at=datetime.datetime.now().isoformat()
                    ))
                
                if snippet_text.strip():
                    compiled_results.append((query, snippet_text))
            except Exception as e:
                logger.error(f"Error executing search query '{query}': {e}")
                
        # 2. Extract information using LLM for each search outcome
        existing_company_json = self._get_flat_company_json(report)
        
        for query, results_text in compiled_results:
            try:
                logger.info(f"Extracting company details from search results of: '{query}'")
                llm_output = await self.llm.enrich_company_data(
                    existing_data_json=existing_company_json,
                    query=query,
                    search_results=results_text
                )
                
                if llm_output:
                    # Update existing_company_json so the next iteration has latest context
                    self._merge_llm_data(report, llm_output, source_url=f"Search Query: {query}")
                    existing_company_json = self._get_flat_company_json(report)
            except Exception as e:
                logger.error(f"Failed to extract structured data from search: {e}")
                
        logger.info("External data enrichment completed.")
        return report

    def _merge_llm_data(self, report: CompanyIntelligenceReport, llm_data: Any, source_url: str):
        """
        Helper to merge fields extracted from external searches into the main CompanyIntelligenceReport.
        Maintains source tracking and conflict states.
        """
        # Merge company fields
        company_fields = [
            "name", "legal_name", "description", "industry", "sub_industry",
            "founded_year", "company_type", "headquarters", "employee_count",
            "company_size", "revenue", "parent_company"
        ]
        
        llm_co = llm_data.company
        for field in company_fields:
            val = getattr(llm_co, field, None)
            if val is not None:
                # Update the EnrichedField
                current_enriched = getattr(report.company, field)
                self._update_enriched_field(current_enriched, val, source_url, "external")
                
        # Merge list fields: locations, subsidiaries
        if llm_co.locations:
            self._update_enriched_field(report.company.locations, llm_co.locations, source_url, "external")
        if llm_co.subsidiaries:
            self._update_enriched_field(report.company.subsidiaries, llm_co.subsidiaries, source_url, "external")

        # Merge other lists (products, services, solutions, etc.)
        for item in llm_data.products:
            report.products.append(ProductServiceItem(
                name=item.name,
                description=item.description,
                source=source_url,
                confidence=0.8
            ))
            
        for item in llm_data.services:
            report.services.append(ProductServiceItem(
                name=item.name,
                description=item.description,
                source=source_url,
                confidence=0.8
            ))

        for item in llm_data.solutions:
            report.solutions.append(ProductServiceItem(
                name=item.name,
                description=item.description,
                source=source_url,
                confidence=0.8
            ))

        for tech in llm_data.technologies:
            if tech not in report.technologies:
                report.technologies.append(tech)

        for cust in llm_data.customers:
            report.customers.append(CustomerItem(name=cust, source=source_url, confidence=0.8))

        for partner in llm_data.partners:
            report.partners.append(PartnerItem(name=partner, source=source_url, confidence=0.8))

        for comp in llm_data.competitors:
            report.competitors.append(CompetitorItem(name=comp.name, reason=comp.reason, source=source_url, confidence=0.8))

        for lead in llm_data.leadership:
            report.leadership.append(LeadershipItem(name=lead.name, role=lead.role, source=source_url, confidence=0.8))

        for cert in llm_data.certifications:
            report.certifications.append(CertificationItem(name=cert, source=source_url, confidence=0.8))

        for award in llm_data.awards:
            report.awards.append(AwardItem(name=award, source=source_url, confidence=0.8))

    def _update_enriched_field(self, enriched: EnrichedField, value: Any, source: str, source_type: str):
        """
        Updates an EnrichedField, resolving duplicate sources and checking for conflicts.
        """
        # If no values yet
        new_source_val = SourceValue(value=value, source=source, source_type=source_type, confidence=0.8)
        
        if not enriched.values:
            enriched.value = value
            enriched.source = source
            enriched.source_type = source_type
            enriched.confidence = 0.8
            enriched.values = [new_source_val]
            return
            
        # Check if this exact source value already exists
        for sv in enriched.values:
            if sv.value == value:
                # Update confidence/source if needed
                return
                
        # If a different value is found, we have a conflict!
        # We append it to the values list and update the status to conflicting_sources
        enriched.values.append(new_source_val)
        
        # If there are multiple values, determine if they are conflicting
        unique_values = {str(sv.value).lower().strip() for sv in enriched.values}
        if len(unique_values) > 1:
            enriched.status = "conflicting_sources"
            # Sort values by confidence, then by length or specificity
            # Keep the primary value as the highest confidence one
            sorted_svs = sorted(enriched.values, key=lambda x: x.confidence, reverse=True)
            enriched.value = sorted_svs[0].value
            enriched.source = sorted_svs[0].source
            enriched.source_type = sorted_svs[0].source_type
            enriched.confidence = sorted_svs[0].confidence
        else:
            # Values are equivalent text-wise, no conflict
            enriched.status = None
