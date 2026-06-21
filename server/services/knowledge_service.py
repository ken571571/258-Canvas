"""知识库业务逻辑层 —— 文本分片、TF-IDF 检索、PDF 解析。

从 routes/knowledge.py 抽取可跨模块复用的核心逻辑，
供 knowledge 路由和 agent/engine.py 共用。
"""

import re
import math
from .. import config


def chunk_text(text: str, size: int = None, overlap: int = None) -> list:
    """将文本按段落切分，支持重叠（overlap）。"""
    if size is None:
        size = config.KB_CHUNK_SIZE
    if overlap is None:
        overlap = config.KB_CHUNK_OVERLAP

    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks, current = [], ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) < size:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)

    # 重叠处理：在相邻 chunk 之间添加重叠部分
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_end = chunks[i - 1][-overlap:] if len(chunks[i - 1]) > overlap else chunks[i - 1]
            overlapped.append(prev_end + "\n" + chunks[i])
        chunks = overlapped

    return [c.strip() for c in chunks if c.strip()]


def extract_pdf_text(raw: bytes, filename: str) -> str:
    """从 PDF 二进制数据中提取文本。

    优先使用 PyPDF2，回退到 pdfplumber，再回退到 pypdf。
    """
    # 尝试 PyPDF2
    try:
        from PyPDF2 import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(raw))
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        if texts:
            return "\n\n".join(texts)
    except ImportError:
        pass
    except Exception:
        pass

    # 尝试 pdfplumber
    try:
        import pdfplumber
        from io import BytesIO
        with pdfplumber.open(BytesIO(raw)) as pdf:
            texts = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
            if texts:
                return "\n\n".join(texts)
    except ImportError:
        pass
    except Exception:
        pass

    # 尝试 pypdf (原 PyPDF2 后继)
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(raw))
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        if texts:
            return "\n\n".join(texts)
    except ImportError:
        pass
    except Exception:
        pass

    raise Exception(f"无法提取 PDF 文本: {filename}。请安装 PyPDF2 (pip install PyPDF2) 或 pdfplumber。")


def tfidf_score(text: str, query_terms: set, df_cache: dict, doc_count: int) -> float:
    """计算 TF-IDF 分数。使用预计算的 DF 缓存避免 O(N²) 重复扫描。"""
    if not query_terms:
        return 0.0
    text_lower = text.lower()
    score = 0.0
    for term in query_terms:
        tf = text_lower.count(term) / max(len(text_lower), 1) * 1000
        df = df_cache.get(term, 0)
        idf = math.log((doc_count + 1) / (df + 1)) + 1
        score += tf * idf
    return score


def collect_chunks_from_index(idx: dict, kb_ids: list) -> list:
    """从知识库索引收集可检索分片（供 TF-IDF 检索使用）。"""
    chunks = []
    for kbid in kb_ids:
        kb_data = idx.get(kbid)
        if not isinstance(kb_data, dict):
            continue
        for doc in kb_data.get("documents", []):
            for chunk in doc.get("chunks", []):
                chunks.append({
                    "kb_id": kbid,
                    "filename": doc.get("filename", ""),
                    "text": chunk.get("text", ""),
                })
    return chunks


def search_chunks(chunks: list, query: str, top_k: int = 3) -> list:
    """对已收集的分片进行 TF-IDF 评分并返回 top_k 结果。"""
    if not chunks or not query:
        return []

    query_terms = set(re.findall(r"[a-zA-Z0-9一-鿿]{2,}", query.lower()))
    doc_count = max(len(chunks), 1)
    df_cache = {}
    for term in query_terms:
        df_cache[term] = sum(1 for c in chunks if term in c["text"].lower())

    for chunk in chunks:
        chunk["score"] = tfidf_score(chunk["text"], query_terms, df_cache, doc_count)

    chunks.sort(key=lambda c: c["score"], reverse=True)
    return [c for c in chunks if c["score"] > 0][:top_k]


def search_from_snapshot(snapshot: dict, kb_ids: list, query: str, top_k: int = 3) -> list:
    """从知识库快照（嵌入 agent 目录的 _kb_snapshot.json）检索分片。

    与 search_chunks 使用相同的 TF-IDF 评分逻辑，
    但数据源来自快照字典而非 _index.json，实现 Agent 跨实例拷贝后知识库仍可用。
    """
    if not kb_ids or not query or not snapshot:
        return []

    chunks = []
    for kbid in kb_ids:
        kb_data = snapshot.get(kbid)
        if not isinstance(kb_data, dict):
            continue
        for doc in kb_data.get("documents", []):
            for chunk in doc.get("chunks", []):
                chunks.append({
                    "kb_id": kbid,
                    "filename": doc.get("filename", ""),
                    "text": chunk.get("text", ""),
                })

    return search_chunks(chunks, query, top_k)
