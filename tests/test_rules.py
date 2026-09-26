import json

import pytest

from triage.llm.gemini import LLMError
from triage.models import Classification, Confidence, Evidence, Issue
from triage.pipeline import triage_issue
from triage.rules.checks import (
    check_issue, r1_not_unclear, r2_confidence, r3_reply_length, r4_mentions_issue, r5_no_promises,
    r6_links_same_repo, r7_open_with_body, r8_no_side_effects, security_check, title_keywords,
)

TITLE = "App crashes when uploading a PDF larger than 10 MB"


def issue(title=TITLE, body="When I upload a large PDF the page goes blank.", state="open", number=12):
    return Issue(number=number, title=title, body=body, author="a", state=state,
                 repo="HARSHAVARDHAN-RAJU5/Triage_sandbox")


def words(n):
    return " ".join(["word"] * n)


# --- R1 / R2 ------------------------------------------------------------------------------------

def cls(category="bug", reply="x", **yes):
    ev = Evidence(**{f: f in yes for f in Evidence.model_fields})
    return Classification(category=category, evidence=ev, model_confidence=1, reason="r", reply=reply)


@pytest.mark.parametrize("category, passed", [("bug", True), ("feature", True), ("question", True), ("unclear", False)])
def test_r1(category, passed):
    assert r1_not_unclear(cls(category)).passed is passed


@pytest.mark.parametrize("score, passed", [(0.69, False), (0.7, True), (0.95, True)])
def test_r2_threshold_is_inclusive(score, passed):
    assert r2_confidence(Confidence(score=score, parts=[])).passed is passed


# --- R3 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("n, passed", [(0, False), (19, False), (20, True), (150, True), (151, False)])
def test_r3_word_limits(n, passed):
    assert r3_reply_length(words(n)).passed is passed


# --- R4 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "reply, passed",
    [
        ("Thanks for opening #12.", True),
        ("Thanks for opening issue 12.", True),
        ("Thanks for #120.", False),          # a different issue number
        ("Thanks for #1.", False),
        ("Sorry the app crashes for you.", True),  # title word
        ("Sorry about the crash.", True),     # plural in title, singular in reply
        ("Uploading big files is hard.", True),
        ("Thanks, noted for the maintainers.", False),
        ("Thanks for the details.", False),
        ("Thanks for reaching out, this issue is noted.", False),  # "issue" alone is not a title word
    ],
)
def test_r4(reply, passed):
    assert r4_mentions_issue(issue(), reply).passed is passed


def test_title_keywords_skip_stopwords_and_numbers():
    assert title_keywords("It doesn't work") == []
    assert title_keywords(TITLE) == ["app", "crashes", "uploading", "pdf", "larger"]


# --- R5 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "reply",
    [
        "This will be fixed in the next release.",
        "We will fix this.",
        "We'll fix it soon.",
        "We will have it done by tomorrow.",
        "We GUARANTEE it works.",
        "This is guaranteed.",
        "You will get a refund.",
        "We have refunded you.",
    ],
)
def test_r5_catches_promises(reply):
    assert not r5_no_promises(reply).passed


@pytest.mark.parametrize(
    "reply",
    ["Thanks, this has been noted for the maintainers.", "Could you share the steps to reproduce?",
     "The fix-it tool is mentioned in the title."],
)
def test_r5_allows_normal_replies(reply):
    assert r5_no_promises(reply).passed


# --- R6 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "reply, passed",
    [
        ("No links at all.", True),
        ("See https://github.com/HARSHAVARDHAN-RAJU5/Triage_sandbox/blob/main/README.md.", True),
        ("See https://github.com/harshavardhan-raju5/triage_sandbox#readme", True),  # case-insensitive
        ("See [the docs](https://github.com/HARSHAVARDHAN-RAJU5/Triage_sandbox/wiki).", True),
        ("Repo: https://github.com/HARSHAVARDHAN-RAJU5/Triage_sandbox", True),
        ("See https://evil.example/patch.exe", False),
        ("See www.evil.example", False),
        ("See https://github.com/HARSHAVARDHAN-RAJU5/Triage_sandbox-evil/issues", False),  # look-alike
        ("See https://github.com/someone/else", False),
        ("See http://github.com/HARSHAVARDHAN-RAJU5/Triage_sandbox", False),  # plain http
        ("See [docs](https://evil.example)", False),
        # found in the live review: all used to pass
        ('<a href="//evil.example/x">details</a>', False),
        ('<img src="//evil.example/pixel.png">', False),
        ("See evil.example for a patch.", False),
        ("Download from files.evil.co/patch.exe", False),
        ("ftp://evil.example/file", False),
        # must not be mistaken for domains
        ("Please attach README.md, config.json and main.py.", True),
        ("Try running install.sh, e.g. with bash.", True),
        ("See https://github.com/HARSHAVARDHAN-RAJU5/Triage_sandbox/blob/main/docs.md", True),
    ],
)
def test_r6(reply, passed):
    assert r6_links_same_repo(issue(), reply).passed is passed


