"""文件管理测试 — 上传、列表、详情、下载、删除"""
import io
import pytest
from tests.conftest import get_auth_headers


@pytest.mark.asyncio
async def test_upload_file(client):
    headers, _ = await get_auth_headers(client)
    csv = b"col1,col2\n1,2\n3,4\n"
    files = {"files": ("data.csv", io.BytesIO(csv), "text/csv")}
    res = await client.post("/api/files/upload", headers=headers, files=files)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["filename"] == "data.csv"


@pytest.mark.asyncio
async def test_upload_unsupported_extension(client):
    headers, _ = await get_auth_headers(client)
    files = {"files": ("malware.exe", io.BytesIO(b"bad"), "application/octet-stream")}
    res = await client.post("/api/files/upload", headers=headers, files=files)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_list_files(client):
    headers, _ = await get_auth_headers(client)
    csv = b"a,b\n1,2\n"
    await client.post("/api/files/upload", headers=headers, files={"files": ("f1.csv", io.BytesIO(csv), "text/csv")})
    await client.post("/api/files/upload", headers=headers, files={"files": ("f2.csv", io.BytesIO(csv), "text/csv")})

    res = await client.get("/api/files", headers=headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 2


@pytest.mark.asyncio
async def test_get_file_detail(client):
    headers, _ = await get_auth_headers(client)
    csv = b"x,y\n1,2\n"
    upload_res = await client.post("/api/files/upload", headers=headers, files={"files": ("detail.csv", io.BytesIO(csv), "text/csv")})
    file_id = upload_res.json()[0]["id"]

    res = await client.get(f"/api/files/{file_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["filename"] == "detail.csv"


@pytest.mark.asyncio
async def test_download_file(client):
    headers, _ = await get_auth_headers(client)
    csv = b"download,test\n1,2\n"
    upload_res = await client.post("/api/files/upload", headers=headers, files={"files": ("dl.csv", io.BytesIO(csv), "text/csv")})
    file_id = upload_res.json()[0]["id"]

    res = await client.get(f"/api/files/{file_id}/download", headers=headers)
    assert res.status_code == 200
    assert b"download,test" in res.content


@pytest.mark.asyncio
async def test_delete_file(client):
    headers, _ = await get_auth_headers(client)
    csv = b"del,me\n1,2\n"
    upload_res = await client.post("/api/files/upload", headers=headers, files={"files": ("todel.csv", io.BytesIO(csv), "text/csv")})
    file_id = upload_res.json()[0]["id"]

    res = await client.delete(f"/api/files/{file_id}", headers=headers)
    assert res.status_code == 204

    get_res = await client.get(f"/api/files/{file_id}", headers=headers)
    assert get_res.status_code == 404
