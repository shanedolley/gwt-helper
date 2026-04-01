import pytest
import time
import os
import respx
import httpx
from gwt_worktree_manager.integrations import IssueInfo, IssueCache
from gwt_worktree_manager.integrations.linear import LinearClient, GRAPHQL_ENDPOINT
from gwt_worktree_manager.integrations.ado import ADOClient


# === IssueCache tests ===

class TestIssueCache:
    def test_get_returns_none_for_missing(self):
        cache = IssueCache()
        assert cache.get("linear", "TB-1") is None

    def test_set_and_get(self):
        cache = IssueCache()
        info = IssueInfo(title="Test", status="Done")
        cache.set("linear", "TB-1", info)
        result = cache.get("linear", "TB-1")
        assert result is not None
        assert result.title == "Test"

    def test_different_providers_separate(self):
        cache = IssueCache()
        info_lin = IssueInfo(title="Linear", status="In Progress")
        info_ado = IssueInfo(title="ADO", status="Active")
        cache.set("linear", "TB-1", info_lin)
        cache.set("ado", "TB-1", info_ado)
        assert cache.get("linear", "TB-1").title == "Linear"
        assert cache.get("ado", "TB-1").title == "ADO"

    def test_expired_entry_returns_none(self):
        cache = IssueCache(ttl_seconds=0)  # Immediate expiry
        cache.set("linear", "TB-1", IssueInfo(title="Expired", status="Done"))
        import time
        time.sleep(0.01)
        assert cache.get("linear", "TB-1") is None

    def test_clear(self):
        cache = IssueCache()
        cache.set("linear", "TB-1", IssueInfo(title="X", status="Y"))
        cache.clear()
        assert cache.get("linear", "TB-1") is None


# === LinearClient tests ===

class TestLinearClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_fetch(self):
        respx.post(GRAPHQL_ENDPOINT).mock(
            return_value=httpx.Response(200, json={
                "data": {
                    "issue": {
                        "title": "Add user profile",
                        "state": {"name": "In Progress"},
                        "assignee": {"name": "Shane"},
                        "url": "https://linear.app/issue/TB-123",
                    }
                }
            })
        )
        client = LinearClient("test-key")
        info = await client.get_issue("TB-123")
        assert info is not None
        assert info.title == "Add user profile"
        assert info.status == "In Progress"
        assert info.assignee == "Shane"
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_error_disables(self):
        respx.post(GRAPHQL_ENDPOINT).mock(return_value=httpx.Response(401))
        client = LinearClient("bad-key")
        result = await client.get_issue("TB-1")
        assert result is None
        assert client._disabled is True
        # Subsequent calls should return None without making requests
        result2 = await client.get_issue("TB-2")
        assert result2 is None
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found(self):
        respx.post(GRAPHQL_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": {"issue": None}})
        )
        client = LinearClient("test-key")
        assert await client.get_issue("NONEXIST") is None
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_timeout(self):
        respx.post(GRAPHQL_ENDPOINT).mock(side_effect=httpx.TimeoutException("timeout"))
        client = LinearClient("test-key")
        assert await client.get_issue("TB-1") is None
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit(self):
        respx.post(GRAPHQL_ENDPOINT).mock(return_value=httpx.Response(429))
        client = LinearClient("test-key")
        assert await client.get_issue("TB-1") is None
        assert client._disabled is False  # Should not disable on rate limit
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_cache_hit_skips_api(self):
        cache = IssueCache()
        cache.set("linear", "TB-1", IssueInfo(title="Cached", status="Done"))

        # No mock route — if it makes a request, it will fail
        client = LinearClient("test-key", cache=cache)
        info = await client.get_issue("TB-1")
        assert info is not None
        assert info.title == "Cached"
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_response(self):
        respx.post(GRAPHQL_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"unexpected": "format"})
        )
        client = LinearClient("test-key")
        assert await client.get_issue("TB-1") is None
        await client.close()

    def test_from_config_missing_env_var(self):
        client = LinearClient.from_config("NONEXISTENT_LINEAR_KEY_XYZ")
        assert client is None

    def test_from_config_with_env_var(self):
        os.environ["TEST_LINEAR_KEY"] = "test-key-value"
        try:
            client = LinearClient.from_config("TEST_LINEAR_KEY")
            assert client is not None
        finally:
            del os.environ["TEST_LINEAR_KEY"]


# === ADOClient tests ===

class TestADOClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_fetch(self):
        respx.get("https://dev.azure.com/myorg/_apis/wit/workitems/12345?api-version=7.0").mock(
            return_value=httpx.Response(200, json={
                "fields": {
                    "System.Title": "Fix login bug",
                    "System.State": "Active",
                    "System.AssignedTo": {"displayName": "Shane"},
                },
                "_links": {
                    "html": {"href": "https://dev.azure.com/myorg/proj/_workitems/edit/12345"}
                },
            })
        )
        client = ADOClient("https://dev.azure.com/myorg", "test-pat")
        info = await client.get_work_item("12345")
        assert info is not None
        assert info.title == "Fix login bug"
        assert info.status == "Active"
        assert info.assignee == "Shane"
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_error_disables(self):
        respx.get("https://dev.azure.com/myorg/_apis/wit/workitems/1?api-version=7.0").mock(
            return_value=httpx.Response(403)
        )
        client = ADOClient("https://dev.azure.com/myorg", "bad-pat")
        result = await client.get_work_item("1")
        assert result is None
        assert client._disabled is True
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found(self):
        respx.get("https://dev.azure.com/myorg/_apis/wit/workitems/999?api-version=7.0").mock(
            return_value=httpx.Response(404)
        )
        client = ADOClient("https://dev.azure.com/myorg", "test-pat")
        assert await client.get_work_item("999") is None
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_timeout(self):
        respx.get("https://dev.azure.com/myorg/_apis/wit/workitems/1?api-version=7.0").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        client = ADOClient("https://dev.azure.com/myorg", "pat")
        assert await client.get_work_item("1") is None
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_cache_hit(self):
        cache = IssueCache()
        cache.set("ado", "123", IssueInfo(title="Cached ADO", status="Done"))
        client = ADOClient("https://dev.azure.com/myorg", "pat", cache=cache)
        info = await client.get_work_item("123")
        assert info.title == "Cached ADO"
        await client.close()

    def test_from_config_missing_env(self):
        client = ADOClient.from_config("NONEXIST_ORG", "NONEXIST_PAT")
        assert client is None

    def test_from_config_with_env(self):
        os.environ["TEST_ADO_ORG"] = "https://dev.azure.com/test"
        os.environ["TEST_ADO_PAT"] = "test-pat"
        try:
            client = ADOClient.from_config("TEST_ADO_ORG", "TEST_ADO_PAT")
            assert client is not None
        finally:
            del os.environ["TEST_ADO_ORG"]
            del os.environ["TEST_ADO_PAT"]


# === IssueInfo tests ===

class TestIssueInfo:
    def test_default_fields(self):
        info = IssueInfo(title="Test", status="Open")
        assert info.assignee is None
        assert info.url is None

    def test_all_fields(self):
        info = IssueInfo(title="T", status="S", assignee="A", url="https://example.com")
        assert info.assignee == "A"
        assert info.url == "https://example.com"
