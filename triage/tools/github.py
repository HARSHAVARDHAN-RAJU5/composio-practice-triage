"""GitHub actions through the Composio GitHub toolkit."""
from composio import Composio

from triage.config import Config


class ToolError(Exception):
    pass


class GitHubTools:
    def __init__(self, config: Config):
        self.user_id = config.composio_user_id
        self.client = Composio(api_key=config.composio_api_key)

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

    def _execute(self, slug: str, arguments: dict) -> dict:
        try:
            result = self.client.tools.execute(
                slug,
                arguments,
                user_id=self.user_id,
                dangerously_skip_version_check=True,
            )
        except Exception as e:
            raise ToolError(f"{slug} failed: {e}") from None
        if not result.get("successful"):
            raise ToolError(f"{slug} failed: {result.get('error')}")
        return result.get("data") or {}

    def list_issues(self, owner: str, repo: str, state: str = "open", limit: int = 10) -> list:
        data = self._execute(
            "GITHUB_LIST_REPOSITORY_ISSUES",
            {"owner": owner, "repo": repo, "state": state, "per_page": limit},
        )
        return data.get("details") or data.get("issues") or []
