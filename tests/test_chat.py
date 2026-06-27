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
    """AI 对话相关回归测试：线程管理、LLM 调用参数校验。

    注意：测试以 RATE_LIMIT_ENABLED=0 运行，429 不会出现，使用精确断言。
    """

    def test_list_threads_ok(self):
        """GET /api/threads 应正常返回。"""
        resp = client.get("/api/threads")
        self.assertEqual(resp.status_code, 200)

    def test_get_nonexistent_thread_not_200(self):
        """GET /api/threads/{id} 对不存在的 ID 应返回 404。"""
        resp = client.get("/api/threads/nonexistent_thread_99999")
        self.assertEqual(resp.status_code, 404)

    def test_delete_nonexistent_thread_not_500(self):
        """DELETE /api/threads/{id} 不应返回 500 崩溃。"""
        resp = client.delete("/api/threads/nonexistent_thread_99999")
        self.assertNotEqual(resp.status_code, 500)

    def test_chat_rejects_invalid_provider(self):
        """POST /api/llm 对不存在的 Provider 应返回 400。"""
        resp = client.post("/api/llm", json={
            "message": "你好",
            "provider_id": "nonexistent_platform",
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_stream_rejects_invalid_provider(self):
        """POST /api/llm/stream 对不存在的 Provider 应返回 400。"""
        resp = client.post("/api/llm/stream", json={
            "message": "你好",
            "provider_id": "nonexistent_platform",
        })
        self.assertEqual(resp.status_code, 400)

    def test_boards_llm_rejects_invalid_provider(self):
        """POST /api/boards/llm 对不存在的 Provider 应返回 400。"""
        resp = client.post("/api/boards/llm", json={
            "message": "画布上的提问",
            "provider_id": "nonexistent_platform",
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_rejects_missing_message(self):
        """POST /api/llm 缺少 message 字段时应返回 422（Pydantic 校验）。"""
        resp = client.post("/api/llm", json={
            "provider_id": "openai",
        })
        self.assertEqual(resp.status_code, 422)

