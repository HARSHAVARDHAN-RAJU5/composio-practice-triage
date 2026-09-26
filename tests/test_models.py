import pytest
from pydantic import ValidationError

from triage.models import Issue, RepoRef
from triage.tools.github import GitHubTools, ToolError, _to_issue

REPO = RepoRef(owner="o", repo="r")


def test_maps_github_payload():
    issue = Issue.from_github(
        {
            "number": 5,
            "title": "Crash 🐛",
            "body": "  details \n",
            "labels": [{"name": "bug"}, {"name": "ui"}],
            "user": {"login": "alice"},
            "state": "open",
            "html_url": "https://github.com/o/r/issues/5",
            "comments": 4,
        },
        REPO,
    )
    assert issue.model_dump() == {
        "number": 5,
        "title": "Crash 🐛",
        "body": "details",
        "labels": ["bug", "ui"],
        "author": "alice",
        "state": "open",
        "url": "https://github.com/o/r/issues/5",
        "comments": 4,
        "repo": "o/r",
    }


@pytest.mark.parametrize(
    "data, field, expected",
    [
        ({"number": 1, "labels": ["bug"]}, "labels", ["bug"]),
        ({"number": 1, "user": None}, "author", "unknown"),
        ({"number": 1, "title": None}, "title", ""),
        ({"number": 1, "body": None}, "body", ""),
        ({"number": 1, "body": " \n\t"}, "body", ""),
    ],
)
def test_tolerates_odd_but_valid_payloads(data, field, expected):
    assert getattr(Issue.from_github(data, REPO), field) == expected


def test_missing_number_is_a_validation_error():
    with pytest.raises(ValidationError):
        Issue.from_github({"title": "x"}, REPO)


def test_bad_payload_becomes_friendly_tool_error():
    with pytest.raises(ToolError, match="Unexpected issue data from GitHub for #\\? in o/r: number"):
        _to_issue({"title": "x"}, REPO)


def test_changed_response_shape_is_an_error_not_empty():
    tools = GitHubTools.__new__(GitHubTools)
    tools._execute = lambda slug, arguments, repo: {"details": []}
    with pytest.raises(ToolError, match="no 'issues' list"):
        tools.list_issues(REPO, limit=5)
