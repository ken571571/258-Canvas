"""API 路由：画布管理

画布存储结构（每个画布一个独立目录，可直接跨实例复制）：
  canvases/{名称}_{id前8位}/
    ├── canvas.json      ← 画布完整数据（节点/连线/分组/数据）
    └── files/           ← 画布引用的所有媒体文件（自包含）

与 Agent 存储模式一致：拷贝整个目录即可迁移到另一台机器。

路由层职责：HTTP 参数校验、状态码转换、WebSocket 广播。
业务逻辑全部委托给 services/canvas_service.py。
"""

import uuid
from fastapi import APIRouter, HTTPException
from .. import config
from ..storage.json_store import store
from ..websocket.manager import manager
from ..models import CanvasCreateRequest, CanvasMetaUpdate
from ..exceptions import AppError, ConflictError
from ..services import canvas_service

router = APIRouter(prefix="/api", tags=["canvas"])


# ——— 异常转换辅助 ———


def _to_http(exc: AppError) -> HTTPException:
    """将 AppError 转换为 FastAPI HTTPException。"""
    d = exc.to_dict()
    return HTTPException(status_code=exc.status_code, detail=d)


# ——— 路由 ———


@router.get("/boards")
def list_canvases():
    return {"canvases": canvas_service.list_all()}


@router.post("/boards")
async def create_canvas(req: CanvasCreateRequest):
    title = (req.title or "未命名画布")[:80]
    canvas, dir_name = canvas_service.create(title)
    await canvas_service.save(canvas)
    return {"canvas": canvas, "_dir": dir_name}


@router.get("/boards/{canvas_id}")
def get_canvas(canvas_id: str):
    try:
        return {"canvas": canvas_service.load(canvas_id)}
    except AppError as e:
        raise _to_http(e)


@router.put("/boards/{canvas_id}")
async def save_canvas(canvas_id: str, payload: dict):
    # v2.5.51：画布线写锁保护 load → merge → save 全事务，防止并发覆盖
    async with canvas_service.lock_canvas(canvas_id):
        try:
            existing = canvas_service.load(canvas_id)
        except AppError as e:
            raise _to_http(e)

        try:
            canvas = canvas_service.merge_from_payload(existing, payload)
        except ConflictError as e:
            # 冲突时返回 409 + 最新数据，供前端自动刷新
            raise HTTPException(
                status_code=409,
                detail={
                    "message": e.message,
                    "canvas": existing,
                    "updated_at": existing.get("updated_at", 0),
                },
            )

        await canvas_service.save(canvas)

    # 广播更新（携带 client_id 避免回环）—— 锁外广播，避免阻塞
    client_id = payload.get("client_id", "")
    await manager.broadcast_board_synced(canvas_id, canvas["updated_at"], client_id)
    return {"canvas": canvas}


@router.post("/boards/{canvas_id}/meta")
async def update_canvas_meta(canvas_id: str, payload: CanvasMetaUpdate):
    """更新画布元数据（标题/图标/颜色/置顶等），不刷新 updated_at。

    直接写入 canvas.json 而非通过 save()，避免触发文件同步和 updated_at 变更。
    """
    try:
        existing = canvas_service.load(canvas_id)
    except AppError as e:
        raise _to_http(e)

    canvas_service.update_meta(existing, payload)
    await store.write(canvas_service._canvas_path(canvas_id), existing)
    return {"canvas": existing}


@router.delete("/boards/{canvas_id}")
async def delete_canvas(canvas_id: str):
    try:
        c = canvas_service.load(canvas_id)
    except AppError as e:
        raise _to_http(e)

    canvas_service.soft_delete(c)
    await canvas_service.save(c)
    return {"ok": True}


@router.delete("/boards/{canvas_id}/permanent")
async def delete_canvas_permanent(canvas_id: str):
    """永久删除画布（清空整个目录，不可恢复）。"""
    try:
        c = canvas_service.load(canvas_id)
    except AppError as e:
        raise _to_http(e)

    canvas_service.hard_delete(c)
    return {"ok": True, "permanent": True}


@router.post("/boards/{canvas_id}/duplicate")
async def duplicate_canvas(canvas_id: str):
    """创建画布副本（含所有节点、连线、分组）。"""
    try:
        existing = canvas_service.load(canvas_id)
    except AppError as e:
        raise _to_http(e)

    new_canvas, dir_name = canvas_service.duplicate(existing)
    await canvas_service.save(new_canvas)
    return {"canvas": new_canvas, "_dir": dir_name}
