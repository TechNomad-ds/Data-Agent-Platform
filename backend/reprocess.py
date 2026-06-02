"""重新处理卡在 pending 状态的文件：生成数据画像 + 向量索引"""
import asyncio
import sys
from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_space import DataSpaceFile
from app.services.preprocessing import preprocess_file


async def main(space_id: str):
    factory = get_session_factory()
    async with factory() as db:
        rows = await db.execute(
            select(File)
            .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
            .where(DataSpaceFile.data_space_id == space_id)
        )
        files = rows.scalars().all()

    print(f"找到 {len(files)} 个文件，开始重新处理...")
    for f in files:
        try:
            res = await preprocess_file(f.id, space_id)
            err = res.get("error") if isinstance(res, dict) else None
            print(f"  {'✗' if err else '✓'} {f.filename}: {err or '画像已生成'}")
        except Exception as e:
            print(f"  ✗ {f.filename}: {e}")

    # 等后台 embedding 任务跑完
    print("等待后台向量索引完成...")
    await asyncio.sleep(8)
    print("完成")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
