import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class VideoTasksTests(unittest.TestCase):
    """视频任务相关回归测试：Provider 列表、模型参数、任务状态查询。"""

    def test_video_providers_list_ok(self):
        resp = client.get("/api/video/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("providers", data)
        self.assertIsInstance(data["providers"], list)

    def test_video_model_params_ok(self):
        resp = client.get("/api/video/model-params")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("durations", data)
        self.assertIn("resolutions", data)

    def test_video_status_404_for_nonexistent_task(self):
        resp = client.get("/api/video/status/nonexistent_task_99999")
        self.assertEqual(resp.status_code, 404)

    def test_video_generate_sync_rejects_without_valid_provider(self):
        """同步视频生成：无有效 Provider 应返回 400。"""
        resp = client.post("/api/video/generate", json={
            "prompt": "test",
            "provider_id": "nonexistent_platform",
            "model": "",
        })
        self.assertEqual(resp.status_code, 400)

    def test_video_generate_async_creates_task(self):
        """异步视频生成：即使 Provider 不完整，也不应 500 崩溃。"""
        resp = client.post("/api/video/generate/async", json={
            "prompt": "test video",
            "provider_id": "openai",
            "model": "",
        })
        # create_task 总是成功（queued 状态），即使 provider 不可用
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("task_id", data)
        self.assertEqual(data["status"], "queued")

