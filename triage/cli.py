"""Entry point: python -m triage.cli <owner/repo | issue URL> [--state open] [--limit 10] [--fetch-only]"""
import argparse
import sys
import textwrap
from collections import Counter

from triage.config import ConfigError, load_config
from triage.llm.gemini import Gemini
from triage.pipeline import TriageResult, triage_issue
from triage.tools.github import GitHubTools, ToolError
from triage.tools.urls import InvalidTarget, parse_target

MAX_LIMIT = 500  # every fetched issue becomes a Gemini call later


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="triage", description="Triage GitHub issues.")
    p.add_argument("target", help="owner/repo, owner/repo#12, repo URL or issue URL")
    p.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p.add_argument("--limit", type=int, default=10, help=f"max issues to fetch (1-{MAX_LIMIT})")
    p.add_argument("--fetch-only", action="store_true", help="skip Gemini, just list issues")
    return p


def main(argv=None) -> int:
    # Windows defaults to cp1252 when output is piped/redirected; issue text has emoji etc.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)

    # Validate input before any network call
    try:
        repo = parse_target(args.target)
    except InvalidTarget as e:
        print(f"Error: {e}")
        return 2
    if not 1 <= args.limit <= MAX_LIMIT:
        print(f"Error: --limit must be between 1 and {MAX_LIMIT}")
        return 2

    try:
        config = load_config()
        gh = GitHubTools(config)
        gh.check_connection()
        issues = gh.fetch(repo, state=args.state, limit=args.limit)
    except (ConfigError, ToolError) as e:
        print(f"Error: {e}")
        return 1

    print(f"Fetched {len(issues)} issue(s) from {repo.full_name}\n")
    llm = None if args.fetch_only else Gemini(config)
    counts = Counter()
    for issue in issues:
        labels = ", ".join(issue.labels) or "none"
        preview = issue.body.replace("\n", " ")[:80] or "(empty body)"
        print(f"#{issue.number} [{issue.state}] {issue.title}")
        print(f"   author: {issue.author} | labels: {labels}")
        print(f"   {preview}")
        if llm:
            result = triage_issue(issue, llm)
            counts[result.action] += 1
            print_result(result)
        print()
    if llm:
        print(f"Summary: {counts['reply']} reply, {counts['escalate']} escalate, {counts['error']} error")
    return 0


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
        print("   => REPLY: all rules passed (" + ", ".join(x.rule for x in r.rules) + ")")


if __name__ == "__main__":
    sys.exit(main())
