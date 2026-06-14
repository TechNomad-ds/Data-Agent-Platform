"""文件管理路由 - 上传、列表、预览、删除"""
import uuid
import io
import shutil
import zipfile
from pathlib import Path

import aiofiles
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
    "txt", "md", "pdf", "docx", "csv", "xlsx", "xls", "json", "jsonl",
    "html", "xml", "sql", "py", "ipynb", "zip", "yaml", "yml",
    "log", "tsv", "parquet", "feather", "sqlite", "db", "sqlite3",
    "png", "jpg", "jpeg", "gif", "bmp", "webp",
    "mp4", "mov", "avi", "mkv", "webm",
    "r", "sas7bdat", "dta", "sav",
}

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB (databases can be large)
MAX_FILES_PER_UPLOAD = 20
MAX_ZIP_FILES = 1000
MAX_ZIP_TOTAL_SIZE = 500 * 1024 * 1024


def get_file_type(filename: str) -> str:
    """从文件名获取文件类型"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    return ext


def _is_junk_path(name: str) -> bool:
    """过滤 zip 中的垃圾文件（macOS 元数据、隐藏文件等）"""
    parts = name.replace("\\", "/").split("/")
    for p in parts:
        if p == "__MACOSX" or p.startswith("."):
            return True
    return False


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
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {MAX_FILES_PER_UPLOAD} 个文件")

    uploaded = []
    user_storage = get_user_storage_path(current_user.id)

    for upload_file in files:
        # 验证文件类型
        file_type = get_file_type(upload_file.filename)
        if file_type not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file_type}")

        temp_path = user_storage / f"_upload_tmp_{uuid.uuid4()}"
        file_size = 0
        try:
            async with aiofiles.open(temp_path, "wb") as tmp:
                while chunk := await upload_file.read(1024 * 1024):
                    file_size += len(chunk)
                    if file_size > MAX_FILE_SIZE:
                        raise HTTPException(status_code=400, detail=f"文件 {upload_file.filename} 超过大小限制(200MB)")
                    await tmp.write(chunk)
        except HTTPException:
            temp_path.unlink(missing_ok=True)
            raise

        # zip 文件：解压后逐个入库
        if file_type == "zip":
            tmp_dir = user_storage / f"_zip_tmp_{uuid.uuid4()}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            try:
                zf = zipfile.ZipFile(str(temp_path), "r")
                total_uncompressed = 0
                valid_count = 0
                for info in zf.infolist():
                    if info.filename.startswith('/') or '..' in info.filename:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        raise HTTPException(status_code=400, detail=f"zip 文件包含不安全的路径: {info.filename}")
                    if info.is_dir() or _is_junk_path(info.filename):
                        continue
                    if get_file_type(info.filename) not in ALLOWED_EXTENSIONS:
                        continue
                    valid_count += 1
                    total_uncompressed += info.file_size
                if valid_count > MAX_ZIP_FILES:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    raise HTTPException(status_code=400, detail=f"zip 文件包含过多有效文件({valid_count}个，上限{MAX_ZIP_FILES}个)")
                if total_uncompressed > MAX_ZIP_TOTAL_SIZE:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    raise HTTPException(status_code=400, detail="zip 解压后总大小超过限制(500MB)")
                zf.extractall(tmp_dir)
                member_names = zf.namelist()
                zf.close()
            except zipfile.BadZipFile:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                temp_path.unlink(missing_ok=True)
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

                member_name = Path(member).name
                member_id = uuid.uuid4()
                member_dir = user_storage / str(member_id)
                member_dir.mkdir(parents=True, exist_ok=True)
                member_path = member_dir / member_name
                member_size = src.stat().st_size
                shutil.move(str(src), str(member_path))

                relative_path = str(member_path.relative_to(Path(settings.storage_root)))
                record = File(
                    id=member_id,
                    user_id=current_user.id,
                    filename=member_name,
                    original_filename=member_name,
                    file_type=member_type,
                    file_size=member_size,
                    storage_path=relative_path,
                    metadata_={"source_zip": upload_file.filename},
                )
                db.add(record)
                uploaded.append(record)

            shutil.rmtree(tmp_dir, ignore_errors=True)
            temp_path.unlink(missing_ok=True)
            continue

        # 普通文件：直接存储
        file_id = uuid.uuid4()
        file_dir = user_storage / str(file_id)
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / upload_file.filename

        shutil.move(str(temp_path), str(file_path))

        relative_path = str(file_path.relative_to(Path(settings.storage_root)))
        file_record = File(
            id=file_id,
            user_id=current_user.id,
            filename=upload_file.filename,
            original_filename=upload_file.filename,
            file_type=file_type,
            file_size=file_size,
            storage_path=relative_path,
            mime_type=upload_file.content_type,
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


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下载文件"""
    from fastapi.responses import FileResponse as FastAPIFileResponse
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = Path(settings.storage_root) / file.storage_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不在磁盘上")

    return FastAPIFileResponse(
        path=str(file_path),
        filename=file.original_filename or file.filename,
        media_type=file.mime_type or "application/octet-stream",
    )


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

    # 清理关联的向量嵌入
    from app.models.data_space import DataSpaceFile
    dsf_result = await db.execute(
        select(DataSpaceFile).where(DataSpaceFile.file_id == file_id)
    )
    for dsf in dsf_result.scalars().all():
        try:
            from app.services.embedding import delete_file_embeddings
            delete_file_embeddings(str(dsf.data_space_id), str(file_id))
        except Exception:
            pass

    # 删除物理文件
    file_path = Path(settings.storage_root) / file.storage_path
    file_dir = file_path.parent
    if file_dir.exists():
        shutil.rmtree(file_dir)

    await db.delete(file)
