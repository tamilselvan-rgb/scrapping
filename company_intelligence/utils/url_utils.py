import re
from urllib.parse import urlparse, urlunparse, urljoin, parse_qsl, urlencode
import tldextract

# File extensions to ignore during crawling
IGNORED_EXTENSIONS = {
    # Images
    "png", "jpg", "jpeg", "gif", "svg", "ico", "webp", "tiff", "bmp",
    # Styles / Scripts
    "css", "js",
    # Documents / Binaries
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "tar", "gz", "rar", "7z", "exe", "dmg", "bin",
    # Audio / Video
    "mp4", "mp3", "mkv", "avi", "mov", "wav", "flv", "wmv", "webm",
    # Fonts
    "woff", "woff2", "ttf", "otf", "eot",
    # RSS / XML feeds
    "xml", "rss", "atom"
}

def get_domain(url: str) -> str:
    """
    Extracts the clean registered domain (e.g. 'example.com' from 'https://sub.example.com/page').
    """
    extracted = tldextract.extract(url)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return ""

def get_full_domain(url: str) -> str:
    """
    Extracts the full hostname (e.g. 'sub.example.com' from 'https://sub.example.com/page').
    """
    parsed = urlparse(url)
    return parsed.netloc.lower()

def is_internal_url(url: str, base_url: str) -> bool:
    """
    Checks if a URL belongs to the same domain as the base URL.
    """
    url_domain = get_domain(url)
    base_domain = get_domain(base_url)
    return url_domain == base_domain if url_domain and base_domain else False

def should_ignore_url(url: str) -> bool:
    """
    Returns True if the URL points to a file type we should ignore (images, css, pdfs, etc.).
    """
    parsed = urlparse(url)
    path = parsed.path.lower()
    
    # Check extension
    for ext in IGNORED_EXTENSIONS:
        if path.endswith(f".{ext}"):
            return True
            
    # Check query params for common file triggers if needed, but extension is usually enough
    return False

def normalize_url(url: str, base_url: str = None) -> str:
    """
    Normalizes a URL by:
    - Resolving relative links against a base URL
    - Converting scheme and domain to lowercase
    - Stripping trailing fragments (#)
    - Filtering out common tracking parameters
    - Normalizing trailing slashes (stripping trailing slash unless it's the root path)
    """
    if base_url:
        url = urljoin(base_url, url)
        
    parsed = urlparse(url)
    
    # 1. Lowercase scheme and netloc
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if not scheme or not netloc:
        return ""
        
    path = parsed.path
    
    # 2. Normalize trailing slashes
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path[:-1]
        
    # 3. Filter query parameters (remove tracking parameters)
    tracking_params = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "gclsrc", "msclkid", "mc_cid", "mc_eid"
    }
    
    query_parts = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query):
            if k.lower() not in tracking_params:
                query_parts.append((k, v))
                
    query = urlencode(query_parts) if query_parts else ""
    
    # Reconstruct url without fragment
    normalized = urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        query,
        "" # Remove fragment
    ))
    
    return normalized
