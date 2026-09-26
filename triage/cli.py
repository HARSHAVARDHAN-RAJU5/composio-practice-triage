"""Entry point: python -m triage.cli <owner/repo | issue URL> [--state open] [--limit 10] [--fetch-only]"""
import argparse
import sys
import textwrap

from triage.config import ConfigError, load_config
from triage.llm.classify import classify
from triage.llm.gemini import Gemini, LLMError
from triage.rules.confidence import compute_confidence
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
    for issue in issues:
        labels = ", ".join(issue.labels) or "none"
        preview = issue.body.replace("\n", " ")[:80] or "(empty body)"
        print(f"#{issue.number} [{issue.state}] {issue.title}")
        print(f"   author: {issue.author} | labels: {labels}")
        print(f"   {preview}")
        if llm:
            print_classification(issue, llm)
        print()
    return 0


def print_classification(issue, llm: Gemini) -> None:
    try:
        result = classify(issue, llm)
    except LLMError as e:
        print(f"   ! LLM error: {e}")
        return
    c = result.classification
    if c is None:
        print(f"   ! {result.error} ({result.model})")
        return
    retried = " after re-ask" if result.attempts > 1 else ""
    conf = compute_confidence(issue, c)
    print(f"   -> {c.category}, confidence {conf.score:.2f} via {result.model}{retried}")
    print(f"   score: {conf.explain()}  (gemini said {c.model_confidence:.2f})")
    print(f"   why: {c.reason}")
    print("   reply: " + textwrap.fill(c.reply, width=96, subsequent_indent="          "))


if __name__ == "__main__":
    sys.exit(main())
