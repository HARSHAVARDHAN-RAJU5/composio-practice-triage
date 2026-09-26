"""Deterministic rules. A reply is posted only if every rule passes; anything else escalates.

Before Gemini (issue only):  R7 open with a body, SECURITY no sensitive topics.
After Gemini:                R1-R6 on the category, computed confidence and drafted reply,
                             R8 no @mentions, other-issue references or /commands in the reply.
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

# Any scheme link, protocol-relative "//host" (e.g. in <a href> / <img src>), and www. links.
# Markdown and HTML links contain one of these too.
LINK = re.compile(r"(?:\b[a-z][a-z0-9+.-]*:)?//[^\s<>\"'()\[\]]+|\bwww\.[^\s<>\"'()\[\]]+", re.IGNORECASE)
LINK_TRAILING = ".,;:!?'\""
# Bare domains ("evil.example/patch"). Curated TLDs: no md/py/sh/json etc., which are file names.
BARE_DOMAIN = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|app|co|xyz|info|me|ai|ly|gg|to|cc|ru|cn|tk|biz|"
    r"site|online|top|link|click|example|us|uk|de|fr|in)\b(?:/[^\s<>\"'()\[\]]*)?",
    re.IGNORECASE,
)

# Things that make GitHub act on other people or places when the comment is posted
MENTION = re.compile(r"(?<![\w`])@[a-z0-9][a-z0-9-]*(?:/[\w.-]+)?", re.IGNORECASE)  # user or @org/team
ISSUE_REF = re.compile(r"(?<![\w/&])(?:#|\bgh-)(\d+)\b", re.IGNORECASE)             # #12, GH-12
CROSS_REF = re.compile(r"\b[\w.-]+/[\w.-]+#\d+\b")                                   # owner/repo#12
SLASH_COMMAND = re.compile(r"^\s*/[a-z][\w-]*", re.IGNORECASE | re.MULTILINE)       # /close, /assign

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
        # https only; the repo itself or any page under it; not e.g. github.com/owner/repo-evil
        if not (lower == repo_url or lower.startswith((repo_url + "/", repo_url + "#", repo_url + "?"))):
            bad.append(url)
    # Bare domains, looked for only outside the links already checked
    bad += [m.group(0).rstrip(LINK_TRAILING) for m in BARE_DOMAIN.finditer(LINK.sub(" ", reply))]
    if bad:
        return RuleResult(rule="R6", passed=False, detail=f"link outside the repo: {', '.join(bad)}")
    return RuleResult(rule="R6", passed=True, detail="no outside links")


def r8_no_side_effects(issue: Issue, reply: str) -> RuleResult:
    """Nothing that notifies people, links other issues, or triggers other bots."""
    found = [m.group(0) for m in MENTION.finditer(reply)]
    found += [m.group(0) for m in ISSUE_REF.finditer(reply) if int(m.group(1)) != issue.number]
    own = f"{issue.repo}#{issue.number}".lower()
    found += [m.group(0) for m in CROSS_REF.finditer(reply) if m.group(0).lower() != own]
    found += [m.group(0).strip() for m in SLASH_COMMAND.finditer(reply)]
    if found:
        return RuleResult(rule="R8", passed=False, detail=f"mention/reference/command: {', '.join(found)}")
    return RuleResult(rule="R8", passed=True, detail="no mentions, references or commands")


def check_triage(issue: Issue, c: Classification, conf: Confidence) -> List[RuleResult]:
    return [
        r1_not_unclear(c),
        r2_confidence(conf),
        r3_reply_length(c.reply),
        r4_mentions_issue(issue, c.reply),
        r5_no_promises(c.reply),
        r6_links_same_repo(issue, c.reply),
        r8_no_side_effects(issue, c.reply),
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
