import json

import pytest

from triage import cli
from triage.models import Evidence, Issue
from triage.tools.github import BOT_MARKER, GitHubTools, ToolError
from triage.tools.records import Recorder
from tests.test_rules import FakeLLM, GOOD_REPLY, STRONG


def issue(body="When I upload a large PDF the page goes blank.", comments=0, title="App crashes on PDF upload 🐛"):
    return Issue(number=12, title=title, body=body, author="a", state="open",
                 repo="HARSHAVARDHAN-RAJU5/Triage_sandbox", url="https://github.com/x/y/issues/12",
                 comments=comments)


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class FakeGH:
    def __init__(self, skip=None, skip_error=None, post_error=None):
        self.skip, self.skip_error, self.post_error = skip, skip_error, post_error
        self.posted = []

    def skip_reason(self, issue):
        if self.skip_error:
            raise ToolError(self.skip_error)
        return self.skip

    def post_comment(self, issue, reply):
        if self.post_error:
            raise ToolError(self.post_error)
        self.posted.append(reply)
        return "https://github.com/x/y/issues/12#issuecomment-1"


@pytest.fixture
def rec(tmp_path):
    return Recorder(str(tmp_path), mode="test")


# --- handle_issue: dry run, post, skip, failures ------------------------------------------------

def test_dry_run_never_posts(rec):
    gh = FakeGH()
    assert cli.handle_issue(issue(), FakeLLM(**STRONG), gh, rec, post=False) == "reply"
    assert gh.posted == []
    [entry] = read(rec.log_path)
    assert entry["decision"] == "reply" and entry["posted"] is False
    assert not rec.escalation_path.exists()


def test_post_mode_posts_the_reply(rec):
    gh = FakeGH()
    assert cli.handle_issue(issue(), FakeLLM(**STRONG), gh, rec, post=True) == "posted"
    assert gh.posted == [GOOD_REPLY]
    [entry] = read(rec.log_path)
    assert entry["posted"] is True and entry["comment_url"].endswith("issuecomment-1")
    assert entry["model"] == "fake" and entry["category"] == "bug"


def test_escalation_is_never_posted_and_goes_to_both_files(rec):
    gh = FakeGH()
    assert cli.handle_issue(issue(body="I want a refund"), FakeLLM(**STRONG), gh, rec, post=True) == "escalate"
    assert gh.posted == []
    [log] = read(rec.log_path)
    [esc] = read(rec.escalation_path)
    assert log["decision"] == "escalate" and log["failed_rules"] == ["SECURITY"]
    assert esc["issue"] == 12 and esc["reasons"] == ["SECURITY: sensitive topic: refund"]


def test_already_replied_is_skipped_without_calling_gemini(rec):
    llm = FakeLLM(**STRONG)
    assert cli.handle_issue(issue(comments=3), llm, FakeGH(skip="already has a reply from this bot"), rec, post=True) == "skip"
    assert llm.calls == 0
    [entry] = read(rec.log_path)
    assert entry["decision"] == "skip" and entry["reason"] == "already has a reply from this bot"


def test_cannot_check_comments_means_error_not_a_risky_post(rec):
    llm, gh = FakeLLM(**STRONG), FakeGH(skip_error="network down")
    assert cli.handle_issue(issue(comments=3), llm, gh, rec, post=True) == "error"
    assert llm.calls == 0 and gh.posted == []
    assert read(rec.log_path)[0]["error"] == "network down"


def test_post_failure_is_logged_as_error(rec):
    gh = FakeGH(post_error="GitHub refused access (403)")
    assert cli.handle_issue(issue(), FakeLLM(**STRONG), gh, rec, post=True) == "error"
    [entry] = read(rec.log_path)
    assert entry["decision"] == "error" and entry["posted"] is False
    assert entry["error"] == "post failed: GitHub refused access (403)"
    assert entry["reply"] == GOOD_REPLY  # the draft is kept for a human


def test_llm_failure_is_logged_as_error(rec):
    assert cli.handle_issue(issue(), FakeLLM(fail=True), FakeGH(), rec, post=True) == "error"
    [entry] = read(rec.log_path)
    assert entry["decision"] == "error" and "All Gemini models failed" in entry["error"]


