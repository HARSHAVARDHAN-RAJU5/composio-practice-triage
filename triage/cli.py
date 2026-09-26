"""Entry point.

    python -m triage.cli <owner/repo | owner/repo#12 | repo URL | issue URL>
        [--state open] [--limit 10] [--post] [--fetch-only] [--out-dir .]

Dry run by default: nothing is posted unless --post is given. Every run is written to
log.jsonl, and escalated issues also to escalation.jsonl.
"""
import argparse
import sys
import textwrap
from collections import Counter

from triage.config import ConfigError, load_config
from triage.llm.gemini import Gemini
from triage.pipeline import TriageResult, triage_issue
from triage.tools.github import GitHubTools, ToolError
from triage.tools.records import Recorder
from triage.tools.urls import InvalidTarget, parse_target

MAX_LIMIT = 500  # every fetched issue becomes a Gemini call


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="triage", description="Triage GitHub issues.")
    p.add_argument("target", help="owner/repo, owner/repo#12, repo URL or issue URL")
    p.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p.add_argument("--limit", type=int, default=10, help=f"max issues to fetch (1-{MAX_LIMIT})")
    p.add_argument("--post", action="store_true", help="really post replies (default: dry run)")
    p.add_argument("--fetch-only", action="store_true", help="skip Gemini, just list issues")
    p.add_argument("--out-dir", default=".", help="where log.jsonl and escalation.jsonl go")
    return p


def main(argv=None) -> int:
    # Windows defaults to cp1252 when output is piped/redirected; issue text has emoji etc.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    rec = Recorder(args.out_dir, mode="post" if args.post else "dry-run")

    # Validate input before any network call
    try:
        repo = parse_target(args.target)
    except InvalidTarget as e:
        print(f"Error: {e}")
        rec.run_error(str(e), target=args.target)
        return 2
    if not 1 <= args.limit <= MAX_LIMIT:
        msg = f"--limit must be between 1 and {MAX_LIMIT}"
        print(f"Error: {msg}")
        rec.run_error(msg, repo=repo.full_name, target=args.target)
        return 2

    try:
        config = load_config()
        gh = GitHubTools(config)
        gh.check_connection()
        issues = gh.fetch(repo, state=args.state, limit=args.limit)
    except (ConfigError, ToolError) as e:
        print(f"Error: {e}")
        rec.run_error(str(e), repo=repo.full_name, target=args.target)
        return 1

    mode = "LIVE: replies will be posted" if args.post else "dry run: nothing will be posted"
    print(f"Fetched {len(issues)} issue(s) from {repo.full_name} ({mode})\n")
    llm = None if args.fetch_only else Gemini(config)
    counts = Counter()
    for issue in issues:
        labels = ", ".join(issue.labels) or "none"
        preview = issue.body.replace("\n", " ")[:80] or "(empty body)"
        print(f"#{issue.number} [{issue.state}] {issue.title}")
        print(f"   author: {issue.author} | labels: {labels}")
        print(f"   {preview}")
        if llm:
            counts[handle_issue(issue, llm, gh, rec, args.post)] += 1
        print()

    if llm:
        replies = counts["reply"] + counts["posted"]
        print(f"Summary: {replies} reply ({counts['posted']} posted), {counts['escalate']} escalate, "
              f"{counts['skip']} skipped, {counts['error']} error")
        print(f"Logged to {rec.log_path}" + (f", escalations in {rec.escalation_path}" if counts["escalate"] else ""))
    return 1 if counts["error"] else 0


def handle_issue(issue, llm: Gemini, gh: GitHubTools, rec: Recorder, post: bool) -> str:
    """Triage, post if allowed, record. Returns the counter key."""
    try:
        reason = gh.skip_reason(issue)
        if reason:
            print(f"   => SKIP: {reason}")
            rec.skipped(issue, reason)
            return "skip"
    except ToolError as e:
        # Can't tell if we replied before: don't triage, never risk a double post
        print(f"   => ERROR: {e}")
        rec.result(TriageResult(issue, "error"), "error", error=str(e))
        return "error"

    r = triage_issue(issue, llm)
    print_result(r)

    if r.action != "reply":
        rec.result(r, r.action)
        return r.action
    if not post:
        print("   => REPLY (dry run, not posted)")
        rec.result(r, "reply")
        return "reply"
    try:
        url = gh.post_comment(issue, r.classification.reply)
    except ToolError as e:
        print(f"   => ERROR: reply not posted: {e}")
        rec.result(r, "error", error=f"post failed: {e}")
        return "error"
    print(f"   => REPLIED: {url}")
    rec.result(r, "reply", posted=True, comment_url=url)
    return "posted"


def print_result(r: TriageResult) -> None:
    c = r.classification
    if c:
        retried = " after re-ask" if r.attempts > 1 else ""
        print(f"   category: {c.category}, confidence {r.confidence.score:.2f} via {r.model}{retried}")
        print(f"   score: {r.confidence.explain()}  (gemini said {c.model_confidence:.2f})")
        print(f"   why: {c.reason}")
        print("   reply: " + textwrap.fill(c.reply, width=96, subsequent_indent="          "))

    if r.action == "error":
        print(f"   => ERROR: {r.error}")
    elif r.action == "escalate":
        print("   => ESCALATE: " + "; ".join(f"{f.rule} {f.detail}" for f in r.failed))
    else:
        print("   rules: all passed (" + ", ".join(x.rule for x in r.rules) + ")")


if __name__ == "__main__":
    sys.exit(main())
