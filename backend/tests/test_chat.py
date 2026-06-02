"""对话模块测试 — 创建、列表、详情、重命名、删除"""
import pytest
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_create_conversation(client):
    headers, _ = await get_auth_headers(client)
    res = await client.post("/api/chat/conversations", headers=headers, json={
        "model_id": "test-model",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["model_id"] == "test-model"
    assert data["data_space_id"] is None


@pytest.mark.asyncio
async def test_create_conversation_with_space(client):
    headers, _ = await get_auth_headers(client)
    space_res = await client.post("/api/data-spaces", headers=headers, json={"name": "chat_space"})
    space_id = space_res.json()["id"]

    res = await client.post("/api/chat/conversations", headers=headers, json={
        "data_space_id": space_id,
        "model_id": "test-model",
    })
    assert res.status_code == 201
    assert res.json()["data_space_id"] == space_id


@pytest.mark.asyncio
async def test_create_conversation_invalid_space(client):
    headers, _ = await get_auth_headers(client)
    import uuid
    res = await client.post("/api/chat/conversations", headers=headers, json={
        "data_space_id": str(uuid.uuid4()),
        "model_id": "test-model",
    })
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_list_conversations(client):
    headers, _ = await get_auth_headers(client)
    await client.post("/api/chat/conversations", headers=headers, json={"model_id": "m1"})
    await client.post("/api/chat/conversations", headers=headers, json={"model_id": "m2"})

    res = await client.get("/api/chat/conversations", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) >= 2


@pytest.mark.asyncio
async def test_get_conversation_detail(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/chat/conversations", headers=headers, json={"model_id": "m1", "title": "test_conv"})
    conv_id = create_res.json()["id"]

    res = await client.get(f"/api/chat/conversations/{conv_id}", headers=headers)
    assert res.status_code == 200
    assert "messages" in res.json()


@pytest.mark.asyncio
async def test_rename_conversation(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/chat/conversations", headers=headers, json={"model_id": "m1"})
    conv_id = create_res.json()["id"]

    res = await client.patch(f"/api/chat/conversations/{conv_id}", headers=headers, json={"title": "新标题"})
    assert res.status_code == 200
    assert res.json()["title"] == "新标题"


@pytest.mark.asyncio
async def test_delete_conversation(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/chat/conversations", headers=headers, json={"model_id": "m1"})
    conv_id = create_res.json()["id"]

    res = await client.delete(f"/api/chat/conversations/{conv_id}", headers=headers)
    assert res.status_code == 204

    get_res = await client.get(f"/api/chat/conversations/{conv_id}", headers=headers)
    assert get_res.status_code == 404
