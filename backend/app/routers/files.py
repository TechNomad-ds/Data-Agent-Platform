"""文件管理路由 - 上传、列表、预览、删除"""
import uuid
import os
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.file import File
from app.schemas.file import FileResponse, FileListResponse
from app.config import settings

router = APIRouter()

# 支持的文件类型
ALLOWED_EXTENSIONS = {
    "txt", "md", "pdf", "docx", "csv", "xlsx", "json", "jsonl",
    "html", "xml", "sql", "py", "ipynb", "zip", "yaml", "yml",
    "log", "tsv", "parquet",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def get_file_type(filename: str) -> str:
    """从文件名获取文件类型"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    return ext


def get_user_storage_path(user_id: uuid.UUID) -> Path:
    """获取用户的存储根目录"""
    path = Path(settings.storage_root) / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/upload", response_model=list[FileResponse])
async def upload_files(
    files: list[UploadFile] = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传文件（支持多文件批量上传）"""
    uploaded = []
    user_storage = get_user_storage_path(current_user.id)

    for upload_file in files:
        # 验证文件类型
        file_type = get_file_type(upload_file.filename)
        if file_type not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file_type}")

        # 读取文件内容
        content = await upload_file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件 {upload_file.filename} 超过大小限制(50MB)")

        # 生成存储路径
        file_id = uuid.uuid4()
        file_dir = user_storage / str(file_id)
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / upload_file.filename

        # 写入文件
        with open(file_path, "wb") as f:
            f.write(content)

        # 如果是 zip 文件，解压
        extracted_files = []
        if file_type == "zip":
            extract_dir = file_dir / "extracted"
            extract_dir.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile(file_path, "r") as zf:
                    zf.extractall(extract_dir)
                    for name in zf.namelist():
                        if not name.endswith("/"):
                            extracted_files.append(name)
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail=f"无效的 zip 文件: {upload_file.filename}")

        # 创建数据库记录
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
            metadata_={"extracted_files": extracted_files} if extracted_files else {},
        )
        db.add(file_record)
        uploaded.append(file_record)

    await db.flush()
    return uploaded


@router.get("", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    file_type: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的文件列表"""
    query = select(File).where(File.user_id == current_user.id)
    if file_type:
        query = query.where(File.file_type == file_type)

    # 总数
    count_query = select(func.count()).select_from(File).where(File.user_id == current_user.id)
    if file_type:
        count_query = count_query.where(File.file_type == file_type)
    total = (await db.execute(count_query)).scalar()

    # 分页
    query = query.order_by(File.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    files = result.scalars().all()

    return FileListResponse(files=files, total=total)


@router.get("/{file_id}", response_model=FileResponse)
async def get_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取文件详情"""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    return file


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除文件"""
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 删除物理文件
    file_path = Path(settings.storage_root) / file.storage_path
    file_dir = file_path.parent
    if file_dir.exists():
        shutil.rmtree(file_dir)

    await db.delete(file)
