"""Validate a GitHub target before any network call."""
import re

from triage.models import RepoRef

OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
REPO = r"[A-Za-z0-9._-]{1,100}"

URL_PATTERN = re.compile(
    rf"^https?://(?:www\.)?github\.com/(?P<owner>{OWNER})/(?P<repo>{REPO}?)(?:\.git)?"
    rf"(?:/issues/(?P<number>[1-9]\d*))?/?$"
)
SHORT_PATTERN = re.compile(rf"^(?P<owner>{OWNER})/(?P<repo>{REPO})(?:#(?P<number>[1-9]\d*))?$")


class InvalidTarget(ValueError):
    pass


def parse_target(text: str) -> RepoRef:
    """Accept owner/repo, owner/repo#12, a repo URL or an issue URL."""
    text = (text or "").strip()
    match = URL_PATTERN.match(text) or SHORT_PATTERN.match(text)
    if not match or match["repo"] in (".", ".."):
        raise InvalidTarget(
            f"Not a valid GitHub repo or issue: {text!r}. "
            "Use owner/repo, owner/repo#12, https://github.com/owner/repo "
            "or https://github.com/owner/repo/issues/12"
        )
    number = match["number"]
    return RepoRef(owner=match["owner"], repo=match["repo"], number=int(number) if number else None)
