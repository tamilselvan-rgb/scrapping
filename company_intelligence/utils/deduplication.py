import difflib
from typing import List

def clean_string(s: str) -> str:
    """
    Cleans a string for uniform comparison.
    """
    if not s:
        return ""
    # Lowercase, strip whitespace, remove extra inner whitespace
    return " ".join(s.lower().strip().split())

def string_similarity(s1: str, s2: str) -> float:
    """
    Returns the similarity ratio between two strings.
    """
    c1 = clean_string(s1)
    c2 = clean_string(s2)
    if not c1 or not c2:
        return 0.0
    return difflib.SequenceMatcher(None, c1, c2).ratio()

def deduplicate_strings(items: List[str], threshold: float = 0.75) -> List[str]:
    """
    Deduplicates a list of strings using fuzzy similarity matching.
    When two strings are similar, the longer/more informative one is kept.
    """
    if not items:
        return []
        
    # Unique, stripped, non-empty items
    unique_items = sorted(list({i.strip() for i in items if i and i.strip()}), key=len, reverse=True)
    
    deduplicated = []
    for item in unique_items:
        # Check if this item is highly similar to any item we've already kept
        is_duplicate = False
        for kept in deduplicated:
            # If they are very similar, or one is a substring of the other (for short words, check ratio)
            if string_similarity(item, kept) >= threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            deduplicated.append(item)
            
    return sorted(deduplicated)

def deduplicate_contacts(contacts: List[str]) -> List[str]:
    """
    Performs exact deduplication for emails, phone numbers, and URLs (ignoring spaces/case).
    """
    seen = set()
    deduped = []
    for c in contacts:
        if not c:
            continue
        cleaned = c.strip().lower()
        # For phone numbers, remove common formatting characters for comparison
        if "@" not in cleaned: # Likely a phone number
            cleaned = "".join(filter(str.isdigit, cleaned))
            
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            deduped.append(c.strip())
    return deduped
