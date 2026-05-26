"""向量嵌入服务 - ChromaDB 封装"""
import uuid
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings


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
    return client.get_or_create_collection(
        name=f"space_{data_space_id.replace('-', '')}",
        metadata={"hnsw:space": "cosine"},
    )


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
