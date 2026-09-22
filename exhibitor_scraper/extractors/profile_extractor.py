import re
import json
import logging
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from utils.url_utils import normalize_url, resolve_url, get_domain
from utils.text_utils import clean_text

logger = logging.getLogger("scraper.profile_extractor")

class ProfileExtractor:
    def __init__(self, profile_url: str):
        self.profile_url = profile_url
        self.profile_domain = get_domain(profile_url)

    def extract(self, html_content: str) -> Dict[str, Any]:
        """
        Extracts all metadata and company info from a profile page.
        Returns a dict of standard fields.
        """
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Initialize default blank values
        data = {
            "company_name": "",
            "website": "",
            "website_source": "not_found",
            "website_confidence": "none",
            "website_verification_reason": "",
            "exhibitor_profile_url": self.profile_url,
            "description": "",
            "category": "",
            "industry": "",
            "country": "",
            "city": "",
            "address": "",
            "email": "",
            "phone": "",
            "booth_number": "",
            "hall_number": "",
            "contact_person": "",
            "linkedin": "",
            "facebook": "",
            "instagram": "",
            "other_social_links": [],
            "products": "",
            "brands": "",
            "source_page": self.profile_url
        }

        # 1. Parse JSON-LD schemas
        self._extract_json_ld(soup, data)

        # 2. Extract from standard Meta Tags (og, twitter, name)
        self._extract_meta_tags(soup, data)

        # 3. Parse all links (Emails, Phones, Social handles, Outbound websites)
        self._extract_links(soup, data)

        # 4. Parse labeled fields (text searches)
        self._extract_labeled_fields(soup, data)
        
        # 5. Clean up lists (products, brands) and normalize outputs
        self._post_process(data)
        
        return data

    def _extract_json_ld(self, soup: BeautifulSoup, data: Dict[str, Any]):
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                js_data = json.loads(script.string or '')
                self._parse_schema_object(js_data, data)
            except Exception:
                pass

    def _parse_schema_object(self, obj: Any, data: Dict[str, Any]):
        if isinstance(obj, list):
            for item in obj:
                self._parse_schema_object(item, data)
            return

        if not isinstance(obj, dict):
            return

        # Check types
        schema_type = obj.get('@type', '')
        if isinstance(schema_type, list):
            schema_type = schema_type[0] if schema_type else ''
            
        if schema_type in ('Organization', 'LocalBusiness', 'Exhibitor', 'Corporation', 'Coop'):
            if obj.get('name') and not data['company_name']:
                data['company_name'] = clean_text(obj['name'])
            
            if obj.get('url'):
                url = obj['url']
                if isinstance(url, list):
                    url = url[0]
                # Ensure it's not the exhibitor directory itself
                if get_domain(url) != self.profile_domain:
                    data['website'] = normalize_url(url)
                    data['website_source'] = 'profile_page'
                    data['website_confidence'] = 'high'
                    data['website_verification_reason'] = 'Found in JSON-LD Organization URL field.'
                    
            if obj.get('telephone') and not data['phone']:
                data['phone'] = clean_text(obj['telephone'])
                
            if obj.get('email') and not data['email']:
                email_val = obj['email']
                if isinstance(email_val, list):
                    email_val = email_val[0]
                data['email'] = clean_text(email_val)
                
            # Address parsing
            addr = obj.get('address')
            if isinstance(addr, dict):
                addr_parts = []
                for field in ['streetAddress', 'addressLocality', 'addressRegion', 'postalCode']:
                    if addr.get(field):
                        addr_parts.append(str(addr[field]))
                if addr.get('addressCountry'):
                    data['country'] = clean_text(str(addr['addressCountry']))
                if addr.get('addressLocality'):
                    data['city'] = clean_text(str(addr['addressLocality']))
                if addr_parts and not data['address']:
                    data['address'] = clean_text(", ".join(addr_parts))
            elif isinstance(addr, str) and not data['address']:
                data['address'] = clean_text(addr)
                
            if obj.get('description') and not data['description']:
                data['description'] = clean_text(obj['description'])

        # Recurse fields to find nested info
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                self._parse_schema_object(v, data)

    def _extract_meta_tags(self, soup: BeautifulSoup, data: Dict[str, Any]):
        # Description
        for name in ['description', 'og:description', 'twitter:description']:
            meta = soup.find('meta', attrs={'name': name}) or soup.find('meta', attrs={'property': name})
            if meta and meta.get('content') and not data['description']:
                data['description'] = clean_text(meta['content'])
                break
                
        # Title (fallback for company name if not extracted yet)
        if not data['company_name']:
            for name in ['og:title', 'twitter:title']:
                meta = soup.find('meta', attrs={'name': name}) or soup.find('meta', attrs={'property': name})
                if meta and meta.get('content'):
                    # Often includes separator details like "Company Name | Event"
                    title = meta['content']
                    title = re.split(r'\||-|–|—', title)[0].strip()
                    data['company_name'] = clean_text(title)
                    break
            if not data['company_name'] and soup.title:
                title = soup.title.get_text()
                title = re.split(r'\||-|–|—', title)[0].strip()
                data['company_name'] = clean_text(title)

    def _extract_links(self, soup: BeautifulSoup, data: Dict[str, Any]):
        outbound_links: List[str] = []
        
        # Define social patterns
        fb_pattern = re.compile(r'facebook\.com/[\w\-\.]+', re.IGNORECASE)
        li_pattern = re.compile(r'linkedin\.com/(?:company|in)/[\w\-\.]+', re.IGNORECASE)
        ig_pattern = re.compile(r'instagram\.com/[\w\-\.]+', re.IGNORECASE)
        
        # Social domains blacklist for identifying company website
        ignored_domains = {
            'facebook.com', 'linkedin.com', 'instagram.com', 'twitter.com', 'x.com',
            'youtube.com', 'pinterest.com', 'google.com', 'apple.com', 'microsoft.com',
            'line.me', 'whatsapp.com', 'tiktok.com', 'vimeo.com', 'skype.com', 'weibo.com',
            self.profile_domain
        }

        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not href:
                continue
                
            # Email links
            if href.lower().startswith('mailto:'):
                email = href[7:].split('?')[0].strip()
                if email and not data['email']:
                    data['email'] = email
                continue
                
            # Phone links
            if href.lower().startswith('tel:'):
                phone = href[4:].split('?')[0].strip()
                if phone and not data['phone']:
                    data['phone'] = phone
                continue
                
            if href.startswith(('#', 'javascript:')):
                continue

            resolved = resolve_url(self.profile_url, href)
            domain = get_domain(resolved)
            
            # Check social matching
            if fb_pattern.search(resolved) and not data['facebook']:
                data['facebook'] = resolved
            elif li_pattern.search(resolved) and not data['linkedin']:
                data['linkedin'] = resolved
            elif ig_pattern.search(resolved) and not data['instagram']:
                data['instagram'] = resolved
            elif any(plat in domain for plat in ['twitter.com', 'x.com', 'youtube.com', 'pinterest.com']):
                if resolved not in data['other_social_links']:
                    data['other_social_links'].append(resolved)
            else:
                # Potential company official website
                if domain and domain not in ignored_domains:
                    # Filter out event registrations, organizers or dynamic internal links
                    # Typically paths like /register, /login, /cart, /ticket are not company websites
                    path = urlparse(resolved).path.lower()
                    if not any(kw in path for kw in ['register', 'login', 'ticket', 'cart', 'checkout', 'sponsor', 'about-us', 'contact-us']):
                        outbound_links.append(resolved)

        # If we have outbound links, pick the most likely candidate (often the first or shortest one)
        if outbound_links and not data['website']:
            # Prioritize links that are simple domain roots (e.g. https://domain.com)
            roots = [l for l in outbound_links if urlparse(l).path in ('', '/')]
            candidate = roots[0] if roots else outbound_links[0]
            data['website'] = normalize_url(candidate)
            data['website_source'] = 'profile_page'
            data['website_confidence'] = 'high'
            data['website_verification_reason'] = 'Outbound link found on the profile page.'

    def _extract_labeled_fields(self, soup: BeautifulSoup, data: Dict[str, Any]):
        """
        Parses text nodes and elements to find values matching labeled patterns.
        E.g. Booth: A12, Stand: Hall 3 - B20, Address: Street Name.
        """
        text_content = soup.get_text(" | ", strip=True)

        # 1. Regex search for booth/stand/stall/hall
        if not data['booth_number']:
            # Search for "booth A12", "stand 12-B", "booth number: A12"
            booth_match = re.search(r'\b(?:booth|stand|stall|booth\s*number)\b\s*:?\s*([a-zA-Z0-9\-\.]+)', text_content, re.IGNORECASE)
            if booth_match:
                data['booth_number'] = booth_match.group(1).strip()
                
        if not data['hall_number']:
            hall_match = re.search(r'\b(?:hall|hall\s*number)\b\s*:?\s*([a-zA-Z0-9\-\.]+)', text_content, re.IGNORECASE)
            if hall_match:
                data['hall_number'] = hall_match.group(1).strip()

        # 2. Iterate through element siblings to find labels like "Address", "Contact Person"
        labels = {
            "address": ["address", "location", "address:"],
            "email": ["email", "e-mail", "email:"],
            "phone": ["phone", "telephone", "tel", "phone:", "contact number"],
            "contact_person": ["contact person", "contact", "representative"],
            "country": ["country", "country:"],
            "city": ["city", "city:"],
            "category": ["category", "categories", "product category"],
            "industry": ["industry", "vertical", "sector"],
            "products": ["products", "product list", "exhibiting products"],
            "brands": ["brands", "represented brands"]
        }

        # Check definition lists, table cells, or strong tags followed by text
        for element in soup.find_all(['td', 'th', 'dt', 'strong', 'span', 'b', 'label']):
            element_text = element.get_text().strip().lower()
            if not element_text:
                continue
                
            for field, label_keywords in labels.items():
                # Skip if already found
                if data[field]:
                    continue
                    
                # Exact match or colon match
                if any(element_text == kw or element_text.startswith(kw + ":") for kw in label_keywords):
                    # Get immediate sibling or parent cell's sibling
                    sibling_val = ""
                    
                    # Try next sibling node
                    sibling = element.next_sibling
                    if sibling and sibling.string:
                        sibling_val = sibling.string.strip()
                        
                    # Try next HTML element sibling
                    if not sibling_val:
                        next_el = element.find_next_sibling()
                        if next_el:
                            sibling_val = next_el.get_text().strip()
                            
                    # If inside a table row (e.g. td representing label, td representing value)
                    if not sibling_val and element.name == 'td':
                        next_td = element.find_next_sibling('td')
                        if next_td:
                            sibling_val = next_td.get_text().strip()
                            
                    # If in definition list (e.g. dt -> dd)
                    if not sibling_val and element.name == 'dt':
                        next_dd = element.find_next_sibling('dd')
                        if next_dd:
                            sibling_val = next_dd.get_text().strip()
                            
                    # Sibling string cleanup
                    if sibling_val:
                        # Strip colons or extra characters at the start
                        sibling_val = re.sub(r'^[:\s\-+]+', '', sibling_val).strip()
                        if sibling_val:
                            # Save to data fields
                            if field == 'products' or field == 'brands':
                                data[field] = sibling_val
                            elif field == 'email':
                                # Verify basic structure
                                if "@" in sibling_val:
                                    data['email'] = sibling_val
                            elif field == 'phone':
                                data['phone'] = sibling_val
                            else:
                                data[field] = clean_text(sibling_val)

    def _post_process(self, data: Dict[str, Any]):
        """
        Final field validations, lists compression, and fallback corrections.
        """
        # Compress other social links list to string
        if isinstance(data['other_social_links'], list):
            data['other_social_links'] = ", ".join(data['other_social_links'])
            
        # Clean email/phone spaces
        if data['email']:
            data['email'] = data['email'].replace(" ", "").strip()
        if data['phone']:
            # Strip spaces, dashes, parentheses but keep digits and + sign
            data['phone'] = re.sub(r'[^\d+]', '', data['phone']).strip()

        # If name is still empty, default to "Unknown Exhibitor"
        if not data['company_name']:
            data['company_name'] = "Unknown Exhibitor"
            
        # If website domain is the event website domain, clear website (internal page error)
        if data['website']:
            web_domain = get_domain(data['website'])
            if web_domain == self.profile_domain:
                data['website'] = ""
                data['website_source'] = "not_found"
                data['website_confidence'] = "none"
                data['website_verification_reason'] = ""