# --- R7 / SECURITY ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "state, body, passed",
    [("open", "details", True), ("closed", "details", False), ("open", "", False), ("open", "   \n", False)],
)
def test_r7(state, body, passed):
    assert r7_open_with_body(issue(state=state, body=body)).passed is passed


@pytest.mark.parametrize(
    "title, body",
    [
        ("it doesnt work", "pls fix asap, lost a lot of money because of this. i want a refund"),
        ("Login", "My password is shown in the logs"),
        ("Leak", "The API key is exposed in the page source"),
        ("CVE-2024-1234 in parser", "details"),
        ("XSS in comments", "details"),
        ("Charged twice", "I was charged twice for the subscription"),
    ],
)
def test_security_escalates(title, body):
    assert not security_check(issue(title=title, body=body)).passed


@pytest.mark.parametrize(
    "title, body",
    [
        (TITLE, "When I upload a large PDF the page goes blank."),
        ("Memory leak in parser", "Memory grows over time."),  # "leak" alone is not sensitive
        ("Tokenizer splits words wrong", "The tokenizer output is off."),  # word boundary
    ],
)
def test_security_ignores_normal_issues(title, body):
    assert security_check(issue(title=title, body=body)).passed


# --- pipeline -----------------------------------------------------------------------------------

GOOD_REPLY = ("Thanks for opening #12 about the app crashing on large PDF uploads. Could you share your "
              "browser version and the exact size of the file? That will help the maintainers look at it.")


class FakeLLM:
    def __init__(self, category="bug", reply=GOOD_REPLY, fail=False, **yes):
        self.fail, self.calls = fail, 0
        ev = {f: f in yes for f in Evidence.model_fields}
        self.out = json.dumps({"category": category, "evidence": ev, "model_confidence": 1,
                               "reason": "r", "reply": reply})

    def generate_json(self, system, prompt, schema):
        self.calls += 1
        if self.fail:
            raise LLMError("All Gemini models failed")
        return self.out, "fake"


STRONG = dict(actionable=1, single_topic=1, has_repro_steps=1, has_error_or_logs=1)


def test_pipeline_reply_when_all_rules_pass():
    r = triage_issue(issue(), FakeLLM(**STRONG))
    assert r.action == "reply", r.failed
    assert [x.rule for x in r.rules] == ["R7", "SECURITY", "R1", "R2", "R3", "R4", "R5", "R6", "R8"]


def test_pipeline_skips_gemini_when_pre_checks_fail():
    llm = FakeLLM(**STRONG)
    r = triage_issue(issue(body="I want a refund"), llm)
    assert r.action == "escalate" and llm.calls == 0
    assert [f.rule for f in r.failed] == ["SECURITY"]


def test_pipeline_reports_every_failed_rule():
    r = triage_issue(issue(), FakeLLM("unclear", reply="We will fix this by tomorrow, see https://evil.example"))
    assert r.action == "escalate"
    assert [f.rule for f in r.failed] == ["R1", "R2", "R3", "R4", "R5", "R6"]


def test_pipeline_error_when_no_model_answers():
    r = triage_issue(issue(), FakeLLM(fail=True))
    assert r.action == "error" and "All Gemini models failed" in r.error


def test_pipeline_escalates_invalid_output():
    llm = FakeLLM()
    llm.out = "not json"
    r = triage_issue(issue(), llm)
    assert r.action == "escalate" and r.failed[0].rule == "OUTPUT" and llm.calls == 2


# --- R8: nothing that notifies people, links elsewhere or triggers bots --------------------------

@pytest.mark.parametrize(
    "reply",
    [
        "cc @torvalds",
        "Pinging @github/security-team for this.",
        "This looks similar to #2.",
        "Duplicate of GH-7.",
        "See HARSHAVARDHAN-RAJU5/other-repo#5.",
        "See someone/else#12.",
        "Thanks!\n/close",
        "  /assign @x",
    ],
)
def test_r8_blocks_side_effects(reply):
    assert not r8_no_side_effects(issue(), reply).passed


@pytest.mark.parametrize(
    "reply",
    [
        "Thanks for opening #12.",
        "Thanks for issue GH-12.",
        "Tracked as HARSHAVARDHAN-RAJU5/Triage_sandbox#12.",
        "Email support@example.com is not a mention.",  # R6's job, not R8's
        "The color #fff is fine, and so is `@decorator` in code.",
        "Use and/or as needed; paths like src/main work.",
        GOOD_REPLY,
    ],
)
def test_r8_allows_normal_replies(reply):
    assert r8_no_side_effects(issue(), reply).passed
