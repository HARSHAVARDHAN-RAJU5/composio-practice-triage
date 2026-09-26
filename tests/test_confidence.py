import pytest

from triage.models import Classification, Evidence, Issue
from triage.rules.confidence import compute_confidence, is_generic_title, is_mostly_log

LONG_BODY = (
    "When I upload a PDF larger than 10 MB the page goes blank and the console shows "
    "RangeError: Maximum call stack size exceeded. Smaller files work fine for me."
)


def issue(title="App crashes when uploading a large PDF", body=LONG_BODY):
    return Issue(number=1, title=title, body=body, author="a", state="open", repo="o/r")


def classification(category="bug", **yes):
    evidence = Evidence(**{f: f in yes for f in Evidence.model_fields})
    return Classification(category=category, evidence=evidence, model_confidence=1.0, reason="r", reply="x")


def score(i, c):
    return compute_confidence(i, c).score


# --- the sandbox examples from the proposal ---------------------------------------------------

def test_detailed_bug_passes():
    c = classification("bug", actionable=1, single_topic=1, has_repro_steps=1, has_error_or_logs=1)
    assert score(issue(), c) == 0.9


def test_clear_question_passes():
    c = classification("question", actionable=1, single_topic=1, specific_question=1, shows_effort=1)
    i = issue("How do I change the default output folder?",
              "I read the docs but couldn't find where the output path is configured. "
              "Is there an environment variable for it?")
    assert score(i, c) == 1.0


def test_vague_issue_scores_low():
    # body is exactly 15 words, so only the generic-title penalty applies
    i = issue("it doesnt work", "pls fix asap, lost a lot of money because of this. i want a refund")
    assert score(i, classification("unclear")) == 0.25


def test_vague_bug_is_pulled_below_threshold_by_fixed_rules():
    c = classification("bug", actionable=1, single_topic=1)
    assert score(issue("Login broken", "Login fails"), c) == 0.3


# --- weights ----------------------------------------------------------------------------------

def test_only_the_chosen_categorys_evidence_counts():
    everything = {f: 1 for f in Evidence.model_fields if f != "fits_another_category"}
    as_bug = compute_confidence(issue(), classification("bug", **everything))
    labels = {p.label for p in as_bug.parts}
    assert "has_error_or_logs" in labels
    assert "describes_behaviour" not in labels and "specific_question" not in labels


def test_unclear_gets_no_category_bonus():
    everything = {f: 1 for f in Evidence.model_fields if f != "fits_another_category"}
    labels = {p.label for p in compute_confidence(issue(), classification("unclear", **everything)).parts}
    assert labels == {"base", "actionable", "single_topic"}


def test_ambiguous_category_is_penalised():
    base = classification("bug", actionable=1, single_topic=1)
    ambiguous = classification("bug", actionable=1, single_topic=1, fits_another_category=1)
    assert score(issue(), base) - score(issue(), ambiguous) == pytest.approx(0.25)


def test_score_is_clamped_to_0_1():
    all_yes = classification("bug", **{f: 1 for f in Evidence.model_fields if f != "fits_another_category"})
    assert score(issue(), all_yes) == 1.0
    worst = classification("unclear", fits_another_category=1)
    assert score(issue("bug", "x"), worst) == 0.0


def test_breakdown_explains_the_score():
    c = classification("bug", actionable=1)
    conf = compute_confidence(issue("Login broken", "Login fails"), c)
    assert conf.explain() == "base 0.35 + actionable 0.15 - short body 0.20 - generic title 0.10"
    assert sum(p.delta for p in conf.parts) == pytest.approx(conf.score)


# --- fixed rules ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title, generic",
    [
        ("it doesnt work", True),
        ("It doesn't work!!", True),
        ("HELP", True),
        ("Login broken", True),  # under 4 words
        ("App crashes on start", False),
        ("How do I change the default output folder?", False),
    ],
)
def test_generic_title(title, generic):
    assert is_generic_title(title) is generic


def test_short_body_boundary():
    c = classification("bug")
    fourteen, fifteen = " ".join(["word"] * 14), " ".join(["word"] * 15)
    labels = lambda body: {p.label for p in compute_confidence(issue(body=body), c).parts}
    assert "short body" in labels(fourteen)
    assert "short body" not in labels(fifteen)


@pytest.mark.parametrize(
    "body, mostly_log",
    [
        ("```\nTraceback (most recent call last):\n  File \"a.py\", line 1\nValueError: x\n```", True),
        ("Traceback (most recent call last):\n  File \"a.py\", line 1, in <module>\nValueError: bad", True),
        ("Crashes on upload.\n```\nRangeError: x\n```\n" + "Happens every time with big files. " * 5, False),
        (LONG_BODY, False),
        ("", False),
    ],
)
def test_mostly_log(body, mostly_log):
    assert is_mostly_log(body) is mostly_log


# --- fix: an issue must show category-specific evidence to pass R2 (0.70) ----------------------

THRESHOLD = 0.70


@pytest.mark.parametrize("category", ["bug", "feature", "question", "unclear"])
def test_general_answers_alone_never_pass(category):
    c = classification(category, actionable=1, single_topic=1)
    assert score(issue(), c) == 0.6 < THRESHOLD


@pytest.mark.parametrize(
    "category, fact",
    [("bug", "has_repro_steps"), ("bug", "has_error_or_logs"),
     ("feature", "describes_behaviour"), ("question", "specific_question")],
)
def test_one_strong_category_fact_passes(category, fact):
    c = classification(category, actionable=1, single_topic=1, **{fact: 1})
    assert score(issue(), c) >= THRESHOLD


@pytest.mark.parametrize("fact", ["has_expected_vs_actual", "has_environment"])
def test_one_weak_bug_fact_is_not_enough(fact):
    c = classification("bug", actionable=1, single_topic=1, **{fact: 1})
    assert score(issue(), c) < THRESHOLD


@pytest.mark.parametrize("category", ["bug", "feature", "question"])
def test_every_category_maxes_at_exactly_one(category):
    yes = {f: 1 for f in Evidence.model_fields if f != "fits_another_category"}
    c = classification(category, **yes)
    assert sum(p.delta for p in compute_confidence(issue(), c).parts) == pytest.approx(1.0)
