"""log.jsonl (every issue, every run) and escalation.jsonl (issues a human must handle)."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from triage.models import Issue
from triage.pipeline import TriageResult

LOG_FILE = "log.jsonl"
ESCALATION_FILE = "escalation.jsonl"

Decision = Literal["reply", "escalate", "error", "skip"]


class Recorder:
    def __init__(self, out_dir: str = ".", mode: str = "dry-run"):
        self.log_path = Path(out_dir) / LOG_FILE
        self.escalation_path = Path(out_dir) / ESCALATION_FILE
        self.run_id = uuid.uuid4().hex[:8]
        self.mode = mode

    def result(self, r: TriageResult, decision: Decision, posted: bool = False,
               comment_url: Optional[str] = None, error: Optional[str] = None) -> None:
        c, conf = r.classification, r.confidence
        entry = {
            **self._head(r.issue.repo),
            **_issue_fields(r.issue),
            "decision": decision,
            "posted": posted,
            "comment_url": comment_url,
            "category": c.category if c else None,
            "confidence": conf.score if conf else None,
            "confidence_parts": [p.model_dump() for p in conf.parts] if conf else None,
            "model_confidence": c.model_confidence if c else None,
            "evidence": c.evidence.model_dump() if c else None,
            "model": r.model,
            "attempts": r.attempts,
            "rules": [x.model_dump() for x in r.rules],
            "failed_rules": [x.rule for x in r.failed],
            "reason": c.reason if c else None,
            "reply": c.reply if c else None,
            "error": error or r.error,
        }
        self._append(self.log_path, entry)
        if decision == "escalate":
            self._append(self.escalation_path, {
                **self._head(r.issue.repo),
                **_issue_fields(r.issue),
                "author": r.issue.author,
                "reasons": [f"{x.rule}: {x.detail}" for x in r.failed],
                "category": entry["category"],
                "confidence": entry["confidence"],
                "draft_reply": entry["reply"],  # a human can edit and post it
            })

    def skipped(self, issue: Issue, reason: str) -> None:
        self._append(self.log_path, {**self._head(issue.repo), **_issue_fields(issue),
                                      "decision": "skip", "posted": False, "reason": reason})

    def run_error(self, error: str, repo: Optional[str] = None, target: Optional[str] = None) -> None:
        """A failure before any issue was triaged (bad URL, auth, fetch)."""
        self._append(self.log_path, {**self._head(repo), "issue": None, "target": target,
                                      "decision": "error", "posted": False, "error": error})

    def _head(self, repo: Optional[str]) -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "mode": self.mode,
            "repo": repo,
        }

    @staticmethod
    def _append(path: Path, entry: dict) -> None:
        # utf-8 explicitly: Windows defaults to cp1252, which crashes on emoji in issue text
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _issue_fields(issue: Issue) -> dict:
    return {"issue": issue.number, "title": issue.title, "url": issue.url}
