from triage.models import RepoRef
from triage.tools.github import GitHubTools


def make_tools(pages):
    """GitHubTools whose Composio calls return the given pages of raw issues."""
    tools = GitHubTools.__new__(GitHubTools)
    calls = []

    def fake_execute(slug, arguments, repo):
        calls.append(arguments)
        return {"issues": pages[arguments["page"] - 1] if arguments["page"] <= len(pages) else []}

    tools._execute = fake_execute
    return tools, calls


def raw(number, pr=False):
    d = {"number": number, "title": f"t{number}", "body": "b", "labels": [], "user": {"login": "u"}, "state": "open"}
    if pr:
        d["pull_request"] = {}
    return d


REPO = RepoRef(owner="o", repo="r")


def test_short_first_page_is_the_last():
    tools, calls = make_tools([[raw(1), raw(2)], [raw(3)]])
    issues = tools.list_issues(REPO, limit=5)  # asks for 5 per page, gets 2
    assert [i.number for i in issues] == [1, 2]
    assert len(calls) == 1


def test_skips_pull_requests_and_fetches_more():
    full = lambda start: [raw(n, pr=(n % 2 == 0)) for n in range(start, start + 100)]
    tools, calls = make_tools([full(1), full(101), full(201)])
    issues = tools.list_issues(REPO, limit=120)  # 50 issues per page after dropping PRs
    assert len(issues) == 120
    assert all(i.number % 2 == 1 for i in issues)
    assert [c["page"] for c in calls] == [1, 2, 3]


def test_stops_on_last_page():
    tools, calls = make_tools([[raw(n) for n in range(1, 101)], [raw(101)]])
    issues = tools.list_issues(REPO, limit=500)
    assert len(issues) == 101
    assert [c["page"] for c in calls] == [1, 2]
