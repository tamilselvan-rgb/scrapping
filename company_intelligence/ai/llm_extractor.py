import os
import json
import logging
import re
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from .schemas import LLMStructuredOutput
from .prompts import PAGE_CLASSIFICATION_PROMPT, COMPANY_EXTRACTION_PROMPT, ENRICHMENT_EXTRACTION_PROMPT

logger = logging.getLogger("company_intelligence.ai.llm_extractor")

T = TypeVar('T', bound=BaseModel)

class LlmExtractor:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        self.model_name = os.getenv("LLM_MODEL", "gemini-1.5-flash")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.base_url = os.getenv("LLM_BASE_URL", "")
        
        # Handle Ollama provider shortcut
        if self.provider == "ollama":
            self.provider = "openai"
            if not self.base_url:
                self.base_url = "http://localhost:11434/v1"
            if not self.api_key:
                self.api_key = "ollama"  # Ollama requires a dummy non-empty key
            if self.model_name == "gemini-1.5-flash":
                self.model_name = "llama3"  # Default local model name
        
        if not self.api_key:
            logger.warning("LLM_API_KEY environment variable is empty. LLM extraction will be disabled/skipped.")
            
        self.gemini_client = None
        self.openai_client = None
        
        if self.api_key:
            if self.provider == "gemini":
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=self.api_key)
                    self.gemini_client = genai.GenerativeModel(self.model_name)
                    logger.info(f"Gemini client initialized with model: {self.model_name}")
                except Exception as e:
                    logger.error(f"Failed to initialize Gemini client: {e}")
            elif self.provider == "openai":
                try:
                    from openai import AsyncOpenAI
                    client_args = {"api_key": self.api_key}
                    if self.base_url:
                        client_args["base_url"] = self.base_url
                    self.openai_client = AsyncOpenAI(**client_args)
                    logger.info(f"OpenAI/Ollama client initialized at {self.base_url or 'default base'} with model: {self.model_name}")
                except Exception as e:
                    logger.error(f"Failed to initialize OpenAI/Ollama client: {e}")
            else:
                logger.error(f"Unsupported LLM provider: {self.provider}")

    def is_active(self) -> bool:
        return (self.provider == "gemini" and self.gemini_client is not None) or \
               (self.provider == "openai" and self.openai_client is not None)

    async def _call_llm(self, prompt: str, system_instruction: str = None) -> str:
        """
        Helper method to call the configured LLM provider asynchronously.
        """
        if not self.is_active():
            raise ValueError("LLM Client is not initialized or API key is missing.")
            
        if self.provider == "gemini":
            # Set system instruction if provided
            config = {}
            if system_instruction:
                # In newer google-generativeai versions, system_instruction can be passed in GenerativeModel init or generation_config.
                # To be compatible across versions, we can prepend it to prompt or set it in configuration if supported.
                import google.generativeai as genai
                # We can configure system instructions dynamically using a new model instance if needed, or prepend.
                # Let's check:
                try:
                    model = genai.GenerativeModel(
                        model_name=self.model_name,
                        system_instruction=system_instruction
                    )
                    response = await model.generate_content_async(prompt)
                except Exception:
                    # Fallback for older SDKs: prepend system instruction to prompt
                    model = self.gemini_client
                    full_prompt = f"{system_instruction}\n\n{prompt}"
                    response = await model.generate_content_async(full_prompt)
            else:
                response = await self.gemini_client.generate_content_async(prompt)
            return response.text
            
        elif self.provider == "openai":
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})
            
            response = await self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                response_format={"type": "json_object"} if "json" in prompt.lower() else None
            )
            return response.choices[0].message.content or ""
            
        return ""

    def _parse_json_block(self, text: str) -> dict:
        """
        Extracts and parses JSON from markdown code blocks or raw text.
        """
        cleaned = text.strip()
        # Find markdown code blocks ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            # Try to find first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                cleaned = cleaned[start:end+1]
                
        return json.loads(cleaned)

    def _get_simplified_schema(self) -> str:
        """
        Returns a simplified JSON template instead of raw JSON schema (which includes
        complex $defs references that often confuse smaller local models like Llama 3).
        """
        example_json = {
            "company": {
                "name": "string or null",
                "legal_name": "string or null",
                "description": "string or null",
                "industry": "string or null",
                "sub_industry": "string or null",
                "founded_year": "integer or null",
                "company_type": "string or null",
                "headquarters": "string or null",
                "locations": ["string"],
                "employee_count": "integer or null",
                "company_size": "string or null",
                "revenue": "string or null",
                "parent_company": "string or null",
                "subsidiaries": ["string"]
            },
            "products": [{"name": "string", "description": "string or null"}],
            "services": [{"name": "string", "description": "string or null"}],
            "solutions": [{"name": "string", "description": "string or null"}],
            "technologies": ["string"],
            "customers": ["string"],
            "partners": ["string"],
            "competitors": [{"name": "string", "reason": "string or null"}],
            "leadership": [{"name": "string", "role": "string"}],
            "certifications": ["string"],
            "awards": ["string"]
        }
        return json.dumps(example_json, indent=2)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def classify_page(self, url: str, title: str, meta_description: str, headings: list, snippet: str) -> str:
        """
        Classifies a page into a category based on URL, title, meta tag, and content.
        """
        if not self.is_active():
            return "other"
            
        prompt = PAGE_CLASSIFICATION_PROMPT.format(
            url=url,
            title=title or "N/A",
            meta_description=meta_description or "N/A",
            headings=", ".join(headings[:5]) if headings else "N/A",
            snippet=snippet[:500] if snippet else "N/A"
        )
        
        try:
            result = await self._call_llm(prompt)
            category = result.strip().lower()
            # Clean up the output in case LLM added extra words or punctuation
            valid_categories = {
                "homepage", "about", "products", "services", "solutions", "industries",
                "technology", "customers", "case_studies", "portfolio", "team", "leadership",
                "careers", "contact", "locations", "partners", "blog", "news", "events",
                "resources", "documentation", "other"
            }
            # Look for exact match or substring
            for cat in valid_categories:
                if cat in category:
                    return cat
            return "other"
        except Exception as e:
            logger.error(f"Error classifying page {url}: {e}")
            return "other"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def extract_company_data(self, crawled_text: str) -> Optional[LLMStructuredOutput]:
        """
        Takes concatenated page summaries and extracts structured company data.
        """
        if not self.is_active():
            return None
            
        # Limit text length to prevent context limit errors (approx. 50k characters is safe)
        truncated_text = crawled_text[:60000]
        prompt = COMPANY_EXTRACTION_PROMPT.format(crawled_text=truncated_text)
        
        # Add instruction to return JSON that matches the schema
        prompt += f"\nReturn a JSON object that adheres exactly to this structure:\n{self._get_simplified_schema()}"
        
        system_instruction = "You are a professional company intelligence data parser. Return JSON output only."
        
        try:
            raw_response = await self._call_llm(prompt, system_instruction=system_instruction)
            data_dict = self._parse_json_block(raw_response)
            return LLMStructuredOutput.model_validate(data_dict)
        except Exception as e:
            logger.error(f"Failed to extract structured company data: {e}")
            raise e

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    async def enrich_company_data(self, existing_data_json: str, query: str, search_results: str) -> Optional[LLMStructuredOutput]:
        """
        Takes existing company data and search result context, and extracts enriched company fields.
        """
        if not self.is_active():
            return None
            
        prompt = ENRICHMENT_EXTRACTION_PROMPT.format(
            existing_data=existing_data_json,
            query=query,
            search_results=search_results[:30000]
        )
        
        prompt += f"\nReturn a JSON object that adheres exactly to this structure:\n{self._get_simplified_schema()}"
        system_instruction = "You are a professional company intelligence data enricher. Return JSON output only."
        
        try:
            raw_response = await self._call_llm(prompt, system_instruction=system_instruction)
            data_dict = self._parse_json_block(raw_response)
            return LLMStructuredOutput.model_validate(data_dict)
        except Exception as e:
            logger.error(f"Failed to enrich structured company data: {e}")
            raise e
