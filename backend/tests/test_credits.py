"""额度模块测试"""
import pytest
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_get_balance(client):
    headers, _ = await get_auth_headers(client)
    res = await client.get("/api/credits/balance", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "balance" in data
    assert "daily_free_allowance" in data
    assert data["balance"] >= 0


@pytest.mark.asyncio
async def test_get_history(client):
    headers, _ = await get_auth_headers(client)
    res = await client.get("/api/credits/history", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "transactions" in data
    assert "total" in data
