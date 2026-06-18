"""对话式数据导入服务 - Agent 可通过工具动态添加数据
适配自 DataMind IngestService"""
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_space import DataSpaceFile
from app.services.chunking import greedy_chunk
from app.services import embedding as embed_svc


class IngestService:
    """对话式数据导入，通过 file_id 引用（多租户安全）"""

    def __init__(self, user_id: uuid.UUID, data_space_id: uuid.UUID):
        self.user_id = user_id
        self.data_space_id = data_space_id

    async def _resolve_file(self, filename: str) -> tuple[Path, str] | None:
        """通过文件名查找文件路径和 file_id"""
        async with get_session_factory()() as db:
            result = await db.execute(
                select(File)
                .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                .where(
                    File.user_id == self.user_id,
                    File.filename == filename,
                    DataSpaceFile.data_space_id == self.data_space_id,
                )
            )
            file = result.scalar_one_or_none()
            if not file:
                return None
            path = Path(settings.storage_root) / file.storage_path
            if not path.exists():
                return None
            return path, str(file.id)

    async def kb_reindex_file(self, filename: str) -> dict:
        """重新分段和嵌入指定文件"""
        resolved = await self._resolve_file(filename)
        if not resolved:
            return {"error": f"文件 '{filename}' 不存在或不在当前数据空间"}

        file_path, file_id = resolved

        embed_svc.delete_file_embeddings(str(self.data_space_id), file_id)

        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in ("txt", "md", "py", "sql", "html", "xml", "yaml"):
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        elif ext == "pdf":
            try:
                import fitz
                doc = fitz.open(str(file_path))
                content = "\n".join(page.get_text() for page in doc)
                doc.close()
            except Exception:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
        elif ext in ("docx", "pptx"):
            try:
                from app.services.document_text import extract_document_text
                content = extract_document_text(file_path, ext)
            except Exception:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
        else:
            return {"error": f"文件类型 '{ext}' 不支持文本索引"}

        chunks = greedy_chunk(content, max_size=1000, overlap=200)
        count = await embed_svc.embed_chunks_async(str(self.data_space_id), chunks, file_id, filename)

        from app.services.retrieval import invalidate_cache
        invalidate_cache(str(self.data_space_id))

        return {"filename": filename, "chunks_indexed": count}

    async def db_import_csv(self, filename: str, table_name: str) -> dict:
        """将 CSV 文件导入为 SQLite 表"""
        resolved = await self._resolve_file(filename)
        if not resolved:
            return {"error": f"文件 '{filename}' 不存在或不在当前数据空间"}

        file_path, file_id = resolved
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in ("csv", "tsv"):
            return {"error": f"只支持 CSV/TSV 文件导入，当前: {ext}"}

        import pandas as pd
        from app.services.preprocessing import _detect_encoding

        encoding = _detect_encoding(file_path)
        sep = "\t" if ext == "tsv" else ","
        df = pd.read_csv(file_path, encoding=encoding, sep=sep, on_bad_lines="skip")

        from app.services.sqlite_engine import load_space_to_sqlite, invalidate_cache as sqlite_invalidate
        db_path = await load_space_to_sqlite(self.data_space_id, self.user_id)

        import sqlite3
        safe_table = table_name.replace(" ", "_").replace("-", "_").lower()
        conn = sqlite3.connect(db_path)
        try:
            df.to_sql(safe_table, conn, if_exists="replace", index=False)
            row_count = len(df)
        finally:
            conn.close()

        sqlite_invalidate(str(self.data_space_id))

        return {
            "filename": filename,
            "table_name": safe_table,
            "row_count": row_count,
            "column_count": len(df.columns),
        }
