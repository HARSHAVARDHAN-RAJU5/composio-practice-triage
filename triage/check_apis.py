"""Smoke test: python -m triage.check_apis"""
import os
import sys

from triage.config import ConfigError, load_config
from triage.llm.gemini import Gemini, LLMError
from triage.tools.github import GitHubTools, ToolError
from triage.tools.urls import InvalidTarget, parse_target


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        config = load_config()
    except ConfigError as e:
        print(f"[FAIL] config: {e}")
        return 1

    ok = True

    print("Composio / GitHub")
    try:
        gh = GitHubTools(config)
        account = gh.check_connection()
        print(f"  [OK] GitHub connected (account {account})")
        repo = parse_target(os.getenv("TEST_REPO", "octocat/Hello-World"))
        issues = gh.list_issues(repo, limit=3)
        print(f"  [OK] fetched {len(issues)} issues from {repo.full_name}")
        for i in issues:
            print(f"       #{i.number} {i.title}")
    except (ToolError, InvalidTarget) as e:
        print(f"  [FAIL] {e}")
        ok = False

    print("Gemini")
    try:
        text, model = Gemini(config).generate("Reply with exactly: pong")
        print(f"  [OK] {model} answered: {text.strip()}")
    except LLMError as e:
        print(f"  [FAIL] {e}")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
