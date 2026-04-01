import base64
import httpx
import logging
import os

from gwt_worktree_manager.integrations import IssueInfo, IssueCache

logger = logging.getLogger(__name__)


class ADOClient:
    """Client for the Azure DevOps REST API."""

    def __init__(self, org_url: str, pat: str, cache: IssueCache | None = None):
        auth = base64.b64encode(f":{pat}".encode()).decode()
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            timeout=5.0,
        )
        self._org_url = org_url.rstrip("/")
        self._cache = cache or IssueCache()
        self._disabled = False

    async def get_work_item(self, work_item_id: str) -> IssueInfo | None:
        """Fetch work item by ID (numeric).

        Returns None on any error.
        """
        if self._disabled:
            return None

        cached = self._cache.get("ado", work_item_id)
        if cached is not None:
            return cached

        try:
            url = f"{self._org_url}/_apis/wit/workitems/{work_item_id}?api-version=7.0"
            response = await self._client.get(url)

            if response.status_code in (401, 403):
                logger.warning("ADO API auth failed. Disabling for this session.")
                self._disabled = True
                return None

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                logger.warning("ADO API rate limited.")
                return None

            if response.status_code != 200:
                logger.warning(f"ADO API returned {response.status_code}")
                return None

            data = response.json()
            fields = data.get("fields", {})

            info = IssueInfo(
                title=fields.get("System.Title", ""),
                status=fields.get("System.State", "Unknown"),
                assignee=fields.get("System.AssignedTo", {}).get("displayName") if isinstance(fields.get("System.AssignedTo"), dict) else None,
                url=data.get("_links", {}).get("html", {}).get("href"),
            )

            self._cache.set("ado", work_item_id, info)
            return info

        except httpx.TimeoutException:
            logger.warning(f"ADO API timeout for {work_item_id}")
            return None
        except Exception as e:
            logger.warning(f"ADO API error: {e}")
            return None

    async def close(self) -> None:
        await self._client.aclose()

    @classmethod
    def from_config(cls, org_url_env: str, pat_env: str, cache: IssueCache | None = None) -> "ADOClient | None":
        """Create a client from environment variable names.

        Returns None if either env var is not set.
        """
        org_url = os.environ.get(org_url_env)
        pat = os.environ.get(pat_env)
        if not org_url or not pat:
            return None
        return cls(org_url, pat, cache)
