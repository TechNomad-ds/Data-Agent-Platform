"""渠道附件统一入库：把从 IM 渠道收到的文件二进制落盘并登记进数据空间。

飞书云文档抓取（feishu_doc）与各渠道发来的文件/图片附件（dispatch attachment 路径）
都收敛到这里：写入用户存储目录 → file_intake.register_file_to_space 登记 + 触发后台
解析索引。之后 agent 即可像普通上传文件一样检索/分析。
"""
from __future__ import annotations

import uuid

from app.services.file_intake import register_file_to_space, user_space_dir


async def ingest_files_to_space(
    user_id: uuid.UUID,
    space_id: uuid.UUID,
    files: list[tuple[str, bytes]],
) -> list[dict]:
    """把 [(filename, bytes), ...] 逐个落盘并登记进数据空间，返回登记结果列表。

    每个文件独立目录（user_space_dir 用新 file_id 建子目录），避免重名覆盖。
    """
    ingested: list[dict] = []
    for filename, content in files:
        target_dir = user_space_dir(user_id, uuid.uuid4())
        path = target_dir / filename
        path.write_bytes(content)
        res = await register_file_to_space(
            user_id=user_id,
            data_space_id=space_id,
            src_path=path,
            filename=filename,
        )
        ingested.append(res)
    return ingested
