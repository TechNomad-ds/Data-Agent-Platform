"""数据空间路由 - CRUD、文件关联、索引管理"""
import uuid
import io
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File as FastAPIFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.file import File
from app.models.data_space import DataSpace, DataSpaceFile
from app.schemas.data_space import (
    DataSpaceCreate, DataSpaceUpdate, DataSpaceResponse,
    DataSpaceDetailResponse, FileInSpace, AddFilesRequest,
)
from app.schemas.file import FileResponse
from app.config import settings
from app.routers.files import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, get_file_type, get_user_storage_path, _is_junk_path

router = APIRouter()


@router.post("", response_model=DataSpaceResponse, status_code=201)
async def create_data_space(
    data: DataSpaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建数据空间"""
    # 检查同名
    result = await db.execute(
        select(DataSpace).where(DataSpace.user_id == current_user.id, DataSpace.name == data.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="已存在同名数据空间")

    space = DataSpace(user_id=current_user.id, name=data.name, description=data.description)
    db.add(space)
    await db.flush()

    return DataSpaceResponse(
        id=space.id, name=space.name, description=space.description,
        index_status=space.index_status, file_count=0,
        created_at=space.created_at, updated_at=space.updated_at,
    )


@router.get("", response_model=list[DataSpaceResponse])
async def list_data_spaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的数据空间列表"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.user_id == current_user.id).order_by(DataSpace.updated_at.desc())
    )
    spaces = result.scalars().all()

    # 查询每个空间的文件数
    responses = []
    for space in spaces:
        count_result = await db.execute(
            select(func.count()).select_from(DataSpaceFile).where(DataSpaceFile.data_space_id == space.id)
        )
        file_count = count_result.scalar()
        responses.append(DataSpaceResponse(
            id=space.id, name=space.name, description=space.description,
            index_status=space.index_status, file_count=file_count,
            created_at=space.created_at, updated_at=space.updated_at,
        ))

    return responses


@router.get("/{space_id}", response_model=DataSpaceDetailResponse)
async def get_data_space(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取数据空间详情（含文件列表）"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="数据空间不存在")

    # 查询关联文件
    file_result = await db.execute(
        select(File, DataSpaceFile.added_at)
        .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
        .where(DataSpaceFile.data_space_id == space_id)
        .order_by(DataSpaceFile.added_at.desc())
    )
    files_in_space = [
        FileInSpace(
            file_id=f.id, filename=f.filename,
            file_type=f.file_type, file_size=f.file_size, added_at=added_at,
        )
        for f, added_at in file_result.all()
    ]

    return DataSpaceDetailResponse(
        id=space.id, name=space.name, description=space.description,
        index_status=space.index_status, file_count=len(files_in_space),
        created_at=space.created_at, updated_at=space.updated_at,
        files=files_in_space,
    )


@router.put("/{space_id}", response_model=DataSpaceResponse)
async def update_data_space(
    space_id: uuid.UUID,
    data: DataSpaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新数据空间"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="数据空间不存在")

    if data.name is not None:
        space.name = data.name
    if data.description is not None:
        space.description = data.description

    count_result = await db.execute(
        select(func.count()).select_from(DataSpaceFile).where(DataSpaceFile.data_space_id == space.id)
    )
    file_count = count_result.scalar()

    return DataSpaceResponse(
        id=space.id, name=space.name, description=space.description,
        index_status=space.index_status, file_count=file_count,
        created_at=space.created_at, updated_at=space.updated_at,
    )


@router.delete("/{space_id}", status_code=204)
async def delete_data_space(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除数据空间"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="数据空间不存在")

    await db.delete(space)


@router.post("/{space_id}/files", status_code=201)
async def add_files_to_space(
    space_id: uuid.UUID,
    data: AddFilesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """向数据空间添加文件"""
    # 验证数据空间归属
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="数据空间不存在")

    # 验证文件归属并添加
    for file_id in data.file_ids:
        file_result = await db.execute(
            select(File).where(File.id == file_id, File.user_id == current_user.id)
        )
        if not file_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"文件 {file_id} 不存在")

        # 检查是否已关联
        existing = await db.execute(
            select(DataSpaceFile).where(
                DataSpaceFile.data_space_id == space_id, DataSpaceFile.file_id == file_id
            )
        )
        if not existing.scalar_one_or_none():
            db.add(DataSpaceFile(data_space_id=space_id, file_id=file_id))

    # 更新索引状态为需要重建
    space_result = await db.execute(select(DataSpace).where(DataSpace.id == space_id))
    space = space_result.scalar_one()
    if space.index_status == "ready":
        space.index_status = "empty"

    return {"message": "文件已添加到数据空间"}


@router.delete("/{space_id}/files/{file_id}", status_code=204)
async def remove_file_from_space(
    space_id: uuid.UUID,
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """从数据空间移除文件"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="数据空间不存在")

    link_result = await db.execute(
        select(DataSpaceFile).where(
            DataSpaceFile.data_space_id == space_id, DataSpaceFile.file_id == file_id
        )
    )
    link = link_result.scalar_one_or_none()
    if link:
        await db.delete(link)


@router.post("/{space_id}/index/build")
async def build_index(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """触发数据空间索引构建"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="数据空间不存在")

    space.index_status = "building"

    # TODO: 触发异步索引构建任务
    # 暂时直接标记为 ready（后续接入实际索引逻辑）
    space.index_status = "ready"

    return {"message": "索引构建已启动", "status": space.index_status}


@router.post("/{space_id}/upload", response_model=list[FileResponse], status_code=201)
async def upload_files_to_space(
    space_id: uuid.UUID,
    files: list[UploadFile] = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传文件到数据空间（上传并自动关联，ZIP 自动解压后每个文件单独入库）"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    space = result.scalar_one_or_none()
    if not space:
        raise HTTPException(status_code=404, detail="数据空间不存在")

    uploaded = []
    user_storage = get_user_storage_path(current_user.id)

    for upload_file in files:
        file_type = get_file_type(upload_file.filename)
        if file_type not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file_type}")

        content = await upload_file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件 {upload_file.filename} 超过大小限制(50MB)")

        # ZIP 文件：解压后每个子文件单独入库并关联到数据空间
        if file_type == "zip":
            tmp_dir = user_storage / f"_zip_tmp_{uuid.uuid4()}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                zf = zipfile.ZipFile(io.BytesIO(content), "r")
                for info in zf.infolist():
                    if info.filename.startswith('/') or '..' in info.filename:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        raise HTTPException(status_code=400, detail=f"zip 文件包含不安全的路径: {info.filename}")
                zf.extractall(tmp_dir)
                member_names = zf.namelist()
                zf.close()
            except zipfile.BadZipFile:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise HTTPException(status_code=400, detail=f"无效的 zip 文件: {upload_file.filename}")

            for member in member_names:
                if member.endswith("/") or _is_junk_path(member):
                    continue
                member_type = get_file_type(member)
                if member_type not in ALLOWED_EXTENSIONS:
                    continue

                src = tmp_dir / member
                if not src.is_file():
                    continue

                member_content = src.read_bytes()
                member_name = Path(member).name
                member_id = uuid.uuid4()
                member_dir = user_storage / str(member_id)
                member_dir.mkdir(parents=True, exist_ok=True)
                member_path = member_dir / member_name
                shutil.move(str(src), str(member_path))

                relative_path = str(member_path.relative_to(Path(settings.storage_root)))
                file_record = File(
                    id=member_id,
                    user_id=current_user.id,
                    filename=member_name,
                    original_filename=member_name,
                    file_type=member_type,
                    file_size=len(member_content),
                    storage_path=relative_path,
                    metadata_={"source_zip": upload_file.filename, "zip_path": member},
                )
                db.add(file_record)
                await db.flush()
                db.add(DataSpaceFile(data_space_id=space_id, file_id=member_id))
                uploaded.append(file_record)

            shutil.rmtree(tmp_dir, ignore_errors=True)
            continue

        # 普通文件：直接存储并关联
        file_id = uuid.uuid4()
        file_dir = user_storage / str(file_id)
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / upload_file.filename

        with open(file_path, "wb") as f:
            f.write(content)

        relative_path = str(file_path.relative_to(Path(settings.storage_root)))
        file_record = File(
            id=file_id,
            user_id=current_user.id,
            filename=upload_file.filename,
            original_filename=upload_file.filename,
            file_type=file_type,
            file_size=len(content),
            storage_path=relative_path,
            mime_type=upload_file.content_type,
        )
        db.add(file_record)
        await db.flush()
        db.add(DataSpaceFile(data_space_id=space_id, file_id=file_id))
        uploaded.append(file_record)

    # 重置索引状态
    if space.index_status == "ready":
        space.index_status = "empty"

    await db.flush()

    # 触发后台预处理
    from fastapi import BackgroundTasks
    import asyncio
    from app.services.preprocessing import preprocess_file

    async def _run_preprocessing():
        for f in uploaded:
            await preprocess_file(f.id, space_id)

    asyncio.ensure_future(_run_preprocessing())

    return uploaded


@router.get("/{space_id}/profile")
async def get_space_profile_endpoint(
    space_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取数据空间的聚合数据画像"""
    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="数据空间不存在")

    from app.services.preprocessing import get_space_profile
    profile = await get_space_profile(space_id)
    return profile


@router.get("/{space_id}/files/{file_id}/profile")
async def get_file_profile_endpoint(
    space_id: uuid.UUID,
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单个文件的数据画像"""
    from app.models.data_profile import DataProfile as DP
    result = await db.execute(
        select(DP).where(DP.file_id == file_id, DP.data_space_id == space_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="画像不存在，可能正在处理中")
    return {
        "file_id": str(profile.file_id),
        "profile_type": profile.profile_type,
        "status": profile.status,
        "profile_data": profile.profile_data,
        "error_message": profile.error_message,
    }


@router.get("/{space_id}/files/{file_id}/preview")
async def preview_file_data(
    space_id: uuid.UUID,
    file_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """预览文件数据（表格形式，支持分页）"""
    import pandas as pd
    import json as json_mod

    result = await db.execute(
        select(DataSpace).where(DataSpace.id == space_id, DataSpace.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="数据空间不存在")

    file_result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = file_result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = Path(settings.storage_root) / file.storage_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不在磁盘上")

    ext = file.file_type.lower()

    # SQLite database files
    if ext in ("sqlite", "db", "sqlite3"):
        import sqlite3
        table_name = Query(default=None)
        conn = sqlite3.connect(str(file_path))
        try:
            # List tables if no specific table requested
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            if not tables:
                return {"type": "database", "tables": [], "message": "数据库为空"}

            # Use first table by default
            target_table = tables[0]
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM '{target_table}'")
            total = count_cursor.fetchone()[0]

            offset = (page - 1) * page_size
            data_cursor = conn.execute(f"SELECT * FROM '{target_table}' LIMIT {page_size} OFFSET {offset}")
            col_names = [desc[0] for desc in data_cursor.description]
            rows_data = [list(str(v) if v is not None else "" for v in row) for row in data_cursor.fetchall()]

            return {
                "type": "database",
                "tables": tables,
                "current_table": target_table,
                "columns": [{"name": c, "dtype": "text"} for c in col_names],
                "rows": rows_data,
                "total_rows": total,
                "page": page,
                "page_size": page_size,
                "filename": file.filename,
            }
        finally:
            conn.close()

    # Tabular formats
    df = None
    if ext == "csv":
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        df = pd.read_csv(file_path, encoding=encoding, nrows=page * page_size, on_bad_lines="skip")
    elif ext == "tsv":
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        df = pd.read_csv(file_path, sep="\t", encoding=encoding, nrows=page * page_size, on_bad_lines="skip")
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(file_path, nrows=page * page_size)
    elif ext == "parquet":
        df = pd.read_parquet(file_path).head(page * page_size)
    elif ext == "feather":
        df = pd.read_feather(file_path).head(page * page_size)
    elif ext == "json":
        content = file_path.read_text(encoding="utf-8")
        data = json_mod.loads(content)
        if isinstance(data, list):
            df = pd.DataFrame(data[:page * page_size])
        elif isinstance(data, dict) and "records" in data:
            df = pd.DataFrame(data["records"][:page * page_size])
        else:
            return {"type": "text", "content": content[:2000], "total_chars": len(content)}
    elif ext == "jsonl":
        df = pd.read_json(file_path, lines=True, nrows=page * page_size)
    elif ext in ("txt", "md", "py", "sql", "html", "xml", "yaml", "yml", "log", "r", "ipynb"):
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        content = file_path.read_text(encoding=encoding, errors="ignore")
        lines = content.split("\n")
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "type": "text",
            "content": "\n".join(lines[start:end]),
            "total_lines": len(lines),
            "page": page,
            "page_size": page_size,
        }
    elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp"):
        return {"type": "image", "filename": file.filename, "file_size_kb": round(file_path.stat().st_size / 1024, 1)}
    else:
        return {"type": "unsupported", "message": f"不支持预览的文件类型: {ext}"}

    if df is None or df.empty:
        return {"type": "unsupported", "message": "无法解析文件内容"}

    total_rows = len(df)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = df.iloc[start:end]

    columns = []
    for col in df.columns:
        columns.append({
            "name": str(col),
            "dtype": str(df[col].dtype),
        })

    rows = page_df.fillna("").astype(str).values.tolist()

    return {
        "type": "table",
        "columns": columns,
        "rows": rows,
        "total_rows": total_rows,
        "page": page,
        "page_size": page_size,
        "filename": file.filename,
    }
