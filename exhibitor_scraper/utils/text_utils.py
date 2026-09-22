import re

def clean_text(text: str) -> str:
    """
    Cleans general text strings by stripping spaces, removing non-printable characters, 
    and collapsing multiple spaces.
    """
    if not text:
        return ""
    # Strip whitespace and collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    # Remove control characters
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    return text.strip()

def normalize_company_name(name: str) -> str:
    """
    Normalizes a company name for deduplication.
    - Converts to lowercase.
    - Removes punctuation and extra whitespace.
    - Strips common corporate suffixes.
    """
    if not name:
        return ""
        
    cleaned = clean_text(name).lower()
    # Replace punctuation with spaces
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    # Collapse spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Common corporate suffixes regex
    # Match these suffixes at the end of the string (with optional space/word boundary)
    suffixes = [
        r'\bpvt\s+ltd\b',
        r'\bprivate\s+limited\b',
        r'\bltd\b',
        r'\blimited\b',
        r'\bllc\b',
        r'\binc\b',
        r'\bcorporation\b',
        r'\bcorp\b',
        r'\bgmbh\b',
        r'\bsa\b',
        r'\bas\b',
        r'\bco\b',
        r'\bcompany\b'
    ]
    
    # Run the suffix removal multiple times in case of multiple suffixes (e.g. Co., Ltd.)
    for _ in range(2):
        for suffix in suffixes:
            cleaned = re.sub(suffix, '', cleaned).strip()
            
    # Final cleanup of any double spaces left after suffix removal
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned
