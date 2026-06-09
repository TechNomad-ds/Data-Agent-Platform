"""端到端测评 harness — 环境搭建

模拟"用户上传 content.zip 到新数据空间"：
- 建一个固定测试用户（admin，跳过额度）
- 每个 task 建一个独立数据空间
- 把 input/task_N/context 下所有文件复制进 storage（复刻线上 user_id/file_id/filename 布局）
- 建 File / DataSpaceFile 记录
- 对每个文件跑 preprocess_file（schema/embedding/OCR/视频关键帧）

直接 import 后端模块，不走 HTTP。
"""
import asyncio
import os
import sys
import uuid
import shutil
from pathlib import Path

BACKEND = Path("/root/datamind/Data-Agent-Platform/backend")
sys.path.insert(0, str(BACKEND))
# 关键：切到 backend 工作目录，使 ./storage、./chroma_data 等相对路径与线上服务一致
os.chdir(BACKEND)

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.database import get_session_factory  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.file import File  # noqa: E402
from app.models.data_space import DataSpace, DataSpaceFile  # noqa: E402
from app.models.data_profile import DataProfile  # noqa: E402
from app.services.preprocessing import preprocess_file  # noqa: E402

INPUT_ROOT = Path("/root/datamind/demo_samples_phase2/input")
TEST_EMAIL = "eval@harness.local"
TEST_USERNAME = "eval_harness"
STORAGE_ROOT = Path(settings.storage_root)
if not STORAGE_ROOT.is_absolute():
    STORAGE_ROOT = BACKEND / STORAGE_ROOT


async def ensure_user() -> uuid.UUID:
    """获取或创建测试用户（admin role，跑 agent 时 is_admin=True 跳过额度）。"""
    async with get_session_factory()() as db:
        result = await db.execute(select(User).where(User.email == TEST_EMAIL))
        user = result.scalar_one_or_none()
        if user:
            return user.id
        user = User(
            email=TEST_EMAIL,
            username=TEST_USERNAME,
            password_hash=hash_password("eval-harness-pw"),
            role="admin",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def ensure_model() -> str:
    """确保有一个可用的平台模型行（用 .env 的 OpenAI 兼容配置 + Fernet 加密 key）。
    返回 model_id，供 AgentLoop 解析。复刻管理员在后台配置模型的流程。"""
    from app.models.llm_model import LLMModel
    from app.core.security import encrypt_api_key

    model_id = "eval-deepseek-v4-flash"
    async with get_session_factory()() as db:
        result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
        m = result.scalar_one_or_none()
        enc_key = encrypt_api_key(settings.openai_api_key)
        if m:
            m.api_key_encrypted = enc_key
            m.api_base = settings.openai_api_base
            m.model_name = settings.openai_model
            m.is_active = True
        else:
            db.add(LLMModel(
                id=model_id,
                provider="openai",
                display_name="Eval DeepSeek V4 Flash",
                api_base=settings.openai_api_base,
                api_key_encrypted=enc_key,
                model_name=settings.openai_model,
                credit_multiplier=1.0,
                max_tokens=8192,
                is_active=True,
                visible_to_users=False,
            ))
        await db.commit()
    return model_id


def list_context_files(task_id: str) -> list[Path]:
    """task_N/context 下所有文件（递归），模拟 zip 内全部成员。"""
    ctx = INPUT_ROOT / task_id / "context"
    return [p for p in ctx.rglob("*") if p.is_file()]


async def reset_space(user_id: uuid.UUID, task_id: str) -> None:
    """删除该 task 已有的数据空间 + 文件记录 + profile（重跑用）。"""
    space_name = f"eval_{task_id}"
    async with get_session_factory()() as db:
        result = await db.execute(
            select(DataSpace).where(DataSpace.user_id == user_id, DataSpace.name == space_name)
        )
        space = result.scalar_one_or_none()
        if not space:
            return
        space_id = space.id
        # 找到该空间所有文件
        fres = await db.execute(
            select(File).join(DataSpaceFile, DataSpaceFile.file_id == File.id)
            .where(DataSpaceFile.data_space_id == space_id)
        )
        files = fres.scalars().all()
        for f in files:
            await db.execute(
                DataProfile.__table__.delete().where(DataProfile.file_id == f.id)
            )
        await db.execute(
            DataSpaceFile.__table__.delete().where(DataSpaceFile.data_space_id == space_id)
        )
        for f in files:
            await db.execute(File.__table__.delete().where(File.id == f.id))
        # 删除引用该空间的会话及其消息
        from app.models.conversation import Conversation, Message
        cres = await db.execute(select(Conversation).where(Conversation.data_space_id == space_id))
        convs = cres.scalars().all()
        for c in convs:
            await db.execute(Message.__table__.delete().where(Message.conversation_id == c.id))
        await db.execute(Conversation.__table__.delete().where(Conversation.data_space_id == space_id))
        await db.execute(DataSpace.__table__.delete().where(DataSpace.id == space_id))
        await db.commit()
    # 清理向量库残留
    try:
        from app.services import embedding as embed_svc
        client = embed_svc.get_chroma_client()
        client.delete_collection(name=f"space_{str(space_id).replace('-', '')}")
    except Exception:
        pass


async def build_space(user_id: uuid.UUID, task_id: str, run_preprocess: bool = True) -> uuid.UUID:
    """建数据空间 + 灌文件 + 预处理。返回 data_space_id。"""
    space_name = f"eval_{task_id}"
    user_dir = STORAGE_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    async with get_session_factory()() as db:
        space = DataSpace(user_id=user_id, name=space_name, description=f"Eval space for {task_id}")
        db.add(space)
        await db.commit()
        await db.refresh(space)
        space_id = space.id

        file_ids = []
        for src in list_context_files(task_id):
            fname = src.name
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "unknown"
            fid = uuid.uuid4()
            fdir = user_dir / str(fid)
            fdir.mkdir(parents=True, exist_ok=True)
            dst = fdir / fname
            shutil.copy2(src, dst)
            rel = str(dst.relative_to(STORAGE_ROOT))
            rec = File(
                id=fid, user_id=user_id, filename=fname, original_filename=fname,
                file_type=ext, file_size=src.stat().st_size, storage_path=rel,
                metadata_={"source_zip": "content.zip"},
            )
            db.add(rec)
            file_ids.append((fid, ext, fname))
        await db.flush()  # 先落 File，再建关联，避免 FK 违例
        for fid, _ext, _fname in file_ids:
            db.add(DataSpaceFile(data_space_id=space_id, file_id=fid))
        await db.commit()

    if run_preprocess:
        for fid, ext, fname in file_ids:
            try:
                await preprocess_file(fid, space_id)
            except Exception as e:
                print(f"  [preprocess 失败] {fname}: {e}")

    return space_id
