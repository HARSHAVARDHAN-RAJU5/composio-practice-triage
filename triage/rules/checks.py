"""Deterministic rules. A reply is posted only if every rule passes; anything else escalates.

Before Gemini (issue only):  R7 open with a body, SECURITY no sensitive topics.
After Gemini:                R1-R6 on the category, computed confidence and drafted reply.
"""
import re
from typing import List

from triage.models import Classification, Confidence, Issue, RuleResult

MIN_CONFIDENCE = 0.70
MIN_REPLY_WORDS = 20
MAX_REPLY_WORDS = 150

# Topics a bot must never handle alone, however clear the issue is
SENSITIVE = re.compile(
    r"\b(refund\w*|money|payments?|paid|charged|billing|invoices?|"
    r"passwords?|tokens?|api[ -]?keys?|secrets?|credentials?|"
    r"cve-\d+|vulnerabilit\w*|exploit\w*|security|hack(ed|ing)?|breach\w*|data leak\w*|"
    r"xss|sql injection)\b",
    re.IGNORECASE,
)

PROMISES = re.compile(
    r"\b(will be fixed|will fix|we'll fix|will get fixed|"
    r"by (tomorrow|today|tonight|next week|the end of the (day|week))|"
    r"guarantee\w*|refund\w*)\b",
    re.IGNORECASE,
)

# http(s) links and www. links (markdown links contain one of these too)
LINK = re.compile(r"(https?://|www\.)[^\s<>()\[\]]+", re.IGNORECASE)
LINK_TRAILING = ".,;:!?'\""

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "when", "what", "how", "why", "can", "does",
    "doesnt", "dont", "not", "are", "was", "has", "have", "you", "your", "our", "but", "any", "all",
    "its", "into", "onto", "than", "then", "there", "about", "after", "before", "work", "works",
    "working", "issue", "problem", "error", "help", "please", "bug", "question", "feature",
}


# --- before Gemini ------------------------------------------------------------------------------

def r7_open_with_body(issue: Issue) -> RuleResult:
    if issue.state != "open":
        return RuleResult(rule="R7", passed=False, detail=f"issue is {issue.state}")
    if not issue.body.strip():
        return RuleResult(rule="R7", passed=False, detail="issue body is empty")
    return RuleResult(rule="R7", passed=True, detail="open, has body")


def security_check(issue: Issue) -> RuleResult:
    found = sorted({m.group(0).lower() for m in SENSITIVE.finditer(f"{issue.title}\n{issue.body}")})
    if found:
        return RuleResult(rule="SECURITY", passed=False, detail=f"sensitive topic: {', '.join(found)}")
    return RuleResult(rule="SECURITY", passed=True, detail="no sensitive topics")


def check_issue(issue: Issue) -> List[RuleResult]:
    return [r7_open_with_body(issue), security_check(issue)]


# --- after Gemini -------------------------------------------------------------------------------

def r1_not_unclear(c: Classification) -> RuleResult:
    if c.category == "unclear":
        return RuleResult(rule="R1", passed=False, detail="category is unclear")
    return RuleResult(rule="R1", passed=True, detail=f"category is {c.category}")


def r2_confidence(conf: Confidence) -> RuleResult:
    passed = conf.score >= MIN_CONFIDENCE
    op = ">=" if passed else "<"
    return RuleResult(rule="R2", passed=passed, detail=f"confidence {conf.score:.2f} {op} {MIN_CONFIDENCE:.2f}")


def r3_reply_length(reply: str) -> RuleResult:
    words = len(reply.split())
    passed = MIN_REPLY_WORDS <= words <= MAX_REPLY_WORDS
    return RuleResult(
        rule="R3", passed=passed,
        detail=f"reply is {words} words ({'within' if passed else 'outside'} {MIN_REPLY_WORDS}-{MAX_REPLY_WORDS})",
    )


def r4_mentions_issue(issue: Issue, reply: str) -> RuleResult:
    if re.search(rf"(#|\bissue\s+){issue.number}\b", reply, re.IGNORECASE):
        return RuleResult(rule="R4", passed=True, detail=f"mentions #{issue.number}")
    reply_words = {_singular(w) for w in _words(reply)}
    shared = [w for w in title_keywords(issue.title) if _singular(w) in reply_words]
    if shared:
        return RuleResult(rule="R4", passed=True, detail=f"uses title word '{shared[0]}'")
    return RuleResult(rule="R4", passed=False, detail=f"no #{issue.number} and no title keyword")


def r5_no_promises(reply: str) -> RuleResult:
    found = sorted({m.group(0).lower() for m in PROMISES.finditer(reply)})
    if found:
        return RuleResult(rule="R5", passed=False, detail=f"promise: {', '.join(found)}")
    return RuleResult(rule="R5", passed=True, detail="no promises")


def r6_links_same_repo(issue: Issue, reply: str) -> RuleResult:
    repo_url = f"https://github.com/{issue.repo}".lower()
    bad = []
    for m in LINK.finditer(reply):
        url = m.group(0).rstrip(LINK_TRAILING)
        lower = url.lower()
        # the repo itself, or any page under it; not e.g. github.com/owner/repo-evil
        if not (lower == repo_url or lower.startswith((repo_url + "/", repo_url + "#", repo_url + "?"))):
            bad.append(url)
    if bad:
        return RuleResult(rule="R6", passed=False, detail=f"link outside the repo: {', '.join(bad)}")
    return RuleResult(rule="R6", passed=True, detail="no outside links")


def check_triage(issue: Issue, c: Classification, conf: Confidence) -> List[RuleResult]:
    return [
        r1_not_unclear(c),
        r2_confidence(conf),
        r3_reply_length(c.reply),
        r4_mentions_issue(issue, c.reply),
        r5_no_promises(c.reply),
        r6_links_same_repo(issue, c.reply),
    ]


# --- helpers ------------------------------------------------------------------------------------

def title_keywords(title: str) -> List[str]:
    return [w for w in _words(title) if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()]


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", "").replace("’", ""))


def _singular(word: str) -> str:
    # crude, enough for matching "crash"/"crashes" and "file"/"files"
    if word.endswith("es") and word[:-2].endswith(("sh", "ch", "x", "ss", "z")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word
