"""智能建议测试"""
import pytest
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_get_suggestions(client):
    headers, _ = await get_auth_headers(client)
    space_res = await client.post("/api/data-spaces", headers=headers, json={"name": "sug_space"})
    space_id = space_res.json()["id"]

    res = await client.get(f"/api/data-spaces/{space_id}/suggestions", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "suggestions" in data
    assert len(data["suggestions"]) > 0


@pytest.mark.asyncio
async def test_suggestions_nonexistent_space(client):
    headers, _ = await get_auth_headers(client)
    import uuid
    res = await client.get(f"/api/data-spaces/{uuid.uuid4()}/suggestions", headers=headers)
    assert res.status_code == 404
