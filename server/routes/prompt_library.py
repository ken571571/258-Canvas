"""API 路由：提示词库（Prompt Library）

存储位置：data/prompt_libraries.json
"""

import os
import json
import uuid
import time
import asyncio
from fastapi import APIRouter, HTTPException
from .. import config

router = APIRouter(prefix="/api", tags=["prompts"])

PROMPT_LIBRARY_FILE = os.path.join(config.DATA_DIR, "prompt_libraries.json")
_write_lock = asyncio.Lock()


def _now():
    return int(time.time() * 1000)


def _load() -> dict:
    if not os.path.exists(PROMPT_LIBRARY_FILE):
        return {"libraries": [{"id": "system", "name": "系统提示词库", "type": "prompt", "categories": [], "items": [], "created_at": _now()}], "active_library_id": "system"}
    with open(PROMPT_LIBRARY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def _save(data: dict):
    async with _write_lock:
        tmp = PROMPT_LIBRARY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROMPT_LIBRARY_FILE)


def _find_library(data: dict, library_id: str) -> dict:
    for lib in data.get("libraries", []):
        if lib["id"] == library_id:
            return lib
    return None


# ——— 提示词库管理 ———


@router.get("/prompts")
def list_libraries():
    return {"library": _load()}


@router.post("/prompts")
async def create_library(payload: dict):
    data = _load()
    lib = {
        "id": f"lib_{uuid.uuid4().hex[:12]}",
        "name": str(payload.get("name", "新提示词库"))[:80],
        "type": "prompt",
        "categories": [],
        "items": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    data.setdefault("libraries", []).append(lib)
    data["active_library_id"] = lib["id"]
    await _save(data)
    return {"library": data, "prompt_library": lib}


@router.delete("/prompts/{library_id}")
async def delete_library(library_id: str):
    if library_id == "system":
        raise HTTPException(status_code=400, detail="系统提示词库不能删除")
    data = _load()
    before = len(data.get("libraries", []))
    data["libraries"] = [l for l in data.get("libraries", []) if l["id"] != library_id]
    if len(data["libraries"]) == before:
        raise HTTPException(status_code=404, detail="提示词库不存在")
    if data.get("active_library_id") == library_id:
        data["active_library_id"] = "system"
    await _save(data)
    return {"library": data}


# ——— 提示词管理 ———


@router.post("/prompts/items")
async def add_item(payload: dict):
    data = _load()
    library_id = str(payload.get("library_id") or data.get("active_library_id", "system"))
    library = _find_library(data, library_id)
    if not library:
        raise HTTPException(status_code=404, detail="提示词库不存在")

    positive = str(payload.get("positive") or "").strip()
    if not positive:
        raise HTTPException(status_code=400, detail="正向提示词不能为空")

    item = {
        "id": f"tpl_{uuid.uuid4().hex[:12]}",
        "name": str(payload.get("name") or "")[:100],
        "positive": positive,
        "negative": str(payload.get("negative") or ""),
        "scene": str(payload.get("scene") or ""),
        "category": str(payload.get("category") or ""),
        "created_at": _now(),
        "updated_at": _now(),
    }
    library.setdefault("items", []).insert(0, item)
    data["active_library_id"] = library_id
    await _save(data)
    return {"library": data, "item": item}


@router.put("/prompts/items/{item_id}")
async def update_item(item_id: str, payload: dict):
    data = _load()
    for library in data.get("libraries", []):
        for i, item in enumerate(library.get("items", [])):
            if item["id"] == item_id:
                if payload.get("positive"):
                    item["positive"] = str(payload["positive"])
                item["negative"] = str(payload.get("negative", item.get("negative", "")))
                item["name"] = str(payload.get("name", item.get("name", "")))[:100]
                item["scene"] = str(payload.get("scene", item.get("scene", "")))
                item["category"] = str(payload.get("category", item.get("category", "")))
                item["updated_at"] = _now()
                library["items"][i] = item
                await _save(data)
                return {"library": data, "item": item}
    raise HTTPException(status_code=404, detail="提示词不存在")


@router.delete("/prompts/items/{item_id}")
async def delete_item(item_id: str):
    data = _load()
    for library in data.get("libraries", []):
        before = len(library.get("items", []))
        library["items"] = [i for i in library.get("items", []) if i["id"] != item_id]
        if len(library["items"]) < before:
            await _save(data)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="提示词不存在")


@router.post("/prompts/items/delete")
async def delete_items_batch(payload: dict):
    """批量删除提示词。"""
    ids = set(str(i) for i in (payload.get("ids") or []) if i)
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    data = _load()
    removed = 0
    for library in data.get("libraries", []):
        before = len(library.get("items", []))
        library["items"] = [i for i in library.get("items", []) if i["id"] not in ids]
        removed += before - len(library["items"])
    await _save(data)
    return {"ok": True, "removed": removed}


# ——— 分类管理 ———


@router.post("/prompts/categories")
async def add_category(payload: dict):
    data = _load()
    library_id = str(payload.get("library_id") or data.get("active_library_id", "system"))
    library = _find_library(data, library_id)
    if not library:
        raise HTTPException(status_code=404, detail="提示词库不存在")

    cat = {
        "id": f"cat_{uuid.uuid4().hex[:12]}",
        "name": str(payload.get("name", "新分类"))[:50],
        "created_at": _now(),
    }
    seen = {c["name"] for c in library.get("categories", [])}
    if cat["name"] in seen:
        raise HTTPException(status_code=400, detail=f"分类 {cat['name']} 已存在")
    library.setdefault("categories", []).append(cat)
    await _save(data)
    return {"library": data, "category": cat}


@router.delete("/prompts/categories/{category_id}")
async def delete_category(category_id: str):
    data = _load()
    for library in data.get("libraries", []):
        before = len(library.get("categories", []))
        library["categories"] = [c for c in library.get("categories", []) if c["id"] != category_id]
        if len(library["categories"]) < before:
            await _save(data)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="分类不存在")
