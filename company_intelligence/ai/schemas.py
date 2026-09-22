from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any

class LLMCompanyInfo(BaseModel):
    name: Optional[str] = Field(None, description="The common name of the company.")
    legal_name: Optional[str] = Field(None, description="The legal/corporate name of the company if publicly stated.")
    description: Optional[str] = Field(None, description="A detailed summary of what the company does.")
    industry: Optional[str] = Field(None, description="Main industry category (e.g. Software, Manufacturing).")
    sub_industry: Optional[str] = Field(None, description="Specific niche or sub-industry.")
    founded_year: Optional[int] = Field(None, description="Year the company was founded.")
    company_type: Optional[str] = Field(None, description="Ownership/company type e.g. Private, Public, Non-Profit.")
    headquarters: Optional[str] = Field(None, description="The main office location (City, State, Country).")
    locations: List[str] = Field(default_factory=list, description="Other physical office locations or cities of operation.")
    employee_count: Optional[int] = Field(None, description="Exact or typical employee count if mentioned.")
    company_size: Optional[str] = Field(None, description="Employee count range (e.g. '51-200', '1000+').")
    revenue: Optional[str] = Field(None, description="Publicly stated revenue (e.g. '$10M', '$10M-$50M').")
    parent_company: Optional[str] = Field(None, description="Parent company name, if applicable.")
    subsidiaries: List[str] = Field(default_factory=list, description="Names of subsidiary companies.")

    @model_validator(mode='before')
    @classmethod
    def clean_lists(cls, values: Any) -> Any:
        if isinstance(values, dict):
            for field in ["locations", "subsidiaries"]:
                val = values.get(field)
                if val is None or not isinstance(val, list):
                    values[field] = []
                else:
                    values[field] = [
                        item for item in val 
                        if item is not None and str(item).strip() != "" and str(item).lower() != "string"
                    ]
            
            # Clean integer fields (like founded_year or employee_count) to handle string "N/A" etc.
            for field in ["founded_year", "employee_count"]:
                val = values.get(field)
                if val is not None:
                    if isinstance(val, str):
                        cleaned_str = val.strip().replace(",", "")
                        try:
                            values[field] = int(cleaned_str)
                        except ValueError:
                            values[field] = None
        return values

class LLMProductService(BaseModel):
    name: str
    description: Optional[str] = Field(None, description="Short explanation of what the product/service is.")

class LLMLeadership(BaseModel):
    name: str
    role: str = Field(..., description="Role e.g. CEO, CTO, Founder, VP Sales.")

class LLMCompetitor(BaseModel):
    name: str
    reason: Optional[str] = Field(None, description="Reason they are a competitor or why they were mentioned.")

class LLMStructuredOutput(BaseModel):
    company: LLMCompanyInfo
    products: List[LLMProductService] = Field(default_factory=list, description="Major products offered.")
    services: List[LLMProductService] = Field(default_factory=list, description="Services provided.")
    solutions: List[LLMProductService] = Field(default_factory=list, description="Solutions provided.")
    technologies: List[str] = Field(default_factory=list, description="Specific tools, languages, software, or platforms the company uses/offers.")
    customers: List[str] = Field(default_factory=list, description="Publicly mentioned customers or clients.")
    partners: List[str] = Field(default_factory=list, description="Partners or partners programs mentioned.")
    competitors: List[LLMCompetitor] = Field(default_factory=list, description="Direct competitors of the company supported by crawled or external text.")
    leadership: List[LLMLeadership] = Field(default_factory=list, description="Key team members, founders, executives.")
    certifications: List[str] = Field(default_factory=list, description="Certifications e.g. ISO 27001, SOC 2.")
    awards: List[str] = Field(default_factory=list, description="Awards received by the company.")

    @model_validator(mode='before')
    @classmethod
    def clean_lists(cls, values: Any) -> Any:
        if isinstance(values, dict):
            list_fields = [
                "products", "services", "solutions", "technologies",
                "customers", "partners", "competitors", "leadership",
                "certifications", "awards"
            ]
            for field in list_fields:
                val = values.get(field)
                if val is None or not isinstance(val, list):
                    values[field] = []
                else:
                    cleaned_val = []
                    for item in val:
                        if item is None:
                            continue
                        if isinstance(item, dict):
                            # Filter out dictionary placeholders or empty items
                            if not any(v is not None and str(v).strip() != "" for v in item.values()):
                                continue
                            # If it's leadership/competitors/products, ensure name is not null/placeholder
                            name_val = item.get("name")
                            if name_val is None or str(name_val).strip() == "" or str(name_val).lower() == "string":
                                continue
                        if isinstance(item, str) and (item.strip() == "" or item.lower() == "string"):
                            continue
                        cleaned_val.append(item)
                    values[field] = cleaned_val
        return values
