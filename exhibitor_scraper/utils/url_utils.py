import urllib.parse
import re

def normalize_url(url: str) -> str:
    """
    Normalizes a URL to a standard format.
    - Strips leading/trailing spaces.
    - Adds scheme 'https://' if missing.
    - Standardizes the hostname.
    - Cleans typical tracking query parameters.
    """
    if not url:
        return ""
    
    url = url.strip()
    
    # If the URL starts with //, prepend https:
    if url.startswith("//"):
        url = "https:" + url
    # If there is no protocol specifier, prepend https://
    elif not re.match(r'^[a-zA-Z]+://', url):
        url = "https://" + url
        
    try:
        parsed = urllib.parse.urlparse(url)
        # Reconstruct without standard UTM parameters or typical tracking params
        query_params = urllib.parse.parse_qsl(parsed.query)
        cleaned_params = [
            (k, v) for k, v in query_params 
            if not k.lower().startswith('utm_') 
            and k.lower() not in {'gclid', 'fbclid', 'ref', 'source'}
        ]
        
        new_query = urllib.parse.urlencode(cleaned_params)
        
        # Clean port if standard
        netloc = parsed.netloc
        if parsed.port:
            if (parsed.scheme == 'http' and parsed.port == 80) or (parsed.scheme == 'https' and parsed.port == 443):
                netloc = parsed.hostname or ""
        
        normalized = urllib.parse.urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            new_query,
            '' # Fragment is usually stripped for deduplication
        ))
        
        # Strip trailing slash for consistency unless it's just the domain
        if normalized.endswith('/') and parsed.path == '/':
            pass
        elif normalized.endswith('/'):
            normalized = normalized[:-1]
            
        return normalized
    except Exception:
        return url

def resolve_url(base_url: str, relative_url: str) -> str:
    """
    Resolves a relative URL against a base URL.
    Returns the resolved normalized URL.
    """
    if not relative_url:
        return ""
    
    # If the relative_url starts with javascript: or mailto:, return as is
    if relative_url.strip().lower().startswith(('javascript:', 'mailto:', 'tel:')):
        return relative_url.strip()
        
    resolved = urllib.parse.urljoin(base_url, relative_url)
    return normalize_url(resolved)

def get_domain(url: str) -> str:
    """
    Extracts the main domain (e.g. example.com) from a URL.
    """
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(normalize_url(url))
        hostname = parsed.hostname or ""
        # Remove www.
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return ""
