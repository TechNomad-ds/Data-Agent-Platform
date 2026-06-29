"""把外部/新建的本地文件登记进数据空间的复用服务。

上传路由、agent 下载工具、对话沉淀等都需要「把一个磁盘上的文件变成数据空间里
可检索/可分析的文件」。这里抽出统一入口，避免各处重复写 File/DataSpaceFile 行 +
触发预处理的样板代码。
"""
import uuid
import logging
from pathlib import Path

from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_space import DataSpaceFile
from app.config import settings
from app.routers.files import get_file_type

logger = logging.getLogger("file_intake")


async def register_file_to_space(
    *,
    user_id: uuid.UUID,
    data_space_id: uuid.UUID,
    src_path: Path,
    filename: str,
    trigger_preprocess: bool = True,
) -> dict:
    """把 src_path 处的文件登记为某数据空间下的 File，并（默认）触发后台预处理/索引。

    src_path 应已位于 settings.storage_root 之下（调用方负责把字节落到用户存储目录）。
    返回 {file_id, filename, file_type, file_size}。
    """
    if not src_path.exists():
        raise FileNotFoundError(f"文件不存在: {src_path}")

    storage_root = Path(settings.storage_root)
    try:
        relative_path = str(src_path.relative_to(storage_root))
    except ValueError:
        raise ValueError("文件必须位于存储根目录之下才能登记")

    file_type = get_file_type(filename)
    file_size = src_path.stat().st_size
    file_id = uuid.uuid4()

    async with get_session_factory()() as db:
        record = File(
            id=file_id,
            user_id=user_id,
            filename=filename,
            original_filename=filename,
            file_type=file_type,
            file_size=file_size,
            storage_path=relative_path,
            mime_type=None,
        )
        db.add(record)
        # 必须先 flush 把 File 落库，再插关联行：否则 SQLAlchemy 可能把
        # data_space_files 的 INSERT 排到 files 之前，触发外键违例（沉淀/下载登记失败的根因）。
        await db.flush()
        db.add(DataSpaceFile(data_space_id=data_space_id, file_id=file_id))
        await db.commit()

    if trigger_preprocess:
        # 后台预处理：不阻塞调用方（agent 工具调用要尽快返回）。
        import asyncio

        async def _bg():
            try:
                from app.services.preprocessing import preprocess_file_limited
                await preprocess_file_limited(file_id, data_space_id)
            except Exception as e:
                logger.error(f"下载文件预处理失败 {filename}: {e}", exc_info=True)

        asyncio.create_task(_bg())

    return {
        "file_id": str(file_id),
        "filename": filename,
        "file_type": file_type,
        "file_size": file_size,
    }


def user_space_dir(user_id: uuid.UUID, file_id: uuid.UUID) -> Path:
    """新文件的落盘目录：{storage_root}/{user_id}/{file_id}/。"""
    d = Path(settings.storage_root) / str(user_id) / str(file_id)
    d.mkdir(parents=True, exist_ok=True)
    return d
