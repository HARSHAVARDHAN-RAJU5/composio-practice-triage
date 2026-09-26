"""One issue through the whole flow: pre-checks -> Gemini -> confidence -> rules -> decision."""
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from triage.llm.classify import classify
from triage.llm.gemini import Gemini, LLMError
from triage.models import Classification, Confidence, Issue, RuleResult
from triage.rules.checks import check_issue, check_triage
from triage.rules.confidence import compute_confidence

Action = Literal["reply", "escalate", "error"]


@dataclass
class TriageResult:
    issue: Issue
    action: Action
    rules: List[RuleResult] = field(default_factory=list)
    classification: Optional[Classification] = None
    confidence: Optional[Confidence] = None
    model: Optional[str] = None
    attempts: int = 0
    error: Optional[str] = None

    @property
    def failed(self) -> List[RuleResult]:
        return [r for r in self.rules if not r.passed]


def triage_issue(issue: Issue, llm: Gemini) -> TriageResult:
    # Issue-only rules first: no point paying for a Gemini call we'll escalate anyway
    rules = check_issue(issue)
    if not all(r.passed for r in rules):
        return TriageResult(issue, "escalate", rules)

    try:
        result = classify(issue, llm)
    except LLMError as e:
        return TriageResult(issue, "error", rules, error=str(e))

    c = result.classification
    if c is None:  # still invalid after the re-ask
        rules.append(RuleResult(rule="OUTPUT", passed=False, detail=result.error))
        return TriageResult(issue, "escalate", rules, model=result.model, attempts=result.attempts)

    conf = compute_confidence(issue, c)
    rules += check_triage(issue, c, conf)
    action: Action = "reply" if all(r.passed for r in rules) else "escalate"
    return TriageResult(issue, action, rules, c, conf, result.model, result.attempts)
