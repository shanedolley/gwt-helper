from dataclasses import dataclass
import time


@dataclass
class IssueInfo:
    """Issue/work item info from an external tracker."""

    title: str
    status: str
    assignee: str | None = None
    url: str | None = None


class IssueCache:
    """In-memory TTL cache for issue lookups.

    Keyed by (provider, issue_id). Session-scoped (resets on restart).
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[tuple[str, str], tuple[IssueInfo, float]] = {}
        self.ttl = ttl_seconds

    def get(self, provider: str, issue_id: str) -> IssueInfo | None:
        key = (provider, issue_id)
        if key in self._cache:
            info, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return info
            del self._cache[key]
        return None

    def set(self, provider: str, issue_id: str, info: IssueInfo) -> None:
        self._cache[(provider, issue_id)] = (info, time.time())

    def clear(self) -> None:
        self._cache.clear()
