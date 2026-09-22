import logging
import re
from typing import Dict, Any, List, Optional
from models.company import CompanyIntelligenceReport, EnrichedField

logger = logging.getLogger("company_intelligence.qualification.icp")

class IcpEvaluator:
    def __init__(self, criteria: Dict[str, Any]):
        """
        Initializes the ICP Evaluator with target criteria.
        Example criteria:
        {
            "industries": ["manufacturing", "software", "technology"],
            "locations": ["maharashtra", "india", "california", "us"],
            "min_employees": 50,
            "max_employees": 250,
            "technologies": ["react", "aws", "salesforce"]
        }
        """
        self.target_industries = [i.lower() for i in criteria.get("industries", [])]
        self.target_locations = [l.lower() for l in criteria.get("locations", [])]
        self.min_employees = criteria.get("min_employees")
        self.max_employees = criteria.get("max_employees")
        self.target_technologies = [t.lower() for t in criteria.get("technologies", [])]

    def _parse_int(self, val: Any) -> Optional[int]:
        if val is None:
            return None
        if isinstance(val, int):
            return val
        digits = "".join(filter(str.isdigit, str(val)))
        if digits:
            return int(digits)
        return None

    def evaluate(self, report: CompanyIntelligenceReport) -> Dict[str, Any]:
        """
        Evaluates the CompanyIntelligenceReport against target ICP criteria.
        Calculates scores, matches, and logs detailed reasoning.
        """
        co = report.company
        
        matches = {
            "industry": False,
            "location": False,
            "employee_size": False,
            "technology": False
        }
        
        reasoning = []
        scores = [] # We append scores for matched criteria to calculate avg
        
        # 1. Evaluate Industry
        ind_val = co.industry.value
        if self.target_industries:
            if ind_val:
                ind_lower = ind_val.lower()
                matched = any(i in ind_lower for i in self.target_industries)
                matches["industry"] = matched
                source_lbl = "verified" if co.industry.source_type == "official_website" else "inferred"
                
                if matched:
                    reasoning.append(f"Company operates in matching industry '{ind_val}' ({source_lbl}).")
                    scores.append(100)
                else:
                    reasoning.append(f"Company industry '{ind_val}' ({source_lbl}) does not match targets {self.target_industries}.")
                    scores.append(0)
            else:
                reasoning.append("No industry information found to evaluate.")
                scores.append(0)

        # 2. Evaluate Location / Geography
        hq_val = co.headquarters.value
        all_locations = [hq_val] if hq_val else []
        if co.locations.value:
            all_locations.extend(co.locations.value)
            
        if self.target_locations:
            matched_locs = []
            source_lbls = set()
            
            for loc in all_locations:
                loc_lower = loc.lower()
                for target in self.target_locations:
                    if target in loc_lower:
                        matched_locs.append(loc)
                        # Determine source type
                        is_hq_official = (loc == hq_val and co.headquarters.source_type == "official_website")
                        is_locs_official = (loc in (co.locations.value or []) and co.locations.source_type == "official_website")
                        if is_hq_official or is_locs_official:
                            source_lbls.add("verified")
                        else:
                            source_lbls.add("inferred")
                            
            if matched_locs:
                matches["location"] = True
                lbl = " / ".join(source_lbls)
                reasoning.append(f"Company has matching operations in {', '.join(set(matched_locs))} ({lbl}).")
                scores.append(100)
            else:
                matches["location"] = False
                reasoning.append(f"Company locations {all_locations} do not match targets {self.target_locations}.")
                scores.append(0)

        # 3. Evaluate Employee Size
        emp_val = co.employee_count.value
        emp_range = co.company_size.value
        
        # Try to parse exact count or range limits
        exact_count = self._parse_int(emp_val)
        
        if self.min_employees is not None or self.max_employees is not None:
            source_lbl = "verified" if co.employee_count.source_type == "official_website" or co.company_size.source_type == "official_website" else "inferred"
            
            matched = False
            eval_lbl = ""
            
            if exact_count is not None:
                eval_lbl = f"{exact_count} employees"
                min_ok = self.min_employees is None or exact_count >= self.min_employees
                max_ok = self.max_employees is None or exact_count <= self.max_employees
                matched = min_ok and max_ok
            elif emp_range:
                # If we only have range (e.g. '50-200')
                eval_lbl = f"range '{emp_range}'"
                # Extract all numbers from range
                nums = [int(n) for n in re.findall(r"\d+", emp_range)]
                if nums:
                    range_min = min(nums)
                    range_max = max(nums)
                    # Check overlap with target range
                    min_ok = self.min_employees is None or range_max >= self.min_employees
                    max_ok = self.max_employees is None or range_min <= self.max_employees
                    matched = min_ok and max_ok
                    
            if matched:
                matches["employee_size"] = True
                reasoning.append(f"Company employee size {eval_lbl} satisfies criteria ({source_lbl}).")
                scores.append(100)
            else:
                matches["employee_size"] = False
                reasoning.append(f"Company employee size {eval_lbl or 'unknown'} does not satisfy targets ({source_lbl}).")
                scores.append(0)

        # 4. Evaluate Technologies
        if self.target_technologies:
            company_techs = [t.lower() for t in report.technologies]
            matched_techs = []
            for t in self.target_technologies:
                if any(t in ct for ct in company_techs):
                    matched_techs.append(t)
                    
            if matched_techs:
                matches["technology"] = True
                reasoning.append(f"Company uses matching technologies: {', '.join(matched_techs)} (inferred from site/web content).")
                scores.append(100)
            else:
                matches["technology"] = False
                reasoning.append("No target technologies detected in company profile.")
                scores.append(0)

        # Calculate score
        final_score = int(sum(scores) / len(scores)) if scores else 100
        icp_match = all(v for k, v in matches.items() if (k == "industry" and self.target_industries) or \
                                                           (k == "location" and self.target_locations) or \
                                                           (k == "employee_size" and (self.min_employees or self.max_employees)))
        
        eval_result = {
            "icp_match": icp_match,
            "score": final_score,
            "criteria": matches,
            "reasoning": reasoning
        }
        
        report.icp = eval_result
        return eval_result
