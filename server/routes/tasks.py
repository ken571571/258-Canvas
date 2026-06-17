"""API 路由：异步任务管理 —— 薄路由层，业务逻辑委托给 services/task_service.py"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..services.task_service import (
    create_task as svc_create_task,
    get_task as svc_get_task,
    delete_task as svc_delete_task,
    list_tasks as svc_list_tasks,
    get_stats as svc_get_stats,
)

router = APIRouter(prefix="/api", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    task_type: str = "general"


@router.get("/tasks")
def list_tasks(task_type: str = "", status: str = ""):
    """列出任务（支持按类型和状态过滤）。"""
    return {"tasks": svc_list_tasks(task_type=task_type, status=status)}


@router.post("/tasks")
async def create_task(req: TaskCreateRequest):
    """创建新任务，返回 task_id 供后续轮询。"""
    tid = svc_create_task(req.task_type)
    return {"task_id": tid, "status": "queued"}


@router.get("/tasks/stats")
def task_stats():
    """获取任务统计信息。"""
    return svc_get_stats()


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    """查询任务状态和结果。"""
    task = svc_get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    """手动删除任务（释放内存）。"""
    svc_delete_task(task_id)
    return {"ok": True}
