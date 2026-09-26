"""Classify an issue and draft a reply, validated against the Classification schema."""
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from triage.llm.gemini import Gemini
from triage.llm.prompts import RETRY_NOTE, issue_prompt, system_prompt
from triage.models import Classification, Issue

MAX_ATTEMPTS = 2  # first try + one re-ask


@dataclass
class ClassifyResult:
    classification: Optional[Classification]  # None -> model output never validated: escalate
    model: str  # which model answered (last attempt)
    attempts: int
    error: Optional[str] = None


def classify(issue: Issue, llm: Gemini) -> ClassifyResult:
    """Raises LLMError if no model answers at all (caller logs decision=error)."""
    system = system_prompt(issue)
    prompt = issue_prompt(issue)
    error = None
    model = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        note = RETRY_NOTE.format(error=error) if error else ""
        text, model = llm.generate_json(system, prompt + note, Classification)
        try:
            return ClassifyResult(Classification.model_validate_json(text), model, attempt)
        except ValidationError as e:
            error = _describe(e)
    return ClassifyResult(None, model, MAX_ATTEMPTS, f"invalid model output after re-ask: {error}")


def _describe(e: ValidationError) -> str:
    parts = []
    for err in e.errors()[:3]:
        field = ".".join(str(p) for p in err["loc"]) or "output"
        parts.append(f"{field}: {err['msg']}")
    return "; ".join(parts)
