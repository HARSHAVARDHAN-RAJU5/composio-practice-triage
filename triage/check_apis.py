"""Smoke test: python -m triage.check_apis"""
import os
import sys

from triage.config import ConfigError, load_config
from triage.llm.gemini import Gemini, LLMError
from triage.tools.github import GitHubTools, ToolError


def main() -> int:
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
        test_repo = os.getenv("TEST_REPO", "octocat/Hello-World")
        owner, repo = test_repo.removeprefix("https://github.com/").strip("/").split("/")[:2]
        issues = gh.list_issues(owner, repo, limit=3)
        print(f"  [OK] fetched {len(issues)} issues from {owner}/{repo}")
        for i in issues:
            print(f"       #{i.get('number')} {i.get('title')}")
    except ToolError as e:
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
