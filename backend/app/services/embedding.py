"""向量嵌入服务 - ChromaDB 封装"""
import asyncio
import logging
import uuid
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.db.base import UniqueConstraintError

from app.config import settings

logger = logging.getLogger("embedding")

_client: Optional[chromadb.ClientAPI] = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection(data_space_id: str) -> chromadb.Collection:
    client = get_chroma_client()
    name = f"space_{data_space_id.replace('-', '')}"
    try:
        return client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    except UniqueConstraintError:
        # Chroma 0.5 can race when multiple upload tasks create the same
        # collection concurrently. If another worker won creation, fetch it.
        logger.info("Chroma collection already created concurrently: %s", name)
        return client.get_collection(name=name)


def embed_chunks(
    data_space_id: str,
    chunks: List[Dict[str, Any]],
    file_id: str,
    filename: str,
) -> int:
    """将文本块嵌入到 ChromaDB"""
    if not chunks:
        return 0

    collection = get_collection(data_space_id)

    ids = [f"{file_id}_{i}" for i in range(len(chunks))]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {
            "file_id": file_id,
            "filename": filename,
            "start_char": c.get("start_char", 0),
            "end_char": c.get("end_char", 0),
        }
        for c in chunks
    ]

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


async def embed_chunks_async(
    data_space_id: str,
    chunks: List[Dict[str, Any]],
    file_id: str,
    filename: str,
) -> int:
    """异步包装：把 CPU 密集的 ONNX 推理丢到线程池，避免阻塞事件循环。

    ChromaDB 的默认 embedding（ONNX 推理）是同步阻塞操作。直接 await
    会冻结整个事件循环，导致索引大文件时所有请求排队。这里用
    run_in_executor 丢到线程池执行，主线程保持响应。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, embed_chunks, data_space_id, chunks, file_id, filename
    )


def warmup() -> None:
    """预热 embedding 模型：在启动时加载 ONNX 模型并跑一次推理。

    首次 embedding 调用需要把 90MB 模型从磁盘加载进内存（数百毫秒到数秒），
    这一步同步发生在第一个上传请求里。提前在启动时预热，消除首次延迟。
    """
    try:
        client = get_chroma_client()
        warm_col = client.get_or_create_collection(
            name="warmup",
            metadata={"hnsw:space": "cosine"},
        )
        # 触发 embedding function 的模型加载 + 一次推理
        warm_col.upsert(ids=["warmup_0"], documents=["预热向量模型 warmup the embedding model"])
        warm_col.delete(ids=["warmup_0"])
        logger.info("✓ embedding 模型已预热")
    except Exception as e:
        logger.warning(f"embedding 模型预热失败（不影响启动）: {e}")



def search(
    data_space_id: str,
    query: str,
    top_k: int = 5,
    file_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """向量搜索"""
    collection = get_collection(data_space_id)

    where = {"file_id": file_id} if file_id else None
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
    )

    items = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            items.append({
                "text": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })
    return items


def delete_file_embeddings(data_space_id: str, file_id: str) -> None:
    """删除文件的所有嵌入"""
    collection = get_collection(data_space_id)
    collection.delete(where={"file_id": file_id})
