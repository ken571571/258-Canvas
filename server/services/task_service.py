"""任务服务 —— 轻量包装 TaskManager，供路由层调用。

职责：
- 封装 task_manager 的 CRUD 操作
- 提供任务统计
- 路由层只需导入本模块，不直接依赖 task_manager 内部实现

后续扩展点（取消/重试/队列限制）应加在此层，不塞进 route。
"""

from ..tasks.manager import task_manager


def create_task(task_type: str = "general") -> str:
    """创建新任务，返回 task_id。"""
    return task_manager.create_task(task_type)


def get_task(task_id: str) -> dict | None:
    """查询任务状态和结果。不存在时返回 None。"""
    return task_manager.get_task(task_id)


def update_task(task_id: str, **kwargs):
    """更新任务状态/进度/结果。"""
    task_manager.update_task(task_id, **kwargs)


def delete_task(task_id: str):
    """删除任务。"""
    task_manager.delete_task(task_id)


def list_tasks(task_type: str = "", status: str = "") -> list:
    """列出任务（支持过滤）。"""
    return task_manager.list_tasks(task_type=task_type, status=status)


def cancel_task(task_id: str) -> bool:
    """取消运行中或排队中的任务。"""
    return task_manager.cancel_task(task_id)


def retry_task(task_id: str) -> bool:
    """重试失败的任务。"""
    return task_manager.retry_task(task_id)


def get_stats() -> dict:
    """获取任务统计信息。"""
    return {
        "total": task_manager.count(),
        "active": task_manager.active_count(),
    }
