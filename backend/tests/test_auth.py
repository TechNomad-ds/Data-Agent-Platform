"""认证模块测试 — 注册、登录、Token刷新、密码修改、资料修改"""
import pytest
from tests.conftest import register_user, login_user, get_auth_headers


@pytest.mark.asyncio
async def test_register_success(client):
    res = await register_user(client, email="new@example.com", username="newuser")
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "new@example.com"
    assert data["username"] == "newuser"
    assert data["role"] in ("user", "admin")
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await register_user(client, email="dup@example.com", username="user1")
    res = await register_user(client, email="dup@example.com", username="user2")
    assert res.status_code == 400
    assert "已被注册" in res.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_username(client):
    await register_user(client, email="a1@example.com", username="samename")
    res = await register_user(client, email="a2@example.com", username="samename")
    assert res.status_code == 400
    assert "已被使用" in res.json()["detail"]


@pytest.mark.asyncio
async def test_register_invalid_email(client):
    res = await client.post("/api/auth/register", json={
        "email": "not-an-email",
        "username": "testuser",
        "password": "Test123456",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password(client):
    res = await client.post("/api/auth/register", json={
        "email": "short@example.com",
        "username": "shortpw",
        "password": "12345",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client):
    await register_user(client, email="login@example.com")
    res = await login_user(client, email="login@example.com")
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await register_user(client, email="wrongpw@example.com")
    res = await login_user(client, email="wrongpw@example.com", password="WrongPassword")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    res = await login_user(client, email="noexist@example.com")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client):
    await register_user(client, email="refresh@example.com")
    login_res = await login_user(client, email="refresh@example.com")
    refresh_token = login_res.json()["refresh_token"]

    res = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    res = await client.post("/api/auth/refresh", json={"refresh_token": "invalid.token.here"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client):
    headers, email = await get_auth_headers(client)
    res = await client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["email"] == email


@pytest.mark.asyncio
async def test_change_password(client):
    headers, email = await get_auth_headers(client, password="OldPass123")
    res = await client.put("/api/auth/password", headers=headers, json={
        "old_password": "OldPass123",
        "new_password": "NewPass456",
    })
    assert res.status_code == 200

    # 用新密码登录
    res2 = await login_user(client, email=email, password="NewPass456")
    assert res2.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_old(client):
    headers, _ = await get_auth_headers(client)
    res = await client.put("/api/auth/password", headers=headers, json={
        "old_password": "WrongOld",
        "new_password": "NewPass456",
    })
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_update_profile(client):
    headers, _ = await get_auth_headers(client)
    res = await client.put("/api/auth/profile", headers=headers, json={
        "username": "updated_name",
    })
    assert res.status_code == 200
    assert res.json()["username"] == "updated_name"
