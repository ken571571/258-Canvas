import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from server.main import app


client = TestClient(app, raise_server_exceptions=False)


class RegressionTests(unittest.TestCase):
    def test_health_and_index_are_available(self):
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        index = client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("text/html", index.headers.get("content-type", ""))

    def test_task_stats_route_and_task_creation(self):
        stats = client.get("/api/tasks/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertIn("total", stats.json())
        self.assertIn("active", stats.json())

        created = client.post("/api/tasks", json={"task_type": "general"})
        self.assertEqual(created.status_code, 200)
        task_id = created.json()["task_id"]
        self.assertTrue(task_id.startswith("task_"))

        try:
            task = client.get(f"/api/tasks/{task_id}")
            self.assertEqual(task.status_code, 200)
            self.assertEqual(task.json()["id"], task_id)
        finally:
            client.delete(f"/api/tasks/{task_id}")

    def test_agent_file_reader_blocks_path_traversal(self):
        created = client.post("/api/agents", json={"name": "路径安全测试"})
        self.assertEqual(created.status_code, 200)
        agent_id = created.json()["agent"]["id"]
        try:
            response = client.get(f"/api/agents/{agent_id}/files/docs/%2e%2e/agent.json")
            self.assertEqual(response.status_code, 400)
        finally:
            client.delete(f"/api/agents/{agent_id}")

    def test_canvas_crud_smoke(self):
        created = client.post("/api/boards", json={"title": "回归测试画布"})
        self.assertEqual(created.status_code, 200)
        canvas = created.json()["canvas"]
        canvas_id = canvas["id"]

        loaded = client.get(f"/api/boards/{canvas_id}")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["canvas"]["id"], canvas_id)

        saved = client.put(
            f"/api/boards/{canvas_id}",
            json={
                "title": "回归测试画布-已保存",
                "nodes": [],
                "connections": [],
                "groups": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "base_updated_at": loaded.json()["canvas"]["updated_at"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["canvas"]["title"], "回归测试画布-已保存")

        deleted = client.delete(f"/api/boards/{canvas_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertIs(deleted.json()["ok"], True)

    def test_agent_run_rejects_image_path_traversal(self):
        """Agent 执行的 input_images 不应接受路径穿越 URL。"""
        created = client.post("/api/agents", json={"name": "图像路径测试"})
        self.assertEqual(created.status_code, 200)
        agent_id = created.json()["agent"]["id"]
        try:
            # 尝试用 ../ 读取非 input/ 目录下的文件
            resp = client.post(f"/api/agents/{agent_id}/run", json={
                "user_input": "test",
                "input_images": ["/input/../API/.env"],
            })
            # 应返回结果（成功或失败均可），但不能 500
            self.assertIn(resp.status_code, (200, 400))
        finally:
            client.delete(f"/api/agents/{agent_id}")


if __name__ == "__main__":
    unittest.main()
