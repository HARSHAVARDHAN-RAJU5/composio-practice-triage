"""Entry point: python -m triage.cli <owner/repo | issue URL> [--state open] [--limit 10]"""
import argparse
import sys

from triage.config import ConfigError, load_config
from triage.tools.github import GitHubTools, ToolError
from triage.tools.urls import InvalidTarget, parse_target

MAX_LIMIT = 500  # every fetched issue becomes a Gemini call later


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="triage", description="Triage GitHub issues.")
    p.add_argument("target", help="owner/repo, owner/repo#12, repo URL or issue URL")
    p.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p.add_argument("--limit", type=int, default=10, help=f"max issues to fetch (1-{MAX_LIMIT})")
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
    for issue in issues:
        labels = ", ".join(issue.labels) or "none"
        preview = issue.body.replace("\n", " ")[:80] or "(empty body)"
        print(f"#{issue.number} [{issue.state}] {issue.title}")
        print(f"   author: {issue.author} | labels: {labels}")
        print(f"   {preview}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
