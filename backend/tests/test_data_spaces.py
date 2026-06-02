"""数据空间测试 — CRUD、文件上传、关联管理"""
import io
import pytest
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_create_space(client):
    headers, _ = await get_auth_headers(client)
    res = await client.post("/api/data-spaces", headers=headers, json={
        "name": "销售分析",
        "description": "Q2 销售数据",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "销售分析"
    assert data["file_count"] == 0


@pytest.mark.asyncio
async def test_create_duplicate_name(client):
    headers, _ = await get_auth_headers(client)
    await client.post("/api/data-spaces", headers=headers, json={"name": "dup_space"})
    res = await client.post("/api/data-spaces", headers=headers, json={"name": "dup_space"})
    assert res.status_code == 400
    assert "同名" in res.json()["detail"]


@pytest.mark.asyncio
async def test_list_spaces(client):
    headers, _ = await get_auth_headers(client)
    await client.post("/api/data-spaces", headers=headers, json={"name": "space_a"})
    await client.post("/api/data-spaces", headers=headers, json={"name": "space_b"})
    res = await client.get("/api/data-spaces", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) >= 2


@pytest.mark.asyncio
async def test_get_space_detail(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "detail_space"})
    space_id = create_res.json()["id"]

    res = await client.get(f"/api/data-spaces/{space_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["name"] == "detail_space"
    assert "files" in res.json()


@pytest.mark.asyncio
async def test_update_space(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "old_name"})
    space_id = create_res.json()["id"]

    res = await client.put(f"/api/data-spaces/{space_id}", headers=headers, json={"name": "new_name"})
    assert res.status_code == 200
    assert res.json()["name"] == "new_name"


@pytest.mark.asyncio
async def test_delete_space(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "to_delete"})
    space_id = create_res.json()["id"]

    res = await client.delete(f"/api/data-spaces/{space_id}", headers=headers)
    assert res.status_code == 204

    get_res = await client.get(f"/api/data-spaces/{space_id}", headers=headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_upload_csv_to_space(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "upload_space"})
    space_id = create_res.json()["id"]

    csv_content = b"name,age,city\nAlice,30,Beijing\nBob,25,Shanghai\n"
    files = {"files": ("test.csv", io.BytesIO(csv_content), "text/csv")}
    res = await client.post(f"/api/data-spaces/{space_id}/upload", headers=headers, files=files)
    assert res.status_code == 201
    data = res.json()
    assert len(data) == 1
    assert data[0]["filename"] == "test.csv"
    assert data[0]["file_type"] == "csv"


@pytest.mark.asyncio
async def test_upload_unsupported_type(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "bad_upload"})
    space_id = create_res.json()["id"]

    files = {"files": ("virus.exe", io.BytesIO(b"bad content"), "application/octet-stream")}
    res = await client.post(f"/api/data-spaces/{space_id}/upload", headers=headers, files=files)
    assert res.status_code == 400
    assert "不支持" in res.json()["detail"]


@pytest.mark.asyncio
async def test_processing_status(client):
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "status_space"})
    space_id = create_res.json()["id"]

    res = await client.get(f"/api/data-spaces/{space_id}/processing-status", headers=headers)
    assert res.status_code == 200
    assert "total_files" in res.json()
