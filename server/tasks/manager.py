"""异步任务管理器。

为生图/生视频等长耗时操作提供统一的异步任务机制：
- 创建任务 → 返回 task_id
- 前端轮询 GET /api/tasks/{task_id}
- 状态机: queued → running → succeeded / failed
- JSON 文件持久化：重启后未过期任务自动恢复
"""

import os
import json
import time
import asyncio
from typing import Dict, Optional

from .. import config

TASK_TYPES = ("image_generation", "video_generation", "comfyui", "llm", "general")
TASK_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
TASK_EXPIRE_SECONDS = config.TASK_EXPIRE_SECONDS


class TaskManager:
    """内存中的异步任务管理器（含 JSON 持久化）。

    设计决策：
    - 内存为主存储（速度快），JSON 文件为持久化备份
    - 过期自动清理（1 小时后）
    - 不依赖 Celery/RQ 等外部中间件
    """

    def __init__(self):
        self._tasks: Dict[str, dict] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        # 持久化目录
        from .. import config
        self._tasks_dir = os.path.join(config.DATA_DIR, "tasks")
        os.makedirs(self._tasks_dir, exist_ok=True)
        self._load_persisted()

    # ——— 持久化 ———

    def _task_path(self, task_id: str) -> str:
        return os.path.join(self._tasks_dir, f"{task_id}.json")

    def _persist(self, task_id: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        try:
            tmp = self._task_path(task_id) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(task, f, ensure_ascii=False)
            os.replace(tmp, self._task_path(task_id))
        except Exception:
            pass  # 持久化失败不影响内存操作

    def _load_persisted(self):
        """启动时加载未过期的持久化任务。"""
        if not os.path.isdir(self._tasks_dir):
            return
        now = int(time.time() * 1000)
        for fn in os.listdir(self._tasks_dir):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(self._tasks_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    task = json.load(f)
                tid = task.get("id", fn[:-5])
                age = now - task.get("updated_at", task.get("created_at", now))
                # 跳过已过期或已完成的任务
                if age > TASK_EXPIRE_SECONDS * 1000:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    continue
                self._tasks[tid] = task
            except Exception:
                pass

    # ——— CRUD ———

    def create_task(self, task_type: str = "general") -> str:
        """创建新任务，返回 task_id。"""
        import uuid
        tid = f"task_{uuid.uuid4().hex[:16]}"
        now = int(time.time() * 1000)
        self._tasks[tid] = {
            "id": tid,
            "type": task_type if task_type in TASK_TYPES else "general",
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None,
            "progress": 0,
            "progress_message": "",
        }
        self._ensure_cleanup_task()
        self._persist(tid)
        return tid

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务状态和结果。"""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        return dict(task)

    def update_task(self, task_id: str, **kwargs):
        """更新任务状态。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        for key in ("status", "result", "error", "progress", "progress_message"):
            if key in kwargs:
                task[key] = kwargs[key]
        task["updated_at"] = int(time.time() * 1000)
        self._persist(task_id)

    def delete_task(self, task_id: str):
        """删除任务。"""
        self._tasks.pop(task_id, None)
        path = self._task_path(task_id)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def list_tasks(self, task_type: str = "", status: str = "", limit: int = 50) -> list:
        """列出任务。"""
        items = list(self._tasks.values())
        if task_type:
            items = [t for t in items if t.get("type") == task_type]
        if status:
            items = [t for t in items if t.get("status") == status]
        items.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return [dict(t) for t in items[:limit]]

    # ——— 辅助 ———

    def _ensure_cleanup_task(self):
        """在当前线程存在事件循环时启动清理协程。

        FastAPI 会把同步路由放到线程池里执行，那里没有 running loop。
        清理任务只是后台维护能力，不应该让任务创建失败。
        """
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._cleanup_task = loop.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self):
        """定期清理过期任务。"""
        while True:
            await asyncio.sleep(600)  # 每 10 分钟清理一次
            now = int(time.time() * 1000)
            expired = []
            for tid, task in self._tasks.items():
                age = now - task.get("updated_at", task.get("created_at", now))
                if age > TASK_EXPIRE_SECONDS * 1000:
                    expired.append(tid)
            for tid in expired:
                self._tasks.pop(tid, None)
                path = self._task_path(tid)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    def count(self) -> int:
        """活跃任务数。"""
        return len(self._tasks)

    def active_count(self) -> int:
        """正在运行的任务数。"""
        return sum(1 for t in self._tasks.values() if t.get("status") in ("queued", "running"))

    # ——— 重试与取消 ———

    def cancel_task(self, task_id: str) -> bool:
        """发送取消信号。运行中的任务需检查 `is_cancelled()` 并自行停止。"""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.get("status") in ("queued", "running"):
            task["status"] = "cancelled"
            task["updated_at"] = int(time.time() * 1000)
            self._persist(task_id)
            # 向 _cancel_events 发送取消信号
            ev = self._cancel_events.get(task_id)
            if ev is not None:
                ev.set()
            return True
        return False

    def retry_task(self, task_id: str) -> bool:
        """重置失败的任务为 queued，等待重新执行。"""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.get("status") == "failed":
            task["status"] = "queued"
            task["error"] = None
            task["progress"] = 0
            task["progress_message"] = ""
            task["retry_count"] = task.get("retry_count", 0) + 1
            task["updated_at"] = int(time.time() * 1000)
            self._persist(task_id)
            return True
        return False

    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被取消（运行中的任务应定期检查此标志）。"""
        task = self._tasks.get(task_id)
        if task is None:
            return True
        return task.get("status") == "cancelled"

    def _cancel_event(self, task_id: str) -> asyncio.Event:
        """获取或创建任务的取消事件（供长耗时任务使用）。"""
        if not hasattr(self, '_cancel_events'):
            self._cancel_events = {}
        if task_id not in self._cancel_events:
            self._cancel_events[task_id] = asyncio.Event()
        return self._cancel_events[task_id]


# 全局单例
task_manager = TaskManager()
