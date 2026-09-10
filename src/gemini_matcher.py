# -*- coding: utf-8 -*-
"""
Hybrid AI Assistant for Pharmaceutical Medicine Matching.
Powered by Gemini 3.6 Flash for instant semantic transliteration, typo correction, and brand matching.
Enforces Hard Clinical Safety Gates on Form, Strength, and Modifiers.
"""
import os
import re
import json
import logging
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from .pharma_matcher import (
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility,
    clean_arabic_string
)

logger = logging.getLogger("GeminiMatcher")

class GeminiMedicineMatcher:
    def __init__(self, api_key: str = None, model: str = None, enabled: bool = True):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        env_enabled = os.getenv("ENABLE_GEMINI", "true").lower() in ("true", "1", "yes")
        self.enabled = enabled and env_enabled and bool(self.api_key)
        self.client = None
        
        if self.enabled:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Gemini Client: {e}")
                self.enabled = False

    def batch_match(self, unmatched_items: list, catalog_df: pd.DataFrame, batch_size: int = 60) -> dict:
        """
        Takes a list of requested items that failed deterministic matching,
        and matches them against catalog candidates using Gemini Flash.
        Returns: {req_item: {'matched_candidate': str, 'confidence': float, 'reason': str}}
        """
        if not self.enabled or not unmatched_items or catalog_df.empty:
            return {}

        results = {}
        unique_catalog_items = sorted(list(catalog_df['item_name'].dropna().unique()))
        
        for i in range(0, len(unmatched_items), batch_size):
            batch = unmatched_items[i:i + batch_size]
            batch_res = self._process_batch(batch, unique_catalog_items)
            results.update(batch_res)
            
        return results

    def _process_batch(self, requested_items: list, catalog_candidates: list) -> dict:
        from google.genai import types

        candidates_to_pass = catalog_candidates[:400] if len(catalog_candidates) > 400 else catalog_candidates
        
        system_prompt = (
            "You are an expert Egyptian Pharmaceutical Procurement Matching Engine.\n"
            "Your task is to match requested pharmacy order items (which may be in Arabic, English, or Franco-Arab with typos) "
            "to the exact corresponding item in the warehouse catalog.\n\n"
            "CRITICAL CLINICAL RULES:\n"
            "1. Transliteration: Accurately match Arabic to English trade names (e.g. اوجمنتين = Augmentin, بنادول = Panadol, كتافلام = Cataflam, كونكور = Concor, بروفين = Brufen).\n"
            "2. NEVER substitute different strengths (e.g., 500mg != 1000mg, 1gm != 625mg).\n"
            "3. NEVER substitute different dosage forms (e.g., Tablet != Syrup != Injection != Cream != Drops).\n"
            "4. NEVER substitute different formulation modifiers (e.g., Plain != Extra != XR/SR != Cold & Flu).\n"
            "5. If a requested item has no exact match in the available candidates, set matched_candidate to null.\n"
            "Output strictly valid JSON array of objects:\n"
            "[\n"
            "  {\n"
            "    \"requested\": \"item_name\",\n"
            "    \"matched_candidate\": \"exact_catalog_candidate_string_or_null\",\n"
            "    \"confidence\": 0.95,\n"
            "    \"reason\": \"brief explanation\"\n"
            "  }\n"
            "]"
        )
        
        user_content = "Requested Items:\n" + "\n".join(f"- {item}" for item in requested_items) + "\n\n"
        user_content += "Available Warehouse Catalog Products:\n" + "\n".join(f"- {c}" for c in candidates_to_pass)

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=4096
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=f"{system_prompt}\n\n{user_content}",
                config=config
            )
            raw_text = response.text.strip()
            data = json.loads(raw_text)
            
            validated_matches = {}
            for entry in data:
                req = entry.get("requested")
                cand = entry.get("matched_candidate")
                conf = float(entry.get("confidence", 0.0))
                reason = entry.get("reason", "")
                
                if not cand or conf < 0.80:
                    continue
                    
                # HARD CLINICAL SAFETY GATE CHECK
                if self._verify_hard_safety_gates(req, cand):
                    validated_matches[req] = {
                        "matched_candidate": cand,
                        "confidence": conf,
                        "reason": reason
                    }
                else:
                    logger.warning(f"SAFETY GATE REJECTED Gemini suggestion: '{req}' -> '{cand}'")

            return validated_matches

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                logger.warning(f"Gemini Free Tier daily quota reached. Proceeding with deterministic results.")
                self.enabled = False  # Disable further calls for this run
            else:
                logger.error(f"Gemini matching error: {e}")
            return {}

    def _verify_hard_safety_gates(self, req: str, cand: str) -> bool:
        """Enforces deterministic clinical safety checks on any LLM output."""
        # 1. Dosage Form Category
        form_req = extract_form_category(req)
        form_cand = extract_form_category(cand)
        if form_req != "UNKNOWN" and form_cand != "UNKNOWN" and form_req != form_cand:
            return False
            
        # 2. Strength Compatibility
        if not check_strength_compatibility(req, cand):
            return False
            
        # 3. Formulation Modifier Compatibility
        if not check_modifier_compatibility(req, cand):
            return False
            
        return True
