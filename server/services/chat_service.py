"""对话业务逻辑层 —— 对话历史管理 + 元数据索引。

从 routes/chat.py 抽取，路由层只保留 HTTP 参数校验和 SSE 流式传输。
"""

import os
import asyncio
import base64
import uuid
import time
import re
from contextlib import asynccontextmanager
from .. import config
from ..storage.json_store import store
from ..utils import KeyedLockManager

# 对话级写锁，防止并发请求导致读-改-写竞态丢消息
_conv_write_lock = KeyedLockManager()

# 线程索引写锁，保护共享 _index.json 的读-改-写事务（v2.5.51 修复 TOCTOU）
_index_write_lock = asyncio.Lock()

# 对话元数据索引
THREADS_INDEX = os.path.join(config.HISTORY_DIR, "_index.json")


def load_thread_index() -> dict:
    """读取对话元数据索引。"""
    return store.read(THREADS_INDEX, default={"threads": {}})


async def save_thread_index(index: dict):
    """写入索引（使用 JsonStore 统一管理）。"""
    await store.write(THREADS_INDEX, index)


def conv_path(conversation_id: str) -> str:
    """对话 ID → 文件路径。"""
    # UUID 格式 ID (conv_ + hex) 直接使用，避免碰撞
    if conversation_id.startswith("conv_") and re.match(r"^conv_[a-fA-F0-9]+$", conversation_id):
        safe = conversation_id
    else:
        # 非标准 ID：使用 URL-safe base64 编码防碰撞
        safe = "conv_" + base64.urlsafe_b64encode(
            conversation_id.encode("utf-8")
        ).decode("ascii").rstrip("=")
    return os.path.join(config.HISTORY_DIR, f"{safe}.json")


def load_history(conversation_id: str) -> list:
    """加载对话历史消息列表。"""
    data = store.read(conv_path(conversation_id), default={"messages": []})
    return data.get("messages", [])


@asynccontextmanager
async def lock_conversation(conversation_id: str):
    """对话写锁上下文管理器 —— 保护读-改-写全事务。

    用法:
        async with lock_conversation(conv_id):
            messages = load_history(conv_id)
            messages.append(...)
            await save_history(conv_id, messages, title)
    """
    async with await _conv_write_lock.get(conversation_id):
        yield


async def save_history(conversation_id: str, messages: list, title: str = ""):
    """保存对话历史 + 同步更新元数据索引。

    注意：调用方需先通过 lock_conversation 获取写锁以保护完整事务。
    """
    data = {
        "id": conversation_id,
        "title": title or "对话",
        "updated_at": int(time.time() * 1000),
        "messages": messages,
    }
    await store.write_with_timestamp(conv_path(conversation_id), data)

    # v2.5.51：索引更新在锁内保护，防止并发写入丢失
    async with _index_write_lock:
        index = load_thread_index()
        index.setdefault("threads", {})[conversation_id] = {
            "id": conversation_id,
            "title": data["title"],
            "updated_at": data["updated_at"],
            "message_count": len(messages),
        }
        await save_thread_index(index)


def generate_id() -> str:
    """生成对话 ID。"""
    return f"conv_{uuid.uuid4().hex[:12]}"


def auto_title(user_msg: str) -> str:
    """根据用户第一条消息自动生成对话标题。"""
    return (user_msg[:40] + "…") if len(user_msg) > 40 else user_msg


def trim_history(messages: list, max_messages: int) -> list:
    """裁剪对话历史，保留 system prompt 和最近的消息。"""
    if len(messages) <= max_messages + 2:
        return messages
    system_msgs = [m for m in messages if m["role"] == "system"]
    other_msgs = [m for m in messages if m["role"] != "system"]
    return system_msgs + other_msgs[-(max_messages):]


def list_conversations() -> list[dict]:
    """列出所有对话历史（从元数据索引读取，O(1) 避免遍历全部文件）。"""
    os.makedirs(config.HISTORY_DIR, exist_ok=True)
    index = load_thread_index()
    items = list(index.get("threads", {}).values())
    items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return items


async def delete_conversation(thread_id: str):
    """删除对话历史（同时清理元数据索引）。"""
    p = conv_path(thread_id)
    if os.path.exists(p):
        os.remove(p)
    # v2.5.51：索引更新在锁内保护，防止并发删除丢失
    async with _index_write_lock:
        index = load_thread_index()
        index.get("threads", {}).pop(thread_id, None)
        await save_thread_index(index)
