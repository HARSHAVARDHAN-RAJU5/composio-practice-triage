"""Gemini calls with retry/backoff and fallback to a second model."""
import time
from typing import Optional, Tuple, Type

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from triage.config import Config

RETRYABLE = {429, 500, 503, 504}
# Primary gets one try: when it's overloaded (503 "high demand") retrying it mostly wastes
# time, so switch to the fallback fast. The fallback is the last resort, so it gets backoff.
PRIMARY_ATTEMPTS = 1
FALLBACK_ATTEMPTS = 3
TIMEOUT_MS = 60_000


class LLMError(Exception):
    pass


class Gemini:
    def __init__(self, config: Config):
        self.client = genai.Client(
            api_key=config.gemini_api_key,
            http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        )
        self.models = [config.gemini_model, config.gemini_fallback_model]

    def generate(self, prompt: str) -> Tuple[str, str]:
        """Plain text. Return (text, model_that_answered)."""
        return self._call(prompt, self._config())

    def generate_json(self, system: str, prompt: str, schema: Type[BaseModel]) -> Tuple[str, str]:
        """JSON constrained to `schema`. Return (raw_text, model_that_answered); caller validates."""
        config = self._config(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            # Classification is simple; low thinking keeps it fast and cheap.
            # Temperature stays at Gemini 3's default (1.0): Google warns lower values can loop.
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        )
        return self._call(prompt, config)

    @staticmethod
    def _config(**kwargs) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            **kwargs,
        )

    def _call(self, contents: str, config: types.GenerateContentConfig) -> Tuple[str, str]:
        last_error: Optional[Exception] = None
        for model, attempts in zip(self.models, (PRIMARY_ATTEMPTS, FALLBACK_ATTEMPTS)):
            for attempt in range(attempts):
                try:
                    resp = self.client.models.generate_content(model=model, contents=contents, config=config)
                    return resp.text or "", model
                except errors.APIError as e:
                    last_error = e
                    if e.code not in RETRYABLE:
                        break  # e.g. 404 model retired: retrying won't help, try the fallback
                except httpx.TransportError as e:  # timeout, connection reset, DNS
                    last_error = e
                if attempt < attempts - 1:
                    time.sleep(2 ** attempt)
        raise LLMError(f"All Gemini models failed ({', '.join(self.models)}): {_short(last_error)}")


def _short(error: Optional[Exception]) -> str:
    if isinstance(error, errors.APIError):
        return f"{error.code} {error.status}: {(error.message or '')[:200]}"
    return str(error)[:200]
