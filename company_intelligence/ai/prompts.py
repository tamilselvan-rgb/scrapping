PAGE_CLASSIFICATION_PROMPT = """
You are an expert page classifier. You will be given a page URL, title, meta description, and the first few paragraphs of text.
Your task is to classify this page into one of the following categories:
- homepage
- about
- products
- services
- solutions
- industries
- technology
- customers
- case studies
- portfolio
- team
- leadership
- careers
- contact
- locations
- partners
- blog
- news
- events
- resources
- documentation
- other

Rules:
- Respond with exactly one of the category names from the list above. No punctuation, no explanation.

Page details:
URL: {url}
Title: {title}
Meta Description: {meta_description}
Headings: {headings}
Snippet: {snippet}
"""

COMPANY_EXTRACTION_PROMPT = """
You are an AI assistant specialized in structured company intelligence.
Your task is to analyze the crawled page contents of a company's website and extract structured information.

IMPORTANT RULES:
1. Do NOT fabricate or hallucinate any information.
2. If a field is not explicitly mentioned or supported by the text, return null (or an empty list).
3. Do NOT guess employee counts or revenue ranges. Only extract if there is concrete evidence in the text.
4. Only extract competitors, customers, or partners if they are explicitly named in the text.
5. All extracted information must be grounded in the text below.

Here is the crawled content from the company's website pages:

{crawled_text}

---

Extract the structured company intelligence matching the required JSON schema.
"""

ENRICHMENT_EXTRACTION_PROMPT = """
You are an AI assistant specialized in structured company intelligence.
Your task is to enrich the existing company profile using the provided external web search results.

IMPORTANT RULES:
1. Do NOT fabricate or hallucinate any information.
2. If a field is not explicitly mentioned in the search results, return null or keep the current value.
3. Compare the search results with the existing values. If you find conflicting information (e.g. different headquarters or employee counts), report them.
4. Ground every single claim in the provided search results.

Existing Company Data:
{existing_data}

Search Results for query "{query}":
{search_results}

---

Extract the enriched company intelligence. Return the fields that were found or updated.
"""
