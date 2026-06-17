"""API 路由：知识库"""

import os
import uuid
import time
import json
import re
import math
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from .. import config
from ..utils import KeyedLockManager

router = APIRouter(prefix="/api", tags=["knowledge"])


class KbUploadPayload(BaseModel):
    filename: str = ""
    content: str = ""


KB_DIR = config.KB_DIR
os.makedirs(KB_DIR, exist_ok=True)

# 文件写锁（防止并发损坏）
_locks = KeyedLockManager()


def _index_path():
    return os.path.join(KB_DIR, "_index.json")


def _load_index():
    """同步读取索引（读操作不需要锁）。"""
    if os.path.exists(_index_path()):
        with open(_index_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


async def _save_index(idx):
    """异步写入索引（带锁）。"""
    lock = await _locks.get("_index")
    async with lock:
        # 先写临时文件，再原子替换
        tmp = _index_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _index_path())


def _kb_file(kbid):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", kbid)
    return os.path.join(KB_DIR, f"{safe}.json")


def _kb_document_chunks(kb_ids: list) -> list:
    """从当前知识库索引收集可检索分片。"""
    idx = _load_index()
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


def search_kb_chunks(kb_ids: list, query: str, top_k: int = 3) -> list:
    """搜索知识库分片，供 API 路由和 Agent 共用。"""
    if not kb_ids or not query:
        return []

    all_chunks = _kb_document_chunks(kb_ids)
    for chunk in all_chunks:
        chunk["score"] = _tfidf_score(chunk["text"], query, all_chunks)

    all_chunks.sort(key=lambda c: c["score"], reverse=True)
    return [c for c in all_chunks if c["score"] > 0][:top_k]


# ——— 知识库 CRUD ———


@router.get("/knowledge-bases")
def list_kbs():
    idx = _load_index()
    return {
        "knowledge_bases": [
            {
                "id": k, "name": v.get("name", k),
                "description": v.get("description", ""),
                "document_count": len(v.get("documents", [])),
                "created_at": v.get("created_at", 0),
            }
            for k, v in idx.items()
        ]
    }


@router.post("/knowledge-bases")
async def create_kb(payload: dict):
    idx = _load_index()
    kbid = f"kb_{uuid.uuid4().hex[:8]}"
    idx[kbid] = {
        "name": str(payload.get("name", "默认知识库"))[:80],
        "description": str(payload.get("description", ""))[:500],
        "documents": [],
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    }
    await _save_index(idx)
    return {"knowledge_base": {"id": kbid, "name": idx[kbid]["name"], "document_count": 0}}


@router.delete("/knowledge-bases/{kb_id}")
async def delete_kb(kb_id: str):
    idx = _load_index()
    if kb_id not in idx:
        raise HTTPException(status_code=404, detail="知识库不存在")
    del idx[kb_id]
    await _save_index(idx)
    # 删除文件
    kbf = _kb_file(kb_id)
    if os.path.exists(kbf):
        os.remove(kbf)
    return {"ok": True}


# ——— 文档管理 ———


@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: str):
    idx = _load_index()
    if kb_id not in idx:
        raise HTTPException(status_code=404, detail="知识库不存在")
    docs = idx[kb_id].get("documents", [])
    return {
        "documents": [
            {"id": d["id"], "filename": d.get("filename", ""),
             "chunk_count": len(d.get("chunks", [])), "created_at": d.get("created_at", 0)}
            for d in docs
        ]
    }


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(kb_id: str, payload: KbUploadPayload):
    idx = _load_index()
    if kb_id not in idx:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="文档内容不能为空")

    # 分片
    chunks = _chunk_text(payload.content)
    doc = {
        "id": f"doc_{uuid.uuid4().hex[:8]}",
        "filename": payload.filename or "未命名.md",
        "content": payload.content,
        "chunks": [{"index": i, "text": c} for i, c in enumerate(chunks)],
        "created_at": int(time.time() * 1000),
    }
    idx[kb_id].setdefault("documents", []).append(doc)
    idx[kb_id]["updated_at"] = int(time.time() * 1000)
    await _save_index(idx)
    return {"document": {"id": doc["id"], "filename": doc["filename"], "chunk_count": len(chunks)}}


