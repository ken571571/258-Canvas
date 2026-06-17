"""API 路由：画布管理"""

import os
import json
import uuid
import time
from fastapi import APIRouter, HTTPException
from ..models import CanvasCreateRequest, CanvasMetaUpdate
from .. import config
from ..storage.json_store import store
from ..websocket.manager import manager

router = APIRouter(prefix="/api", tags=["canvas"])


def _now():
    return int(time.time() * 1000)


def _path(cid):
    return os.path.join(config.CANVAS_DIR, f"{cid}.json")


def _load(cid):
    p = _path(cid)
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="画布不存在")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


async def _save(c):
    """原子写入画布（自动更新 updated_at）。"""
    await store.write_with_timestamp(_path(c["id"]), c)


def _list():
    items = []
    if not os.path.isdir(config.CANVAS_DIR):
        return items
    for fn in os.listdir(config.CANVAS_DIR):
        if fn.endswith(".json"):
            path = _path(fn[:-5])
            try:
                with open(path, "r", encoding="utf-8") as f:
                    c = json.load(f)
                if not c.get("deleted_at"):
                    items.append(c)
            except Exception:
                pass
    items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return items


@router.get("/boards")
def list_canvases():
    return {"canvases": _list()}


@router.post("/boards")
async def create_canvas(req: CanvasCreateRequest):
    cid = uuid.uuid4().hex[:16]
    now = _now()
    canvas = {
        "id": cid,
        "title": req.title or "未命名画布",
        "created_at": now,
        "updated_at": now,
        "nodes": [],
        "connections": [],
        "groups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    await _save(canvas)
    return {"canvas": canvas}


@router.get("/boards/{canvas_id}")
def get_canvas(canvas_id: str):
    return {"canvas": _load(canvas_id)}


@router.put("/boards/{canvas_id}")
async def save_canvas(canvas_id: str, payload: dict):
    # _load 会在画布不存在时抛出 404，所以不需要额外检查 existing
    existing = _load(canvas_id)

    # ——— 乐观并发控制 ———
    base_updated_at = payload.get("base_updated_at")
    current_updated_at = existing.get("updated_at", 0)
    if base_updated_at and current_updated_at and int(base_updated_at) < current_updated_at:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "画布已被其他页面更新，已拒绝旧版本覆盖。请刷新页面获取最新数据。",
                "canvas": existing,
                "updated_at": current_updated_at,
            },
        )

    canvas = {
        "id": canvas_id,
        "title": payload.get("title", existing.get("title", "未命名画布")),
        "created_at": existing.get("created_at", _now()),
        "updated_at": _now(),
        "nodes": payload.get("nodes", existing.get("nodes", [])),
        "connections": payload.get("connections", existing.get("connections", [])),
        "groups": payload.get("groups", existing.get("groups", [])),
        "viewport": payload.get("viewport", existing.get("viewport", {"x": 0, "y": 0, "scale": 1})),
        # 保留扩展字段
        "icon": payload.get("icon", existing.get("icon", "layers")),
        "kind": payload.get("kind", existing.get("kind", "default")),
        "logs": payload.get("logs", existing.get("logs", [])),
        "settings": payload.get("settings", existing.get("settings", {})),
    }
    await _save(canvas)
    # 广播更新，携带 client_id 避免回环
    client_id = payload.get("client_id", "")
    await manager.broadcast_board_synced(canvas_id, canvas["updated_at"], client_id)
    return {"canvas": canvas}


# ——— 画布元数据（轻量更新，不触发 updated_at 排序变化） ———


@router.post("/boards/{canvas_id}/meta")
async def update_canvas_meta(canvas_id: str, payload: dict):
    """更新画布元数据（标题/图标/颜色/置顶等），不刷新 updated_at，
    避免打标签、置顶等操作改变画布列表排序。"""
    existing = _load(canvas_id)

    if payload.get("title") is not None:
        existing["title"] = (str(payload["title"]) or existing.get("title") or "未命名画布")[:80]
    if payload.get("icon") is not None:
        existing["icon"] = (str(payload["icon"]) or "layers")[:32]
    if payload.get("color") is not None:
        existing["color"] = str(payload["color"])[:20]
    if payload.get("owner") is not None:
        existing["owner"] = str(payload["owner"]).strip()[:40]
    if payload.get("pinned") is not None:
        existing["pinned"] = bool(payload["pinned"])
    if payload.get("kind") is not None:
        existing["kind"] = str(payload["kind"])[:20]

    # 原子写入，不更改 updated_at（元数据更新不影响排序）
    await store.write(_path(canvas_id), existing)

    return {"canvas": existing}


@router.delete("/boards/{canvas_id}")
async def delete_canvas(canvas_id: str):
    c = _load(canvas_id)
    c["deleted_at"] = _now()
    await _save(c)
    return {"ok": True}
