"""API 路由：知识库"""

import os
import uuid
import time
import re
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from .. import config
from ..storage.json_store import store
from ..services import knowledge_service

router = APIRouter(prefix="/api", tags=["knowledge"])


class KbUploadPayload(BaseModel):
    filename: str = ""
    content: str = ""


KB_DIR = config.KB_DIR
os.makedirs(KB_DIR, exist_ok=True)

def _index_path():
    return os.path.join(KB_DIR, "_index.json")


def _load_index():
    """读取知识库索引（使用 JsonStore 缓存）。"""
    return store.read(_index_path(), default={})


async def _save_index(idx):
    """写入索引（使用 JsonStore 统一管理）。"""
    await store.write(_index_path(), idx)


def _kb_file(kbid):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", kbid)
    return os.path.join(KB_DIR, f"{safe}.json")


def _kb_document_chunks(kb_ids: list) -> list:
    """从当前知识库索引收集可检索分片。"""
    idx = _load_index()
    return knowledge_service.collect_chunks_from_index(idx, kb_ids)


def search_kb_chunks(kb_ids: list, query: str, top_k: int = 3) -> list:
    """搜索知识库分片，供 API 路由和 Agent 共用。"""
    if not kb_ids or not query:
        return []
    all_chunks = _kb_document_chunks(kb_ids)
    return knowledge_service.search_chunks(all_chunks, query, top_k)


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


class KbCreatePayload(BaseModel):
    name: str = "默认知识库"
    description: str = ""


@router.post("/knowledge-bases")
async def create_kb(payload: KbCreatePayload):
    idx = _load_index()
    kbid = f"kb_{uuid.uuid4().hex[:8]}"
    idx[kbid] = {
        "name": (payload.name or "默认知识库")[:80],
        "description": (payload.description or "")[:500],
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
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（最大 50MB）")
    filename = os.path.basename(file.filename or "未命名.txt")
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


def _chunk_text(text: str, size: int = None, overlap: int = None) -> list:
    """将文本按段落切分，支持重叠（overlap）。"""
    return knowledge_service.chunk_text(text, size, overlap)


def _extract_pdf_text(raw: bytes, filename: str) -> str:
    """从 PDF 二进制数据中提取文本。"""
    return knowledge_service.extract_pdf_text(raw, filename)


def search_kb_chunks_from_snapshot(snapshot: dict, kb_ids: list, query: str, top_k: int = 3) -> list:
    """从知识库快照检索分片。"""
    return knowledge_service.search_from_snapshot(snapshot, kb_ids, query, top_k)


def _tfidf_score(text: str, query_terms: set, df_cache: dict, doc_count: int) -> float:
    """计算 TF-IDF 分数。"""
    return knowledge_service.tfidf_score(text, query_terms, df_cache, doc_count)
