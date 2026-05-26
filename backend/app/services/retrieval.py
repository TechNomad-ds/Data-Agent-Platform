"""混合检索服务 - BM25 + 向量 + RRF 融合
适配自 DataMind HybridRetriever + KDD-CUP MarkdownRAG"""
import re
import math
from dataclasses import dataclass
from typing import Optional

from rank_bm25 import BM25Okapi

from app.config import settings
from app.services import embedding as embed_svc


@dataclass
class RetrievalResult:
    text: str
    score: float
    metadata: dict
    source: str  # "vector" | "bm25" | "hybrid"


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "further", "then", "once", "and", "but", "or",
    "nor", "not", "so", "yet", "both", "either", "neither", "each", "every",
    "all", "any", "few", "more", "most", "other", "some", "such", "no",
    "only", "own", "same", "than", "too", "very", "just", "because",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "这", "中", "大", "为", "上", "个", "国", "他", "时", "来", "用", "们",
    "到", "说", "会", "着", "那", "地", "也", "子", "要", "下", "看", "天",
})

_CJK_RANGES = (
    "一-鿿"   # CJK Unified
    "㐀-䶿"   # CJK Extension A
    "豈-﫿"   # CJK Compatibility
)
_TOKEN_RE = re.compile(
    rf"[{_CJK_RANGES}]|[a-zA-Z0-9][\w.-]*",
    re.UNICODE,
)


def _tokenize(text: str) -> list[str]:
    """CJK 感知分词：中文单字切分，英文按词切分"""
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if len(t) >= 2 or re.match(rf"[{_CJK_RANGES}]", t)]


def _tokenize_filtered(text: str) -> list[str]:
    """分词 + 去停用词"""
    return [t for t in _tokenize(text) if t not in _STOPWORDS]


class HybridRetrievalService:
    """BM25 + 向量 + RRF 融合检索"""

    def __init__(self, data_space_id: str):
        self.data_space_id = data_space_id
        self._bm25: Optional[BM25Okapi] = None
        self._corpus_docs: list[dict] = []

    def _ensure_bm25(self) -> bool:
        """确保 BM25 索引已构建，返回是否可用"""
        if self._bm25 is not None:
            return True
        return self._build_bm25_index()

    def _build_bm25_index(self) -> bool:
        """从 ChromaDB 读取所有文本构建 BM25 索引"""
        texts_data = get_all_texts(self.data_space_id)
        if not texts_data:
            return False

        self._corpus_docs = texts_data
        tokenized = [_tokenize_filtered(doc["text"]) for doc in texts_data]
        self._bm25 = BM25Okapi(tokenized)
        return True

    def rebuild_bm25_index(self) -> dict:
        """强制重建 BM25 索引"""
        self._bm25 = None
        self._corpus_docs = []
        success = self._build_bm25_index()
        return {
            "success": success,
            "doc_count": len(self._corpus_docs),
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """统一检索入口"""
        mode = mode or settings.retrieval_mode

        if mode == "vector":
            return self._vector_search(query, top_k)
        elif mode == "bm25":
            return self._bm25_search(query, top_k)
        elif mode == "hybrid":
            return self._hybrid_search(query, top_k)
        elif mode == "multi_query":
            return self._hybrid_search(query, top_k)
        else:
            return self._hybrid_search(query, top_k)

    def _vector_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """纯向量搜索"""
        results = embed_svc.search(self.data_space_id, query, top_k=top_k)
        return [
            RetrievalResult(
                text=r["text"],
                score=1.0 - r.get("distance", 0),
                metadata=r.get("metadata", {}),
                source="vector",
            )
            for r in results
        ]

    def _bm25_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """纯 BM25 搜索"""
        if not self._ensure_bm25():
            return []

        query_tokens = _tokenize_filtered(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        max_score = max(scores) if max(scores) > 0 else 1.0
        for idx in top_indices:
            if scores[idx] <= 0:
                break
            doc = self._corpus_docs[idx]
            results.append(RetrievalResult(
                text=doc["text"],
                score=scores[idx] / max_score,
                metadata=doc.get("metadata", {}),
                source="bm25",
            ))
        return results

    def _hybrid_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """BM25 + 向量 RRF 融合"""
        candidate_k = top_k * 3
        rrf_k = settings.rrf_k

        vec_results = self._vector_search(query, candidate_k)
        bm25_results = self._bm25_search(query, candidate_k)

        vec_ranked = {}
        for rank, r in enumerate(vec_results):
            key = r.text[:200]
            vec_ranked[key] = (rank, r)

        bm25_ranked = {}
        for rank, r in enumerate(bm25_results):
            key = r.text[:200]
            bm25_ranked[key] = (rank, r)

        all_keys = set(vec_ranked.keys()) | set(bm25_ranked.keys())
        fused = []
        for key in all_keys:
            vec_score = 1.0 / (rrf_k + vec_ranked[key][0] + 1) if key in vec_ranked else 0
            bm25_score = 1.0 / (rrf_k + bm25_ranked[key][0] + 1) if key in bm25_ranked else 0
            combined = vec_score + bm25_score

            result = vec_ranked[key][1] if key in vec_ranked else bm25_ranked[key][1]
            fused.append(RetrievalResult(
                text=result.text,
                score=combined,
                metadata=result.metadata,
                source="hybrid",
            ))

        fused.sort(key=lambda r: r.score, reverse=True)
        return fused[:top_k]


def get_all_texts(data_space_id: str) -> list[dict]:
    """从 ChromaDB 获取所有文本，供 BM25 索引构建"""
    collection = embed_svc.get_collection(data_space_id)
    try:
        result = collection.get(include=["documents", "metadatas"])
    except Exception:
        return []

    if not result or not result.get("documents"):
        return []

    docs = []
    for i, text in enumerate(result["documents"]):
        if text:
            meta = result["metadatas"][i] if result.get("metadatas") else {}
            docs.append({"text": text, "metadata": meta})
    return docs


_service_cache: dict[str, HybridRetrievalService] = {}


def get_retrieval_service(data_space_id: str) -> HybridRetrievalService:
    """获取或创建检索服务实例（带缓存）"""
    if data_space_id not in _service_cache:
        _service_cache[data_space_id] = HybridRetrievalService(data_space_id)
    return _service_cache[data_space_id]


def invalidate_cache(data_space_id: str) -> None:
    """数据变更后清除缓存"""
    _service_cache.pop(data_space_id, None)
