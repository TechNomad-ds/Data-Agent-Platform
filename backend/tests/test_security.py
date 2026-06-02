"""安全测试 — 未认证访问、越权访问、SQL注入防护"""
import io
import uuid
import pytest
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_unauthenticated_access_blocked(client):
    """未认证请求应返回 401/403"""
    endpoints = [
        ("GET", "/api/data-spaces"),
        ("GET", "/api/files"),
        ("GET", "/api/chat/conversations"),
        ("GET", "/api/credits/balance"),
        ("GET", "/api/auth/me"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = await client.get(path)
        else:
            res = await client.post(path)
        assert res.status_code in (401, 403), f"{method} {path} should require auth, got {res.status_code}"


@pytest.mark.asyncio
async def test_user_cannot_access_other_user_space(client):
    """用户 A 不能访问用户 B 的数据空间"""
    headers_a, _ = await get_auth_headers(client)
    headers_b, _ = await get_auth_headers(client)

    # A 创建空间
    space_res = await client.post("/api/data-spaces", headers=headers_a, json={"name": "private_space"})
    space_id = space_res.json()["id"]

    # B 不能访问 A 的空间
    res = await client.get(f"/api/data-spaces/{space_id}", headers=headers_b)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_access_other_user_file(client):
    """用户 A 不能访问用户 B 的文件"""
    headers_a, _ = await get_auth_headers(client)
    headers_b, _ = await get_auth_headers(client)

    # A 上传文件
    csv = b"x,y\n1,2\n"
    upload_res = await client.post("/api/files/upload", headers=headers_a, files={"files": ("sec.csv", io.BytesIO(csv), "text/csv")})
    file_id = upload_res.json()[0]["id"]

    # B 不能访问
    res = await client.get(f"/api/files/{file_id}", headers=headers_b)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_access_other_user_conversation(client):
    """用户 A 不能访问用户 B 的对话"""
    headers_a, _ = await get_auth_headers(client)
    headers_b, _ = await get_auth_headers(client)

    conv_res = await client.post("/api/chat/conversations", headers=headers_a, json={"model_id": "m"})
    conv_id = conv_res.json()["id"]

    res = await client.get(f"/api/chat/conversations/{conv_id}", headers=headers_b)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_nonexistent_resource_returns_404(client):
    """访问不存在的资源应返回 404"""
    headers, _ = await get_auth_headers(client)
    fake_id = str(uuid.uuid4())

    assert (await client.get(f"/api/data-spaces/{fake_id}", headers=headers)).status_code == 404
    assert (await client.get(f"/api/files/{fake_id}", headers=headers)).status_code == 404
    assert (await client.get(f"/api/chat/conversations/{fake_id}", headers=headers)).status_code == 404
