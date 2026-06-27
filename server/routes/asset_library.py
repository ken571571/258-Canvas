"""API 路由：素材库（Asset Library）

素材库结构（三层）：
  Libraries → Categories → Items

存储位置：data/asset_library.json
"""

import os
import uuid
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from .. import config
from ..storage.json_store import store
from ..utils import KeyedLockManager

router = APIRouter(prefix="/api", tags=["assets"])
_locks = KeyedLockManager()

LIBRARY_FILE = os.path.join(config.DATA_DIR, "asset_library.json")


def _now():
    return int(time.time() * 1000)


def _load_lib() -> dict:
    data = store.read(LIBRARY_FILE, default=None)
    if data is not None and isinstance(data, dict) and "libraries" in data:
        return data
    return _default_library()


async def _save_lib(data: dict):
    data["updated_at"] = _now()
    await store.write(LIBRARY_FILE, data)


def _default_library() -> dict:
    return {
        "version": 1,
        "libraries": [{
            "id": "default",
            "name": "默认素材库",
            "type": "image",
            "categories": [],
            "created_at": _now(),
            "updated_at": _now(),
        }],
        "active_library_id": "default",
    }


def _find_category(library: dict, category_id: str) -> Optional[dict]:
    for cat in library.get("categories", []):
        if cat.get("id") == category_id:
            return cat
    return None


# ——— 素材库概览 ———


@router.get("/library")
def get_asset_library():
    """获取完整素材库数据。"""
    return {"library": _load_lib()}


# ——— 分类管理 ———


@router.post("/library/categories")
async def create_category(payload: dict):
    """创建素材分类。

    payload: {name: "风景", library_id: "default"}
    """
    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()
        library_id = str(payload.get("library_id") or data.get("active_library_id", "default"))
        library = next((lib for lib in data["libraries"] if lib["id"] == library_id), None)
        if not library:
            raise HTTPException(status_code=404, detail="素材库不存在")

        cat = {
            "id": f"cat_{uuid.uuid4().hex[:12]}",
            "name": str(payload.get("name", "新分类"))[:50],
            "type": payload.get("type", "image"),
            "items": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        library.setdefault("categories", []).append(cat)
        data["active_library_id"] = library_id
        await _save_lib(data)
        return {"category": cat, "library_id": library_id}


@router.delete("/library/categories/{category_id}")
async def delete_category(category_id: str):
    """删除素材分类及其所有素材引用。"""
    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()
        removed = False
        for library in data.get("libraries", []):
            before = len(library.get("categories", []))
            library["categories"] = [c for c in library.get("categories", []) if c["id"] != category_id]
            if len(library["categories"]) < before:
                removed = True
        if not removed:
            raise HTTPException(status_code=404, detail="分类不存在")
        await _save_lib(data)
        return {"ok": True}


# ——— 素材管理 ———


@router.post("/library/items")
async def add_asset_item(payload: dict):
    """添加素材到指定分类。

    payload: {
        category_id: "cat_xxx",
        library_id: "default",
        url: "/assets/output/xxx.png",
        name: "生成的图片",
        tags: ["风景", "夕阳"]
    }
    """
    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()
        library_id = str(payload.get("library_id") or data.get("active_library_id", "default"))
        library = next((lib for lib in data["libraries"] if lib["id"] == library_id), None)
        if not library:
            raise HTTPException(status_code=404, detail="素材库不存在")

        category_id = str(payload.get("category_id", ""))
        category = _find_category(library, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="分类不存在")

        url = str(payload.get("url", "")).strip()
        if not url:
            raise HTTPException(status_code=400, detail="素材 URL 不能为空")

        item = {
            "id": f"item_{uuid.uuid4().hex[:12]}",
            "url": url,
            "name": str(payload.get("name") or "未命名素材")[:100],
            "kind": payload.get("kind", "image"),
            "tags": payload.get("tags") or [],
            "width": payload.get("width", 0),
            "height": payload.get("height", 0),
            "source": payload.get("source", ""),
            "created_at": _now(),
        }
        category.setdefault("items", []).insert(0, item)
        data["active_library_id"] = library_id
        await _save_lib(data)
        return {"item": item, "category_id": category_id}


@router.post("/library/items/batch")
async def add_asset_items_batch(payload: dict):
    """批量添加素材。

    payload: {
        category_id: "cat_xxx",
        library_id: "default",
        items: [{url: "...", name: "..."}, ...]
    }
    """
    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()
        library_id = str(payload.get("library_id") or data.get("active_library_id", "default"))
        library = next((lib for lib in data["libraries"] if lib["id"] == library_id), None)
        if not library:
            raise HTTPException(status_code=404, detail="素材库不存在")

        category_id = str(payload.get("category_id", ""))
        category = _find_category(library, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="分类不存在")

        added = []
        for raw in (payload.get("items") or [])[:200]:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not url:
                continue
            item = {
                "id": f"item_{uuid.uuid4().hex[:12]}",
                "url": url,
                "name": str(raw.get("name") or "未命名素材")[:100],
                "kind": raw.get("kind", "image"),
                "tags": raw.get("tags") or [],
                "created_at": _now(),
            }
            category.setdefault("items", []).insert(0, item)
            added.append(item)

        data["active_library_id"] = library_id
        await _save_lib(data)
        return {"items": added, "count": len(added)}


@router.delete("/library/items/{item_id}")
async def delete_asset_item(item_id: str):
    """删除素材引用（不删除物理文件）。"""
    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()
        removed = False
        for library in data.get("libraries", []):
            for category in library.get("categories", []):
                before = len(category.get("items", []))
                category["items"] = [i for i in category.get("items", []) if i["id"] != item_id]
                if len(category["items"]) < before:
                    removed = True
        if not removed:
            raise HTTPException(status_code=404, detail="素材不存在")
        await _save_lib(data)
        return {"ok": True}


@router.post("/library/items/delete")
async def delete_asset_items_batch(payload: dict):
    """批量删除素材引用。"""
    ids = set(str(i) for i in (payload.get("ids") or []) if i)
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()
        removed = 0
        for library in data.get("libraries", []):
            for category in library.get("categories", []):
                before = len(category.get("items", []))
                category["items"] = [i for i in category.get("items", []) if i["id"] not in ids]
                removed += before - len(category["items"])
        await _save_lib(data)
        return {"ok": True, "removed": removed}


@router.post("/library/items/move")
async def move_asset_items(payload: dict):
    """移动素材到其他分类。"""
    item_ids = set(str(i) for i in (payload.get("ids") or []) if i)
    target_category_id = str(payload.get("target_category_id") or "")
    target_library_id = str(payload.get("target_library_id") or "")

    if not item_ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    lock = await _locks.get(LIBRARY_FILE)
    async with lock:
        data = _load_lib()

        # 找到目标分类
        target_category = None
        for library in data.get("libraries", []):
            if target_library_id and library["id"] != target_library_id:
                continue
            target_category = _find_category(library, target_category_id)
            if target_category:
                break

        if not target_category:
            raise HTTPException(status_code=404, detail="目标分类不存在")

        moved = 0
        for library in data.get("libraries", []):
            for category in library.get("categories", []):
                keep = []
                for item in category.get("items", []):
                    if item["id"] in item_ids:
                        target_category.setdefault("items", []).append(item)
                        moved += 1
                    else:
                        keep.append(item)
                if len(keep) < len(category.get("items", [])):
                    category["items"] = keep

        await _save_lib(data)
        return {"ok": True, "moved": moved}
