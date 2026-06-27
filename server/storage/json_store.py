"""JSON 文件存储 —— 统一原子写入模式。

项目中有 9+ 个模块各自实现了 JSON 持久化。本模块提供统一接口，
后续新增模块和新功能应优先使用 JsonStore。

现有模块的迁移应逐步进行，不在此阶段强制全量迁移。
"""

import os
import json
import asyncio
import time
import threading


from .. import config

# 内存缓存 TTL（秒）：频繁读取的文件（画布、对话、Agent配置等）缓存
_CACHE_TTL = config.JSON_CACHE_TTL


class JsonStore:
    """统一的 JSON 文件读写器，使用 KeyedLockManager 保护并发写入。

    写入模式: 临时文件 + os.replace() → 原子替换，防止中断导致文件损坏
    读取模式: 同步直接读取，带 TTL 内存缓存减少磁盘 I/O

    用法:
        store = JsonStore()
        data = store.read("/path/to/file.json", default={"items": []})
        await store.write("/path/to/file.json", data)
    """

    def __init__(self):
        from ..utils import KeyedLockManager
        self._locks = KeyedLockManager()
        self._cache = {}  # path → (data, expiry_timestamp)
        self._cache_lock = threading.Lock()  # 保护 _cache 并发读写

    # ——— 读取 ———

    def read(self, path: str, default: dict | list = None) -> dict | list:
        """同步读取 JSON 文件。文件不存在或解析失败时返回 default。

        读取时会检查内存缓存（TTL 30s），缓存命中则跳过磁盘 I/O。
        新增 async 代码请优先使用 async_read() 避免阻塞事件循环。

        双重检查模式：仅持锁读写 _cache dict，磁盘 I/O 在锁外执行。
        避免在 asyncio 事件循环中因持锁做 I/O 导致全局停滞。
        """
        now = time.time()
        # 第一阶段：持锁仅查缓存（O(1) dict 操作，不阻塞事件循环）
        with self._cache_lock:
            cached = self._cache.get(path)
            if cached is not None:
                data, expiry = cached
                if now < expiry:
                    return data

        # 第二阶段：锁外执行磁盘 I/O（不阻塞其他协程/线程）
        try:
            if not os.path.exists(path):
                data = default
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            data = default

        # 第三阶段：持锁写缓存（O(1) dict 操作）
        with self._cache_lock:
            self._cache[path] = (data, now + _CACHE_TTL)
        return data
    async def async_read(self, path: str, default: dict | list = None) -> dict | list:
        """异步读取 JSON 文件（在线程池中执行，不阻塞事件循环）。

        适用于 async 路由处理函数，比 read() 对并发吞吐量更友好。
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.read, path, default)

    # ——— 写入 ———

    async def write(self, path: str, data: dict | list):
        """异步写入 JSON 文件（原子替换）。

        使用 KeyedLockManager 按文件路径分片加锁，
        确保同一文件的并发写入串行化。
        写入后自动失效该路径的内存缓存。
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = await self._locks.get(path)
        async with lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())   # 确保持久化到磁盘后再原子替换
            os.replace(tmp, path)
        # 失效缓存（写入后下次读取必须从磁盘获取最新数据，线程安全）
        with self._cache_lock:
            self._cache.pop(path, None)

    # ——— 带时间戳的写 ———

    async def write_with_timestamp(self, path: str, data: dict, timestamp_key: str = "updated_at"):
        """写入 JSON 并自动更新毫秒时间戳。"""
        data[timestamp_key] = int(time.time() * 1000)
        await self.write(path, data)


# 模块级单例，供各处共享（共享同一个 KeyedLockManager 实例）
store = JsonStore()