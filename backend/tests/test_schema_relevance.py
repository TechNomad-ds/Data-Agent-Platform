"""相关性 schema 注入：文件级相关性排序聚合逻辑测试。

只测可纯函数化的聚合部分，mock 掉检索服务，不触发真实向量库/DB。
"""
import types
import uuid
import pytest

from app.agent.loop import AgentLoop


def _file(name, ftype="csv"):
    f = types.SimpleNamespace()
    f.id = uuid.uuid4()
    f.filename = name
    f.file_type = ftype
    return f


@pytest.mark.asyncio
async def test_rank_empty_question_returns_none():
    agent = AgentLoop()
    files = [_file("sales.csv")]
    assert await agent._rank_files_by_relevance("", uuid.uuid4(), files) is None
    assert await agent._rank_files_by_relevance("有数据吗", uuid.uuid4(), []) is None


@pytest.mark.asyncio
async def test_rank_aggregates_chunks_to_file_score(monkeypatch):
    """块级命中聚合成文件级：取最高分 + 命中数加权。"""
    import app.services.retrieval as retr

    f1 = _file("east_sales_2023.csv")
    f2 = _file("hr.csv")
    files = [f1, f2]

    def fake_search(self, q, top_k=30):
        return [
            types.SimpleNamespace(score=0.9, metadata={"file_id": str(f1.id)}),
            types.SimpleNamespace(score=0.5, metadata={"file_id": str(f1.id)}),  # 同文件第二块
            types.SimpleNamespace(score=0.3, metadata={"file_id": str(f2.id)}),
        ]
    monkeypatch.setattr(retr.HybridRetrievalService, "search", fake_search, raising=False)

    agent = AgentLoop()
    scores = await agent._rank_files_by_relevance("2023 华东销售", uuid.uuid4(), files)
    assert scores is not None
    # f1 取最高 0.9，+命中两块加权 0.03 → ~0.93；明显高于 f2 的 0.3
    assert scores[str(f1.id)] > scores[str(f2.id)]
    assert scores[str(f1.id)] >= 0.9


@pytest.mark.asyncio
async def test_rank_filename_match_boost(monkeypatch):
    """检索为空时，文件名字面匹配仍能给出相关性。"""
    import app.services.retrieval as retr

    f1 = _file("销售明细.csv")
    f2 = _file("库存.csv")
    files = [f1, f2]

    def empty_search(self, q, top_k=30):
        return []
    monkeypatch.setattr(retr.HybridRetrievalService, "search", empty_search, raising=False)

    agent = AgentLoop()
    scores = await agent._rank_files_by_relevance("销售情况怎么样", uuid.uuid4(), files)
    # 文件名含"销售"应被加分；"库存"不被匹配
    assert scores is not None
    assert scores.get(str(f1.id), 0) > 0


@pytest.mark.asyncio
async def test_rank_survives_retrieval_failure(monkeypatch):
    """检索抛异常不应让整个排序崩溃（退回文件名匹配或 None）。"""
    import app.services.retrieval as retr

    def boom(self, q, top_k=30):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(retr.HybridRetrievalService, "search", boom, raising=False)

    agent = AgentLoop()
    f1 = _file("orders.csv")
    # 不抛异常即通过（可能返回 None 或文件名匹配结果）
    result = await agent._rank_files_by_relevance("orders today", uuid.uuid4(), [f1])
    assert result is None or isinstance(result, dict)
