"""数据空间测试 — CRUD、文件上传、关联管理"""
import io
import pytest
import pandas as pd
from sqlalchemy import select
from tests.conftest import get_auth_headers, _test_session_factory
from app.models.user import User


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
async def test_upload_pptx_to_space(client):
    pptx = pytest.importorskip("pptx")
    headers, _ = await get_auth_headers(client)
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "slides_space"})
    space_id = create_res.json()["id"]

    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "计算机体系结构"
    slide.placeholders[1].text = "流水线、缓存局部性、指令级并行"
    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)

    files = {
        "files": (
            "architecture.pptx",
            buf,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    }
    res = await client.post(f"/api/data-spaces/{space_id}/upload", headers=headers, files=files)
    assert res.status_code == 201
    data = res.json()
    assert len(data) == 1
    assert data[0]["filename"] == "architecture.pptx"
    assert data[0]["file_type"] == "pptx"


@pytest.mark.asyncio
async def test_upload_multisheet_excel_expands_to_sql_tables(client, db_session, monkeypatch):
    """报告中的核心回归：一个 xlsx 的多个 sheet 必须都进入 SQL 层。"""
    pytest.importorskip("openpyxl")
    headers, email = await get_auth_headers(client)
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    create_res = await client.post("/api/data-spaces", headers=headers, json={"name": "multisheet_sql_space"})
    space_id = create_res.json()["id"]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as writer:
        pd.DataFrame({"course_id": ["C001"], "course_name": ["线性代数"]}).to_excel(
            writer, sheet_name="课程目录", index=False
        )
        pd.DataFrame({"student_id": ["S001"], "course_id": ["C001"]}).to_excel(
            writer, sheet_name="报名记录", index=False
        )
        pd.DataFrame({"student_id": ["S001"], "minutes": [80]}).to_excel(
            writer, sheet_name="学习日志", index=False
        )
    buf.seek(0)

    files = {
        "files": (
            "online_course_ops_multisheet.xlsx",
            buf,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    res = await client.post(f"/api/data-spaces/{space_id}/upload", headers=headers, files=files)
    assert res.status_code == 201

    import app.services.sqlite_engine as sqlite_engine

    monkeypatch.setattr(sqlite_engine, "get_session_factory", lambda: _test_session_factory)
    sqlite_engine.invalidate_cache(space_id)
    db_path = await sqlite_engine.load_space_to_sqlite(space_id, user.id)
    tables = sqlite_engine.list_tables(db_path)
    table_names = {t["name"] for t in tables}
    assert {
        "online_course_ops_multisheet__课程目录",
        "online_course_ops_multisheet__报名记录",
        "online_course_ops_multisheet__学习日志",
    }.issubset(table_names)

    joined = sqlite_engine.execute_query(
        db_path,
        'SELECT c.course_name, e.student_id, l.minutes '
        'FROM "online_course_ops_multisheet__课程目录" c '
        'JOIN "online_course_ops_multisheet__报名记录" e ON e.course_id = c.course_id '
        'JOIN "online_course_ops_multisheet__学习日志" l ON l.student_id = e.student_id',
    )
    assert joined["row_count"] == 1
    assert joined["rows"][0]["course_name"] == "线性代数"
    assert joined["rows"][0]["minutes"] == 80


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
