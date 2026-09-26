"""Confidence = evidence Gemini reports (yes/no) + fixed checks on the issue text. No model numbers."""
import re
from typing import List

from triage.models import Classification, Confidence, Issue, ScorePart

# Base + all common weights = 0.60, below the 0.70 threshold: an issue needs at least one
# category-specific fact to pass. Every category maxes out at exactly 1.0.
BASE = 0.35

COMMON_WEIGHTS = {
    "actionable": 0.15,
    "single_topic": 0.10,
    "fits_another_category": -0.25,
}

# Only the weights for the category Gemini picked count; "unclear" gets none (R1 escalates it anyway)
CATEGORY_WEIGHTS = {
    "bug": {
        "has_repro_steps": 0.15,
        "has_error_or_logs": 0.15,
        "has_expected_vs_actual": 0.05,
        "has_environment": 0.05,
    },
    "feature": {
        "describes_behaviour": 0.25,
        "explains_use_case": 0.15,
    },
    "question": {
        "specific_question": 0.25,
        "shows_effort": 0.15,
    },
    "unclear": {},
}

SHORT_BODY_WORDS = 15
SHORT_BODY_PENALTY = -0.20

GENERIC_TITLES = {
    "it doesnt work", "it doesn't work", "doesnt work", "doesn't work", "not working",
    "help", "bug", "error", "issue", "problem", "question", "broken", "fix", "urgent",
}
SHORT_TITLE_WORDS = 4
GENERIC_TITLE_PENALTY = -0.10

MOSTLY_LOG_RATIO = 0.8  # share of the body that is code/log
MOSTLY_LOG_PENALTY = -0.10
FENCED_CODE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
LOG_LINE = re.compile(
    r"^\s*(at\s|File \"|Traceback|\w*(Error|Exception)\b|\[?\d{4}-\d\d-\d\d|\$ |>>> |[{}\[\]<>]\s*$)"
)


def compute_confidence(issue: Issue, c: Classification) -> Confidence:
    parts: List[ScorePart] = [ScorePart(label="base", delta=BASE)]

    weights = {**COMMON_WEIGHTS, **CATEGORY_WEIGHTS[c.category]}
    for field, weight in weights.items():
        if getattr(c.evidence, field):
            parts.append(ScorePart(label=field, delta=weight))

    if len(issue.body.split()) < SHORT_BODY_WORDS:
        parts.append(ScorePart(label="short body", delta=SHORT_BODY_PENALTY))
    if is_generic_title(issue.title):
        parts.append(ScorePart(label="generic title", delta=GENERIC_TITLE_PENALTY))
    if is_mostly_log(issue.body):
        parts.append(ScorePart(label="mostly log/code", delta=MOSTLY_LOG_PENALTY))

    score = min(1.0, max(0.0, sum(p.delta for p in parts)))
    return Confidence(score=round(score, 2), parts=parts)


def is_generic_title(title: str) -> bool:
    normalized = re.sub(r"[^\w\s']", "", title.lower()).strip()
    return normalized in GENERIC_TITLES or len(normalized.split()) < SHORT_TITLE_WORDS


def is_mostly_log(body: str) -> bool:
    if not body:
        return False
    code_chars = sum(len(m) for m in FENCED_CODE.findall(body))
    rest = FENCED_CODE.sub("", body)
    code_chars += sum(len(line) for line in rest.splitlines() if LOG_LINE.match(line))
    return code_chars / len(body) >= MOSTLY_LOG_RATIO
