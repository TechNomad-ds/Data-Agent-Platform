"""健康检查测试"""
import pytest


@pytest.mark.asyncio
async def test_health_check(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "version" in data
    assert "database" in data
    assert "redis" in data
