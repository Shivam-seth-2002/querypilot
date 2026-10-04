"""Google Gemini API client wrapper using google-genai SDK with retries, timeout, and JSON extraction."""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional
from google import genai
from google.genai import types

from querypilot.config import settings

logger = logging.getLogger(__name__)


class GeminiAPIKeyMissingError(RuntimeError):
    """Raised when GEMINI_API_KEY is required but not configured."""
    pass


class GeminiClient:
    """Wrapper around Google GenAI SDK with retry logic and JSON formatting."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._client: Optional[genai.Client] = None
        if self.api_key and self.api_key != "your_gemini_api_key_here":
            self._client = genai.Client(api_key=self.api_key)

    @property
    def is_configured(self) -> bool:
        """Check if a valid non-placeholder API key is available."""
        return bool(self.api_key and self.api_key != "your_gemini_api_key_here")

    def _get_client(self) -> genai.Client:
        """Get or initialize the GenAI client."""
        if not self.is_configured:
            # Re-check environment in case user updated .env during runtime
            current_key = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
            if current_key and current_key != "your_gemini_api_key_here":
                self.api_key = current_key
                self._client = genai.Client(api_key=self.api_key)
            else:
                raise GeminiAPIKeyMissingError(
                    "GEMINI_API_KEY is not configured. Please set your Gemini API key in .env or the environment."
                )
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> str:
        """Generate text using Gemini model with retry mechanism."""
        client = self._get_client()

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            response_mime_type="application/json" if json_mode else None,
        )

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                if response.text is not None:
                    return response.text.strip()
                return ""
            except Exception as e:
                last_error = e
                wait_time = self.retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"Gemini API request attempt {attempt}/{self.max_retries} failed: {e}. Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)

        raise RuntimeError(f"Gemini API failed after {self.max_retries} attempts: {last_error}")

    def generate_json(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Generate structured JSON response, cleaning markdown code fences if present."""
        raw_text = self.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            json_mode=True,
            temperature=temperature,
        )
        return self.extract_json(raw_text)

    @staticmethod
    def extract_json(text: str) -> Dict[str, Any]:
        """Clean and parse JSON from text that might include markdown code fences."""
        cleaned = text.strip()
        # Remove markdown code fences like ```json ... ``` or ``` ... ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: search for first '{' and last '}'
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise
