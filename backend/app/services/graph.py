"""知识图谱服务 - NetworkX + JSON 持久化
适配自 DataMind NetworkXGraphStore + IngestService 三元组抽取"""
import json
import os
from pathlib import Path
from typing import Optional

import networkx as nx
from anthropic import AsyncAnthropic

from app.config import settings


TRIPLE_EXTRACTION_PROMPT = """从以下文本中提取知识图谱三元组（主体-关系-客体）。

要求：
1. 提取文本中明确表达的实体关系
2. 主体和客体应为具体的实体名称（人名、地名、组织、概念等）
3. 关系应为简洁的动词或短语
4. 最多提取 {max_triples} 个三元组
5. 只返回 JSON 数组，不要其他内容

输出格式（严格 JSON）：
[
  {{"subject": "实体A", "relation": "关系", "object": "实体B"}},
  ...
]

文本：
{text}"""


class GraphService:
    """每个 data_space 一个独立的知识图谱"""

    def __init__(self, user_id: str, data_space_id: str):
        self.user_id = user_id
        self.data_space_id = data_space_id
        self._graph: Optional[nx.MultiDiGraph] = None
        self._storage_path = self._get_storage_path()

    def _get_storage_path(self) -> Path:
        path = Path(settings.storage_root) / self.user_id / self.data_space_id
        path.mkdir(parents=True, exist_ok=True)
        return path / "graph.json"

    @property
    def graph(self) -> nx.MultiDiGraph:
        if self._graph is None:
            self._graph = self._load()
        return self._graph

    def _load(self) -> nx.MultiDiGraph:
        """从 JSON 加载图谱"""
        g = nx.MultiDiGraph()
        if not self._storage_path.exists():
            return g

        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                g.add_node(node["id"], label=node.get("label", node["id"]),
                          type=node.get("type", ""), **node.get("props", {}))
            for edge in data.get("edges", []):
                g.add_edge(edge["src"], edge["dst"], relation=edge["rel"],
                          weight=edge.get("w", 1.0), **edge.get("props", {}))
        except (json.JSONDecodeError, KeyError):
            pass
        return g

    async def persist(self) -> None:
        """持久化到 JSON"""
        nodes = []
        for nid, attrs in self.graph.nodes(data=True):
            nodes.append({
                "id": nid,
                "label": attrs.get("label", nid),
                "type": attrs.get("type", ""),
                "props": {k: v for k, v in attrs.items() if k not in ("label", "type")},
            })

        edges = []
        for src, dst, attrs in self.graph.edges(data=True):
            edges.append({
                "src": src,
                "dst": dst,
                "rel": attrs.get("relation", "related_to"),
                "w": attrs.get("weight", 1.0),
                "props": {k: v for k, v in attrs.items() if k not in ("relation", "weight")},
            })

        data = {"nodes": nodes, "edges": edges}
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    async def upsert_triples(self, triples: list[dict]) -> dict:
        """插入三元组到图谱"""
        added = 0
        for t in triples:
            subj = t.get("subject", "").strip()
            rel = t.get("relation", "related_to").strip()
            obj = t.get("object", "").strip()
            if not subj or not obj:
                continue

            if not self.graph.has_node(subj):
                self.graph.add_node(subj, label=subj, type="entity")
            if not self.graph.has_node(obj):
                self.graph.add_node(obj, label=obj, type="entity")

            self.graph.add_edge(subj, obj, relation=rel, weight=1.0)
            added += 1

        if added > 0:
            await self.persist()
        return {"added": added, "total_nodes": self.graph.number_of_nodes(), "total_edges": self.graph.number_of_edges()}

    async def extract_triples_from_text(self, text: str, max_triples: int = 30) -> dict:
        """用 LLM 从文本中抽取三元组"""
        if not text.strip():
            return {"triples": [], "added": 0}

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        prompt = TRIPLE_EXTRACTION_PROMPT.format(text=text[:5000], max_triples=max_triples)

        try:
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            triples = json.loads(raw)
            if not isinstance(triples, list):
                return {"triples": [], "added": 0}
        except (json.JSONDecodeError, Exception):
            return {"triples": [], "added": 0}

        result = await self.upsert_triples(triples)
        result["triples"] = triples
        return result

    async def search_entities(self, query: str, top_k: int = 5) -> list[dict]:
        """模糊搜索实体节点"""
        query_lower = query.lower()
        scored = []
        for nid, attrs in self.graph.nodes(data=True):
            label = attrs.get("label", nid)
            if query_lower in label.lower() or query_lower in nid.lower():
                score = 1.0 if query_lower == label.lower() else 0.5
                scored.append({
                    "id": nid,
                    "label": label,
                    "type": attrs.get("type", ""),
                    "degree": self.graph.degree(nid),
                    "score": score,
                })
        scored.sort(key=lambda x: (-x["score"], -x["degree"]))
        return scored[:top_k]

    async def traverse(self, start: str, max_hops: int = 2, relation_filter: list[str] | None = None) -> list[dict]:
        """从实体出发 BFS 遍历"""
        if not self.graph.has_node(start):
            return []

        visited = set()
        paths = []
        queue = [(start, 0, [])]

        while queue:
            node, depth, path = queue.pop(0)
            if depth > max_hops:
                break
            if node in visited:
                continue
            visited.add(node)

            if path:
                paths.append({"path": path, "depth": depth})

            for _, neighbor, attrs in self.graph.edges(node, data=True):
                rel = attrs.get("relation", "")
                if relation_filter and rel not in relation_filter:
                    continue
                if neighbor not in visited:
                    step = {"from": node, "relation": rel, "to": neighbor}
                    queue.append((neighbor, depth + 1, path + [step]))

        return paths[:50]

    async def neighbors(self, entity: str, direction: str = "both") -> list[dict]:
        """获取实体的直接邻居"""
        if not self.graph.has_node(entity):
            return []

        results = []
        if direction in ("out", "both"):
            for _, target, attrs in self.graph.out_edges(entity, data=True):
                results.append({
                    "entity": target,
                    "relation": attrs.get("relation", ""),
                    "direction": "out",
                    "label": self.graph.nodes[target].get("label", target),
                })
        if direction in ("in", "both"):
            for source, _, attrs in self.graph.in_edges(entity, data=True):
                results.append({
                    "entity": source,
                    "relation": attrs.get("relation", ""),
                    "direction": "in",
                    "label": self.graph.nodes[source].get("label", source),
                })
        return results

    def stats(self) -> dict:
        """图谱统计信息"""
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "connected_components": nx.number_weakly_connected_components(self.graph) if self.graph.number_of_nodes() > 0 else 0,
        }

    def export_for_frontend(self) -> dict:
        """导出为前端可视化格式"""
        nodes = []
        for nid, attrs in self.graph.nodes(data=True):
            nodes.append({
                "id": nid,
                "name": attrs.get("label", nid),
                "category": attrs.get("type", "entity"),
                "symbolSize": min(10 + self.graph.degree(nid) * 3, 50),
            })

        edges = []
        for src, dst, attrs in self.graph.edges(data=True):
            edges.append({
                "source": src,
                "target": dst,
                "name": attrs.get("relation", ""),
            })

        return {"nodes": nodes, "edges": edges}