# --- records -------------------------------------------------------------------------------------

def test_log_is_utf8_json_lines_and_appends(rec):
    cli.handle_issue(issue(), FakeLLM(**STRONG), FakeGH(), rec, post=False)
    cli.handle_issue(issue(), FakeLLM(**STRONG), FakeGH(), rec, post=False)
    entries = read(rec.log_path)
    assert len(entries) == 2
    assert entries[0]["title"] == "App crashes on PDF upload 🐛"
    assert "🐛" in rec.log_path.read_text(encoding="utf-8")  # written as-is, not \\u escapes
    assert entries[0]["run_id"] == entries[1]["run_id"]
    assert {"ts", "mode", "repo", "rules", "confidence_parts", "evidence"} <= set(entries[0])


def test_run_error_entry(rec):
    rec.run_error("GitHub repository not found", repo="o/r", target="o/r")
    [entry] = read(rec.log_path)
    assert entry["decision"] == "error" and entry["issue"] is None and entry["target"] == "o/r"


def test_invalid_target_is_logged_before_any_network_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(cli, "GitHubTools", boom)
    monkeypatch.setattr(cli, "load_config", boom)
    assert cli.main(["https://gitlab.com/o/r", "--out-dir", str(tmp_path)]) == 2
    [entry] = read(tmp_path / "log.jsonl")
    assert entry["decision"] == "error" and entry["target"] == "https://gitlab.com/o/r"


# --- GitHubTools comment helpers -----------------------------------------------------------------

def fake_tools(pages):
    tools = GitHubTools.__new__(GitHubTools)
    calls = []

    def execute(slug, arguments, repo):
        calls.append((slug, arguments))
        if slug == "GITHUB_CREATE_AN_ISSUE_COMMENT":
            return {"html_url": "https://github.com/x/y/issues/12#issuecomment-9"}
        page = arguments["page"]
        return {"comments": pages[page - 1] if page <= len(pages) else []}

    tools._execute = execute
    return tools, calls


def comment(body="hi", login="stranger", role="NONE"):
    return {"body": body, "user": {"login": login}, "author_association": role}


def test_no_comments_means_no_call():
    tools, calls = fake_tools([])
    assert tools.skip_reason(issue(comments=0)) is None and calls == []


def test_finds_marker_on_a_later_page():
    tools, calls = fake_tools([[comment()] * 100, [comment(f"Thanks!\n\n{BOT_MARKER}", "bob", "OWNER")]])
    assert tools.skip_reason(issue(comments=101)) == "already has a reply from this bot"
    assert [a["page"] for _, a in calls] == [1, 2]


def test_other_peoples_comments_dont_block():
    tools, _ = fake_tools([[comment(), comment(None), comment(login="x", role="CONTRIBUTOR")]])
    assert tools.skip_reason(issue(comments=3)) is None


@pytest.mark.parametrize("role", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_maintainer_answer_blocks(role):
    tools, _ = fake_tools([[comment("Try setting OUTPUT_DIR.", "maint", role)]])
    assert tools.skip_reason(issue(comments=1)) == f"a maintainer (maint, {role}) already commented"


def test_maintainer_follow_up_on_own_issue_does_not_block():
    tools, _ = fake_tools([[comment("more details", "a", "OWNER")]])  # "a" is the issue author
    assert tools.skip_reason(issue(comments=1)) is None


def test_bot_marker_wins_over_maintainer_reason():
    tools, _ = fake_tools([[comment("answer", "maint", "OWNER"), comment(f"x {BOT_MARKER}", "maint", "OWNER")]])
    assert tools.skip_reason(issue(comments=2)) == "already has a reply from this bot"


def test_post_comment_appends_hidden_marker():
    tools, calls = fake_tools([])
    url = tools.post_comment(issue(), "Thanks for the report.")
    slug, args = calls[0]
    assert slug == "GITHUB_CREATE_AN_ISSUE_COMMENT"
    assert args["body"] == f"Thanks for the report.\n\n{BOT_MARKER}"
    assert (args["owner"], args["repo"], args["issue_number"]) == ("HARSHAVARDHAN-RAJU5", "Triage_sandbox", 12)
    assert url.endswith("issuecomment-9")
