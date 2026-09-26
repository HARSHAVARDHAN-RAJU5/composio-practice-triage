"""Gemini calls with retry/backoff and fallback to a second model."""
import time

from google import genai
from google.genai import errors

from triage.config import Config

RETRYABLE = {429, 500, 503}
MAX_RETRIES = 3


class LLMError(Exception):
    pass


class Gemini:
    def __init__(self, config: Config):
        self.client = genai.Client(api_key=config.gemini_api_key)
        self.models = [config.gemini_model, config.gemini_fallback_model]

    def generate(self, prompt: str) -> tuple:
        """Return (text, model_that_answered)."""
        last_error = None
        for model in self.models:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = self.client.models.generate_content(model=model, contents=prompt)
                    return resp.text, model
                except errors.APIError as e:
                    last_error = e
                    if e.code not in RETRYABLE:
                        break
                    time.sleep(2 ** attempt)
        raise LLMError(f"All Gemini models failed: {last_error}")
