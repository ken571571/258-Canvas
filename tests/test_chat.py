import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class ChatTests(unittest.TestCase):
    """LLM 对话端点回归测试：/api/llm 入参校验。

    注意：独立「Chat 对话」页面已移除，流式 /api/llm/stream、画布多模态
    /api/boards/llm、对话历史管理 /api/threads 系列端点均已下线。
    本文件仅保留对仍在使用的 /api/llm（Agent 设计器等内部调用方）的校验测试。

    测试以 RATE_LIMIT_ENABLED=0 运行，429 不会出现，使用精确断言。
    """

    def test_chat_rejects_invalid_provider(self):
        """POST /api/llm 对不存在的 Provider 应返回 400。"""
        resp = client.post("/api/llm", json={
            "message": "你好",
            "provider_id": "nonexistent_platform",
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_rejects_missing_message(self):
        """POST /api/llm 缺少 message 字段时应返回 422（Pydantic 校验）。"""
        resp = client.post("/api/llm", json={
            "provider_id": "openai",
        })
        self.assertEqual(resp.status_code, 422)
