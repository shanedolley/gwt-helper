import httpx
import logging
import os

from gwt_worktree_manager.integrations import IssueInfo, IssueCache

logger = logging.getLogger(__name__)

GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"

ISSUE_QUERY = """
query IssueByIdentifier($identifier: String!) {
  issueByIdentifier(identifier: $identifier) {
    title
    state {
      name
    }
    assignee {
      name
    }
    url
  }
}
"""


class LinearClient:
    """Client for the Linear GraphQL API."""

    def __init__(self, api_key: str, cache: IssueCache | None = None):
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=5.0,
        )
        self._cache = cache or IssueCache()
        self._disabled = False  # Set True on auth failure

    async def get_issue(self, issue_id: str) -> IssueInfo | None:
        """Fetch issue info by identifier (e.g., 'TB-123').

        Returns None on any error (auth, not found, timeout).
        Disables itself for the session on auth errors.
        """
        if self._disabled:
            return None

        # Check cache
        cached = self._cache.get("linear", issue_id)
        if cached is not None:
            return cached

        try:
            response = await self._client.post(
                GRAPHQL_ENDPOINT,
                json={
                    "query": ISSUE_QUERY,
                    "variables": {"identifier": issue_id},
                },
            )

            if response.status_code in (401, 403):
                logger.warning("Linear API auth failed. Disabling for this session.")
                self._disabled = True
                return None

            if response.status_code == 429:
                logger.warning("Linear API rate limited.")
                return None

            if response.status_code != 200:
                logger.warning(f"Linear API returned {response.status_code}")
                return None

            data = response.json()
            issue_data = data.get("data", {}).get("issueByIdentifier")
            if issue_data is None:
                return None

            info = IssueInfo(
                title=issue_data.get("title", ""),
                status=issue_data.get("state", {}).get("name", "Unknown"),
                assignee=issue_data.get("assignee", {}).get("name") if issue_data.get("assignee") else None,
                url=issue_data.get("url"),
            )

            self._cache.set("linear", issue_id, info)
            return info

        except httpx.TimeoutException:
            logger.warning(f"Linear API timeout for {issue_id}")
            return None
        except Exception as e:
            logger.warning(f"Linear API error: {e}")
            return None

    async def close(self) -> None:
        await self._client.aclose()

    @classmethod
    def from_config(cls, api_key_env: str, cache: IssueCache | None = None) -> "LinearClient | None":
        """Create a client from an environment variable name.

        Returns None if the env var is not set.
        """
        api_key = os.environ.get(api_key_env)
        if not api_key:
            return None
        return cls(api_key, cache)