@router.post("/knowledge-bases/{kb_id}/documents/upload")
async def upload_document_file(kb_id: str, file: UploadFile = File(...)):
    """上传文件文档（支持 .txt .md .pdf）。

    PDF 文件会自动提取文本内容后进行分片。
    """
    idx = _load_index()
    if kb_id not in idx:
        raise HTTPException(status_code=404, detail="知识库不存在")

    raw = await file.read()
    filename = file.filename or "未命名.txt"
    ext = os.path.splitext(filename)[1].lower()

    # 提取文本
    if ext == ".pdf":
        content = _extract_pdf_text(raw, filename)
    elif ext in (".txt", ".md", ".markdown", ".rst", ".text"):
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = raw.decode("gbk")
            except Exception:
                raise HTTPException(status_code=400, detail="无法识别文件编码，请使用 UTF-8 编码的文本文件")
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，支持 .txt .md .pdf")

    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 分片
    chunks = _chunk_text(content)
    doc = {
        "id": f"doc_{uuid.uuid4().hex[:8]}",
        "filename": filename,
        "content": content,
        "chunks": [{"index": i, "text": c} for i, c in enumerate(chunks)],
        "created_at": int(time.time() * 1000),
    }
    idx[kb_id].setdefault("documents", []).append(doc)
    idx[kb_id]["updated_at"] = int(time.time() * 1000)
    await _save_index(idx)
    return {"document": {"id": doc["id"], "filename": doc["filename"], "chunk_count": len(chunks)}}


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str):
    idx = _load_index()
    if kb_id not in idx:
        raise HTTPException(status_code=404, detail="知识库不存在")
    docs = idx[kb_id].get("documents", [])
    idx[kb_id]["documents"] = [d for d in docs if d["id"] != doc_id]
    idx[kb_id]["updated_at"] = int(time.time() * 1000)
    await _save_index(idx)
    return {"ok": True}


# ——— 检索 ———


@router.post("/knowledge-bases/search")
def search_knowledge(payload: dict):
    kb_ids = payload.get("kb_ids", [])
    query = payload.get("query", "")
    top_k = int(payload.get("top_k", 3))

    return {"results": search_kb_chunks(kb_ids, query, top_k)}


# ——— 工具函数 ———


def _chunk_text(text: str, size: int = 500, overlap: int = 100) -> list:
    """将文本按段落切分，支持重叠（overlap）。"""
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
            curr_start = chunks[i][:overlap] if len(chunks[i]) > overlap else chunks[i]
            # 将前一个 chunk 的尾部追加到当前 chunk 开头
            overlapped.append(prev_end + "\n" + chunks[i])
        chunks = overlapped

    return [c.strip() for c in chunks if c.strip()]


def _extract_pdf_text(raw: bytes, filename: str) -> str:
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
            text = page.extract_text()
            if text:
                texts.append(text)
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
                text = page.extract_text()
                if text:
                    texts.append(text)
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
            text = page.extract_text()
            if text:
                texts.append(text)
        if texts:
            return "\n\n".join(texts)
    except ImportError:
        pass
    except Exception:
        pass

    raise Exception(f"无法提取 PDF 文本: {filename}。请安装 PyPDF2 (pip install PyPDF2) 或 pdfplumber。")


def _tfidf_score(text: str, query: str, all_chunks: list) -> float:
    """计算 TF-IDF 分数。all_chunks 必须为已完整构建的列表。"""
    query_terms = set(re.findall(r"[a-zA-Z0-9一-鿿]{2,}", query.lower()))
    if not query_terms:
        return 0.0
    text_lower = text.lower()
    doc_count = max(len(all_chunks), 1)
    score = 0.0
    for term in query_terms:
        tf = text_lower.count(term) / max(len(text_lower), 1) * 1000
        df = sum(1 for c in all_chunks if term in c["text"].lower())
        idf = math.log((doc_count + 1) / (df + 1)) + 1
        score += tf * idf
    return score
