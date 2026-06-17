"""JSON 文件存储 —— 统一原子写入模式。

项目中有 9+ 个模块各自实现了 JSON 持久化。本模块提供统一接口，
后续新增模块和新功能应优先使用 JsonStore。

现有模块的迁移应逐步进行，不在此阶段强制全量迁移。
"""

import os
import json
import asyncio
import time


class JsonStore:
    """统一的 JSON 文件读写器，使用 KeyedLockManager 保护并发写入。

    写入模式: 临时文件 + os.replace() → 原子替换，防止中断导致文件损坏
    读取模式: 同步直接读取（读操作不需要锁）

    用法:
        store = JsonStore()
        data = store.read("/path/to/file.json", default={"items": []})
        await store.write("/path/to/file.json", data)
    """

    def __init__(self):
        from ..utils import KeyedLockManager
        self._locks = KeyedLockManager()

    # ——— 读取 ———

    def read(self, path: str, default: dict | list = None) -> dict | list:
        """同步读取 JSON 文件。文件不存在或解析失败时返回 default。"""
        if default is None:
            default = {}
        try:
            if not os.path.exists(path):
                return default
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return default

    # ——— 写入 ———

    async def write(self, path: str, data: dict | list):
        """异步写入 JSON 文件（原子替换）。

        使用 KeyedLockManager 按文件路径分片加锁，
        确保同一文件的并发写入串行化。
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = await self._locks.get(path)
        async with lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

    # ——— 带时间戳的写 ———

    async def write_with_timestamp(self, path: str, data: dict, timestamp_key: str = "updated_at"):
        """写入 JSON 并自动更新毫秒时间戳。"""
        data[timestamp_key] = int(time.time() * 1000)
        await self.write(path, data)


# 模块级单例，供各处共享（共享同一个 KeyedLockManager 实例）
store = JsonStore()
