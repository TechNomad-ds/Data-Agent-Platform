"""文本分段服务 - 基于 DataMind 的贪心分段策略"""
import re
from typing import List, Dict, Any


def greedy_chunk(
    text: str,
    max_size: int = 1000,
    overlap: int = 200,
) -> List[Dict[str, Any]]:
    """贪心分段：优先段落边界 → 句子边界 → 硬切"""
    if not text.strip():
        return []

    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""
    start_char = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 1 <= max_size:
            current = current + "\n\n" + para if current else para
        else:
            if current:
                chunks.append({
                    "text": current,
                    "start_char": start_char,
                    "end_char": start_char + len(current),
                })
                overlap_text = current[-overlap:] if len(current) > overlap else current
                start_char += len(current) - len(overlap_text)
                current = overlap_text + "\n\n" + para if overlap > 0 else para
            else:
                sentences = _split_sentences(para)
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_size:
                        current = current + " " + sent if current else sent
                    else:
                        if current:
                            chunks.append({
                                "text": current,
                                "start_char": start_char,
                                "end_char": start_char + len(current),
                            })
                            overlap_text = current[-overlap:] if len(current) > overlap else current
                            start_char += len(current) - len(overlap_text)
                            current = overlap_text + " " + sent if overlap > 0 else sent
                        else:
                            for i in range(0, len(sent), max_size - overlap):
                                chunk_text = sent[i:i + max_size]
                                chunks.append({
                                    "text": chunk_text,
                                    "start_char": start_char + i,
                                    "end_char": start_char + i + len(chunk_text),
                                })
                            start_char += len(sent)
                            current = ""

    if current.strip():
        chunks.append({
            "text": current,
            "start_char": start_char,
            "end_char": start_char + len(current),
        })

    return chunks


def _split_sentences(text: str) -> List[str]:
    """中英文句子分割"""
    pattern = r'(?<=[。！？.!?])\s*'
    sentences = re.split(pattern, text)
    return [s.strip() for s in sentences if s.strip()]
