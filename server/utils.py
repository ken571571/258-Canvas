"""共享工具类 —— 减少跨路由模块的重复代码。

- KeyedLockManager: 按 key 分配 asyncio.Lock 的管理器（文件写锁，含定期清理）
- safe_join: 从 server.security.paths 重新导出（安全路径拼接）
- resolve_gen_size: 解析图生图尺寸倍率标记为实际像素尺寸
"""

import asyncio
import time
import os

# v2.5.51：使用 monotonic 防止系统时钟回拨导致锁过期判断异常
_monotonic = time.monotonic
import base64
from .logging_config import get_logger

# 从 security.paths 重新导出，保持向后兼容
from .security.paths import safe_join  # noqa: F401

_log = get_logger("utils")


class KeyedLockManager:
    """按 key 管理多个 asyncio.Lock，用于保护按 ID 分片的 JSON 文件写操作。

    使用方式:
        _locks = KeyedLockManager()

        async def save_xxx(data):
            lock = await _locks.get(data["id"])
            async with lock:
                ...  # 写文件

    每小时自动清理 1 小时未访问的锁，防止内存无限增长。
    """

    def __init__(self):
        self._locks: dict = {}
        self._last_access: dict = {}          # key → timestamp
        self._manager = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def get(self, key: str) -> asyncio.Lock:
        async with self._manager:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            self._last_access[key] = _monotonic()
            # 启动清理任务（如尚未运行）
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            return self._locks[key]

    async def _periodic_cleanup(self):
        """每小时清理一次超过 1 小时未访问的锁。"""
        while True:
            await asyncio.sleep(3600)
            now = _monotonic()
            async with self._manager:
                stale = [
                    k for k, t in self._last_access.items()
                    if now - t > 3600
                ]
                for k in stale:
                    self._locks.pop(k, None)
                    self._last_access.pop(k, None)


# ——— 图生图尺寸解析 ———


def resolve_gen_size(size: str, reference_images: list) -> str:
    """图生图尺寸处理：解析倍率标记 (x2, x3, custom:2048 等) 为实际像素尺寸。

    如果 size 是标准像素格式 (如 "1024x1024") 或 API 原生格式 ("16:9", "auto")，直接返回。
    """
    from . import config

    size_lower = str(size or "").lower().strip()
    # 标准像素格式 / API 原生格式 → 直接放行
    # "custom" 无冒号 = 选了自定义但未确认 → 等同跟随
    if size_lower == "custom":
        size_lower = ""
    if not size_lower or size_lower in ("auto", "follow") or size_lower.startswith("x") or size_lower.startswith("custom:"):
        pass  # 需要解析
    else:
        return size  # 已经是像素或原生格式，原样返回

    if not reference_images:
        return size  # 无参考图，原样返回（文生图不管）

    # 从参考图读取原始尺寸
    ref_url = str(reference_images[0] or "").strip()
    try:
        if ref_url.startswith("data:"):
            parts = ref_url.split(",", 1)
            if len(parts) < 2:
                return size
            _, b64 = parts
            img_bytes = base64.b64decode(b64)
            from PIL import Image as PILImage
            import io as _io
            orig_w, orig_h = PILImage.open(_io.BytesIO(img_bytes)).size
        elif ref_url.startswith(("http://", "https://")):
            return size
        else:
            local = safe_join(config.BASE_DIR, ref_url.lstrip("/"))
            # v2.5.40：PIL.open(local) 只读文件头，不加载完整文件到内存
            from PIL import Image as PILImage
            orig_w, orig_h = PILImage.open(local).size
    except Exception as e:
        _log.debug(f"读取参考图尺寸失败，使用原始 size={size}: {e}")
        return size  # 读图失败，原样返回

    w, h = orig_w, orig_h
    if size_lower == "x2":
        w, h = w * 2, h * 2
    elif size_lower == "x3":
        w, h = w * 3, h * 3
    elif size_lower == "x4":
        w, h = w * 4, h * 4
    elif size_lower == "x5":
        w, h = w * 5, h * 5
    elif size_lower.startswith("custom:"):
        try:
            max_edge = int(size_lower.split(":")[1]) if ":" in size_lower else 2048
        except (ValueError, IndexError):
            max_edge = 2048
        scale = max_edge / max(w, h)
        w, h = int(w * scale), int(h * scale)
    # 对齐到 16 的倍数
    w = max(64, ((w + 8) // 16) * 16)
    h = max(64, ((h + 8) // 16) * 16)
    # 检查最低要求：最长边 ≥ 1024
    if max(w, h) < 1024:
        need = int(1024 / max(orig_w, orig_h)) + 1
        raise RuntimeError(
            f"尺寸 {w}x{h} 不满足最低要求（最长边需 ≥ 1024）。"
            f"原图 {orig_w}x{orig_h}，最小需要 x{need} 倍"
        )
    _log.info(f"倍率解析: {size or '跟随'} 原图{orig_w}x{orig_h} → {w}x{h}")
    return f"{w}x{h}"


# ——— 上传安全 ———


async def read_upload_safely(file, max_bytes: int) -> bytes:
    """流式读取上传文件内容，超限立即拒绝（防止 OOM）。

    分块编码（无 Content-Length）时 file.size 为 None，
    直接 await file.read() 会无条件加载全部内容到内存。
    本函数用流式读取，每块累加，超限时抛出 HTTPException(413)。

    Args:
        file: FastAPI UploadFile 对象
        max_bytes: 最大允许字节数

    Returns:
        文件完整内容 bytes

    Raises:
        fastapi.HTTPException: 内容超过 max_bytes 时立即拒绝
    """
    from fastapi import HTTPException
    chunks = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)  # 64KB 块
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大（超过 {max_bytes // 1024 // 1024}MB 上限）"
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ——— 后台任务管理 ———

# 后台任务引用集合（防止 GC 回收导致异常静默丢失）
_bg_tasks: set = set()


def launch_background_task(coro) -> asyncio.Task:
    """创建后台任务并保存引用，任务完成后自动清理。

    用于 generation.py / video.py 等模块的异步长期任务。
    """
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task
