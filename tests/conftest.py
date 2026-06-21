"""共享测试配置 — 被所有测试文件导入。

提供：
- 统一的 sys.path 注入
- 统一的 TestClient 实例
- 常用 fixture 辅助函数
"""

import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 必须在导入 app 前关闭限流，避免测试被 429 污染
os.environ["RATE_LIMIT_ENABLED"] = "0"

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


def create_canvas(title="测试画布"):
    """创建画布并返回 canvas_id，调用方负责清理。"""
    resp = client.post("/api/boards", json={"title": title})
    assert resp.status_code == 200, f"创建画布失败: {resp.status_code}"
    return resp.json()["canvas"]["id"]


def create_agent(name="测试Agent"):
    """创建 Agent 并返回 agent_id，调用方负责清理。"""
    resp = client.post("/api/agents", json={"name": name})
    assert resp.status_code == 200, f"创建Agent失败: {resp.status_code}"
    return resp.json()["agent"]["id"]


def create_kb(name="测试知识库"):
    """创建知识库并返回 kb_id，调用方负责清理。"""
    resp = client.post("/api/knowledge-bases", json={"name": name})
    assert resp.status_code == 200, f"创建知识库失败: {resp.status_code}"
    return resp.json()["knowledge_base"]["id"]


def delete_canvas(cid):
    """安全删除画布（忽略已删除/不存在）。"""
    try:
        client.delete(f"/api/boards/{cid}")
    except Exception:
        pass


def delete_agent(aid):
    """安全删除 Agent。"""
    try:
        client.delete(f"/api/agents/{aid}")
    except Exception:
        pass


def delete_kb(kbid):
    """安全删除知识库。"""
    try:
        client.delete(f"/api/knowledge-bases/{kbid}")
    except Exception:
        pass
