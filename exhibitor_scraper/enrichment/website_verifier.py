import re
import urllib.parse
from typing import Dict, Any, List, Tuple
from utils.url_utils import get_domain
from utils.text_utils import normalize_company_name

class WebsiteVerifier:
    @staticmethod
    def verify_candidate(
        company_name: str,
        candidates: List[Dict[str, Any]],
        exhibitor_metadata: Dict[str, Any]
    ) -> Tuple[str, str, str, str]:
        """
        Verifies list of candidate websites against company name and exhibitor details.
        Returns: (verified_website, source, confidence, reason)
        """
        if not candidates:
            return "", "not_found", "none", "No candidates found during web search."

        normalized_company = normalize_company_name(company_name)
        if not normalized_company:
            return "", "not_found", "none", "Empty company name for verification."

        # Keep track of scores for each candidate
        scored_candidates = []

        for cand in candidates:
            url = cand["url"]
            title = cand["title"].lower()
            snippet = cand["snippet"].lower()
            
            domain = get_domain(url)
            # Extract domain label (e.g. "google" from "google.com")
            domain_parts = domain.split('.')
            domain_label = domain_parts[0] if len(domain_parts) > 0 else ""
            
            score = 0
            reasons = []

            # 1. Domain Similarity Heuristic
            # Check if domain label contains the company name or vice versa
            normalized_domain_label = re.sub(r'[^a-z0-9]', '', domain_label.lower())
            normalized_company_alphanumeric = re.sub(r'[^a-z0-9]', '', normalized_company)
            
            if normalized_domain_label == normalized_company_alphanumeric:
                score += 50
                reasons.append("Domain name matches company name exactly.")
            elif normalized_domain_label in normalized_company_alphanumeric or normalized_company_alphanumeric in normalized_domain_label:
                score += 30
                reasons.append("Domain name is highly similar to company name.")

            # 2. Company Name in Page Title Heuristic
            # Check if normalized company words appear in the candidate title
            company_words = [w for w in normalized_company.split() if len(w) > 2]
            matched_words = 0
            if company_words:
                for word in company_words:
                    if word in title:
                        matched_words += 1
                
                match_ratio = matched_words / len(company_words)
                if match_ratio == 1.0:
                    score += 30
                    reasons.append("All company name words visible in page title.")
                elif match_ratio >= 0.5:
                    score += 15
                    reasons.append("Part of company name visible in page title.")

            # 3. Company Name in Snippet Heuristic
            if company_words:
                snippet_matched_words = sum(1 for w in company_words if w in snippet)
                if snippet_matched_words / len(company_words) >= 0.5:
                    score += 10
                    reasons.append("Company name mentioned in search snippet.")

            # 4. Location Verification Heuristic
            country = exhibitor_metadata.get("country", "").lower()
            city = exhibitor_metadata.get("city", "").lower()
            if country and (country in snippet or country in title):
                score += 10
                reasons.append("Matching country found in search results.")
            if city and (city in snippet or city in title):
                score += 10
                reasons.append("Matching city found in search results.")

            # 5. Industry Verification Heuristic
            industry = exhibitor_metadata.get("industry", "").lower()
            category = exhibitor_metadata.get("category", "").lower()
            if industry and (industry in snippet or industry in title or industry in url):
                score += 5
                reasons.append("Industry/category tags correlate with candidate site.")
            if category and (category in snippet or category in title or category in url):
                score += 5
                reasons.append("Products/category terms correlate with candidate site.")

            scored_candidates.append({
                "url": url,
                "score": score,
                "reason": "; ".join(reasons)
            })

        # Sort candidates by score descending
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        best_cand = scored_candidates[0]

        # Determine confidence mapping
        best_score = best_cand["score"]
        if best_score >= 60:
            confidence = "high"
        elif best_score >= 35:
            confidence = "medium"
        elif best_score >= 15:
            confidence = "low"
        else:
            confidence = "none"

        # Output resolution
        if confidence in ("high", "medium", "low"):
            return best_cand["url"], "web_search", confidence, best_cand["reason"]
        else:
            return "", "not_found", "none", "No candidate website passed similarity thresholds."
