import pytest
from httpx import AsyncClient

from netwatch.config import settings


@pytest.mark.asyncio
async def test_healthz_unauthenticated(async_client: AsyncClient) -> None:
    """Verifies that the /healthz endpoint is accessible without an API key."""
    res = await async_client.get("/healthz")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["replica_id"] == settings.replica_id


@pytest.mark.asyncio
async def test_metrics_unauthenticated(async_client: AsyncClient) -> None:
    """Verifies that the /metrics Prometheus endpoint is accessible without an API key."""
    res = await async_client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(async_client: AsyncClient) -> None:
    """Verifies that requests missing the X-API-Key header receive 401 Unauthorized."""
    res = await async_client.get("/api/targets")
    assert res.status_code == 401
    assert "Missing X-API-Key header" in res.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401(async_client: AsyncClient) -> None:
    """Verifies that requests with an unrecognized API key receive 401 Unauthorized."""
    res = await async_client.get("/api/targets", headers={"X-API-Key": "invalid-secret-key"})
    assert res.status_code == 401
    assert "Invalid API key" in res.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_can_read_targets(async_client: AsyncClient) -> None:
    """Verifies that viewer role has read permission to list targets."""
    headers = {"X-API-Key": settings.viewer_api_key}
    res = await async_client.get("/api/targets", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)


@pytest.mark.asyncio
async def test_viewer_cannot_post_target(async_client: AsyncClient) -> None:
    """Verifies that viewer role receives 403 Forbidden when attempting to create a target."""
    headers = {"X-API-Key": settings.viewer_api_key}
    payload = {"host": "example.com", "port": 443, "interval_s": 30}
    res = await async_client.post("/api/targets", json=payload, headers=headers)
    assert res.status_code == 403
    assert "admin role required" in res.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_cannot_delete_target(async_client: AsyncClient) -> None:
    """Verifies that viewer role receives 403 Forbidden when attempting to delete a target."""
    headers = {"X-API-Key": settings.viewer_api_key}
    res = await async_client.delete("/api/targets/1", headers=headers)
    assert res.status_code == 403
    assert "admin role required" in res.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_create_and_delete_target(async_client: AsyncClient) -> None:
    """Verifies that admin role can successfully register, query, and remove targets."""
    headers = {"X-API-Key": settings.admin_api_key}
    payload = {"host": "gateway.internal", "port": 8443, "interval_s": 15, "enabled": True}

    # 1. Create target
    create_res = await async_client.post("/api/targets", json=payload, headers=headers)
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["host"] == "gateway.internal"
    assert created["port"] == 8443
    target_id = created["id"]

    # 2. Verify target appears in list
    list_res = await async_client.get("/api/targets", headers=headers)
    assert list_res.status_code == 200
    assert any(t["id"] == target_id for t in list_res.json())

    # 3. Delete target
    del_res = await async_client.delete(f"/api/targets/{target_id}", headers=headers)
    assert del_res.status_code == 204


@pytest.mark.asyncio
async def test_target_validation_errors(async_client: AsyncClient) -> None:
    """Verifies input validation rejects URI schemes, invalid ports, and out-of-range intervals."""
    headers = {"X-API-Key": settings.admin_api_key}

    # Invalid host containing scheme
    res1 = await async_client.post(
        "/api/targets", json={"host": "https://bad.host", "port": 443}, headers=headers
    )
    assert res1.status_code == 422

    # Port out of range (65536)
    res2 = await async_client.post(
        "/api/targets", json={"host": "valid.host", "port": 70000}, headers=headers
    )
    assert res2.status_code == 422

    # Interval too low (< 10)
    res3 = await async_client.post(
        "/api/targets", json={"host": "valid.host", "interval_s": 5}, headers=headers
    )
    assert res3.status_code == 422
