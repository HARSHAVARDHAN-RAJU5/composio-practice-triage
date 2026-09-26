"""GitHub actions through the Composio GitHub toolkit."""
import json
from typing import List, Optional

from composio import Composio
from pydantic import ValidationError

from triage.config import Config
from triage.models import Issue, RepoRef


MAX_PER_PAGE = 100  # GitHub's page size cap
# Pinned so tool input/output shapes can't change under us; bump deliberately
GITHUB_TOOLKIT_VERSION = "20260924_00"
# Invisible in rendered markdown; lets a re-run see we already replied so it never posts twice
BOT_MARKER = "<!-- triage-bot -->"
# Comment authors whose answer means the bot should stay out
MAINTAINER_ROLES = {"OWNER", "MEMBER", "COLLABORATOR"}


class ToolError(Exception):
    pass


def _to_issue(data: dict, repo: RepoRef) -> Issue:
    try:
        return Issue.from_github(data, repo)
    except ValidationError as e:
        number = data.get("number", "?") if isinstance(data, dict) else "?"
        first = e.errors()[0]
        field = ".".join(str(p) for p in first["loc"])
        raise ToolError(
            f"Unexpected issue data from GitHub for #{number} in {repo.full_name}: "
            f"{field}: {first['msg']}"
        ) from None


def _friendly(slug: str, error, repo: RepoRef) -> str:
    """Turn a raw Composio/GitHub error into one readable line."""
    try:
        status = str(json.loads(error).get("status"))
    except (TypeError, ValueError, AttributeError):
        status = ""
    if status == "404":
        what = f"issue #{repo.number}" if repo.number else "repository"
        return f"GitHub {what} not found in {repo.full_name} (or it is private and not accessible)."
    if status in ("401", "403"):
        return f"GitHub refused access to {repo.full_name} ({status}). Check the GitHub connection in Composio."
    return f"{slug} failed for {repo.full_name}: {error}"


class GitHubTools:
    def __init__(self, config: Config):
        self.user_id = config.composio_user_id
        self.client = Composio(
            api_key=config.composio_api_key,
            toolkit_versions={"github": GITHUB_TOOLKIT_VERSION},
        )

    def check_connection(self) -> str:
        """Return the id of the active GitHub connection, or raise ToolError with how to fix it."""
        try:
            resp = self.client.connected_accounts.list(
                user_ids=[self.user_id], toolkit_slugs=["github"], statuses=["ACTIVE"]
            )
        except Exception as e:
            raise ToolError(f"Could not reach Composio (is COMPOSIO_API_KEY right?): {e}") from None
        if not resp.items:
            raise ToolError(
                f"GitHub is not connected in Composio for user '{self.user_id}'. "
                "Connect it at https://platform.composio.dev (Toolkits -> GitHub -> Connect), "
                "or set COMPOSIO_USER_ID to the user id you connected with."
            )
        return resp.items[0].id

    def _execute(self, slug: str, arguments: dict, repo: RepoRef) -> dict:
        try:
            result = self.client.tools.execute(slug, arguments, user_id=self.user_id)
        except Exception as e:
            raise ToolError(f"Could not reach Composio while calling {slug}: {e}") from None
        if not result.get("successful"):
            raise ToolError(_friendly(slug, result.get("error"), repo))
        return result.get("data") or {}

    def get_issue(self, repo: RepoRef) -> Issue:
        data = self._execute(
            "GITHUB_GET_AN_ISSUE",
            {"owner": repo.owner, "repo": repo.repo, "issue_number": repo.number},
            repo,
        )
        if "pull_request" in data:
            raise ToolError(f"#{repo.number} in {repo.full_name} is a pull request, not an issue.")
        return _to_issue(data, repo)

    def list_issues(self, repo: RepoRef, state: str = "open", limit: int = 10) -> List[Issue]:
        """Newest issues first, following pages until `limit` issues are collected."""
        per_page = min(limit, MAX_PER_PAGE)
        issues: List[Issue] = []
        page = 1
        while len(issues) < limit:
            data = self._execute(
                "GITHUB_LIST_REPOSITORY_ISSUES",
                {"owner": repo.owner, "repo": repo.repo, "state": state, "per_page": per_page, "page": page},
                repo,
            )
            if not isinstance(data.get("issues"), list):
                # Never read a changed response shape as "no issues"
                raise ToolError(
                    f"Unexpected response from GITHUB_LIST_REPOSITORY_ISSUES for {repo.full_name}: "
                    f"no 'issues' list (got keys: {sorted(data)})"
                )
            batch = data["issues"]
            # GitHub's issues endpoint also returns pull requests; this bot only triages issues
            issues += [_to_issue(d, repo) for d in batch if "pull_request" not in d]
            if len(batch) < per_page:  # last page
                break
            page += 1
        return issues[:limit]

    def fetch(self, repo: RepoRef, state: str = "open", limit: int = 10) -> List[Issue]:
        """One issue if the target names one, otherwise the repo's issues."""
        if repo.number:
            return [self.get_issue(repo)]
        return self.list_issues(repo, state, limit)

    def skip_reason(self, issue: Issue) -> Optional[str]:
        """Why this issue must not get a bot reply, from its comments; None if it may."""
        if not issue.comments:
            return None  # nothing to look through, save the call
        maintainer = None
        for c in self._comments(issue.ref):
            if BOT_MARKER in (c.get("body") or ""):
                return "already has a reply from this bot"
            author = (c.get("user") or {}).get("login")
            # A maintainer following up on their own issue hasn't answered anyone
            if c.get("author_association") in MAINTAINER_ROLES and author != issue.author:
                maintainer = maintainer or f"a maintainer ({author}, {c['author_association']}) already commented"
        return maintainer

    def _comments(self, ref: RepoRef) -> List[dict]:
        comments, page = [], 1
        while True:
            data = self._execute(
                "GITHUB_LIST_ISSUE_COMMENTS",
                {"owner": ref.owner, "repo": ref.repo, "issue_number": ref.number,
                 "per_page": MAX_PER_PAGE, "page": page},
                ref,
            )
            batch = data.get("comments")
            if not isinstance(batch, list):
                raise ToolError(f"Unexpected response from GITHUB_LIST_ISSUE_COMMENTS for #{ref.number}")
            comments += batch
            if len(batch) < MAX_PER_PAGE:
                return comments
            page += 1

    def post_comment(self, issue: Issue, reply: str) -> str:
        """Post the reply with our hidden marker; return the comment URL."""
        ref = issue.ref
        data = self._execute(
            "GITHUB_CREATE_AN_ISSUE_COMMENT",
            {"owner": ref.owner, "repo": ref.repo, "issue_number": ref.number,
             "body": f"{reply}\n\n{BOT_MARKER}"},
            ref,
        )
        return data.get("html_url") or data.get("url") or ""
