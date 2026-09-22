from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Generic, TypeVar

T = TypeVar('T')

class SourceValue(BaseModel, Generic[T]):
    value: T
    source: str
    source_type: str  # 'official_website', 'external', 'inferred'
    confidence: float

class EnrichedField(BaseModel, Generic[T]):
    value: Optional[T] = None
    source: Optional[str] = None
    source_type: Optional[str] = None
    confidence: Optional[float] = None
    
    # Conflict tracking
    values: List[SourceValue[T]] = Field(default_factory=list)
    status: Optional[str] = None  # None, 'resolved', 'conflicting_sources'

    @classmethod
    def create(cls, value: T, source: str, source_type: str = "official_website", confidence: float = 0.9) -> "EnrichedField[T]":
        return cls(
            value=value,
            source=source,
            source_type=source_type,
            confidence=confidence,
            values=[SourceValue(value=value, source=source, source_type=source_type, confidence=confidence)]
        )

# Sub-models for structured items with source tracking
class ProductServiceItem(BaseModel):
    name: str
    description: Optional[str] = None
    source: str
    confidence: float = 0.9

class CompetitorItem(BaseModel):
    name: str
    reason: Optional[str] = None
    source: str
    confidence: float = 0.8

class LeadershipItem(BaseModel):
    name: str
    role: str  # 'CEO', 'CTO', 'Founder', etc.
    source: str
    confidence: float = 0.9

class CustomerItem(BaseModel):
    name: str
    source: str
    confidence: float = 0.9

class CaseStudyItem(BaseModel):
    title: str
    url: Optional[str] = None
    description: Optional[str] = None
    source: str
    confidence: float = 0.9

class PartnerItem(BaseModel):
    name: str
    type: Optional[str] = None # e.g. 'technology', 'channel'
    source: str
    confidence: float = 0.9

class AwardItem(BaseModel):
    name: str
    year: Optional[str] = None
    source: str
    confidence: float = 0.9

class CertificationItem(BaseModel):
    name: str
    source: str
    confidence: float = 0.9

class NewsEventItem(BaseModel):
    title: str
    date: Optional[str] = None
    url: Optional[str] = None
    source: str
    confidence: float = 0.8

# Core Metadata
class CrawlMetadata(BaseModel):
    input_url: str
    domain: str
    crawl_started: str
    crawl_completed: str
    pages_discovered: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0

# Contact Information
class ContactDetails(BaseModel):
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    addresses: List[str] = Field(default_factory=list)

# Page Level storage
class PageData(BaseModel):
    url: str
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    page_type: str = "other"  # homepage, about, products, blog, contact, etc.
    content: str = ""
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    links: List[str] = Field(default_factory=list)

# Enrichment source
class ExternalSource(BaseModel):
    query: str
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    scraped_at: str

# Combined Company Model
class CompanyModel(BaseModel):
    name: EnrichedField[str] = Field(default_factory=EnrichedField)
    legal_name: EnrichedField[str] = Field(default_factory=EnrichedField)
    description: EnrichedField[str] = Field(default_factory=EnrichedField)
    industry: EnrichedField[str] = Field(default_factory=EnrichedField)
    sub_industry: EnrichedField[str] = Field(default_factory=EnrichedField)
    founded_year: EnrichedField[int] = Field(default_factory=EnrichedField)
    company_type: EnrichedField[str] = Field(default_factory=EnrichedField) # 'Public', 'Private', etc.
    headquarters: EnrichedField[str] = Field(default_factory=EnrichedField)
    locations: EnrichedField[List[str]] = Field(default_factory=EnrichedField)
    employee_count: EnrichedField[int] = Field(default_factory=EnrichedField)
    company_size: EnrichedField[str] = Field(default_factory=EnrichedField) # '50-200', '1000+', etc.
    revenue: EnrichedField[str] = Field(default_factory=EnrichedField) # String to support range e.g. '$10M-$50M'
    parent_company: EnrichedField[str] = Field(default_factory=EnrichedField)
    subsidiaries: EnrichedField[List[str]] = Field(default_factory=EnrichedField)

# Total Intelligence Output Report
class CompanyIntelligenceReport(BaseModel):
    metadata: CrawlMetadata
    company: CompanyModel = Field(default_factory=CompanyModel)
    products: List[ProductServiceItem] = Field(default_factory=list)
    services: List[ProductServiceItem] = Field(default_factory=list)
    solutions: List[ProductServiceItem] = Field(default_factory=list)
    industries_served: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    customers: List[CustomerItem] = Field(default_factory=list)
    case_studies: List[CaseStudyItem] = Field(default_factory=list)
    partners: List[PartnerItem] = Field(default_factory=list)
    competitors: List[CompetitorItem] = Field(default_factory=list)
    leadership: List[LeadershipItem] = Field(default_factory=list)
    contact_information: ContactDetails = Field(default_factory=ContactDetails)
    social_media: Dict[str, str] = Field(default_factory=dict) # platform -> url
    news: List[NewsEventItem] = Field(default_factory=list)
    events: List[NewsEventItem] = Field(default_factory=list)
    certifications: List[CertificationItem] = Field(default_factory=list)
    awards: List[AwardItem] = Field(default_factory=list)
    
    # Raw pages crawled logs
    pages: List[PageData] = Field(default_factory=list)
    external_sources: List[ExternalSource] = Field(default_factory=list)
    
    # Qualification and summary
    icp: Dict[str, Any] = Field(default_factory=dict)
    confidence_summary: Dict[str, float] = Field(default_factory=dict)
