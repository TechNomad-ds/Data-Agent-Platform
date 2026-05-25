"""数据空间路由 - CRUD、文件关联、索引管理"""
import uuid
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
from app.routers.files import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, get_file_type, get_user_storage_path

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
    """上传文件到数据空间（上传并自动关联）"""
    # 验证数据空间归属
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

        file_id = uuid.uuid4()
        file_dir = user_storage / str(file_id)
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / upload_file.filename

        with open(file_path, "wb") as f:
            f.write(content)

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
        await db.flush()

        # 关联到数据空间
        db.add(DataSpaceFile(data_space_id=space_id, file_id=file_id))
        uploaded.append(file_record)

    # 重置索引状态
    if space.index_status == "ready":
        space.index_status = "empty"

    await db.flush()
    return uploaded
