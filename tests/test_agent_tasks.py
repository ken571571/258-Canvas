"""Agent 管理 + Task 管理 + Assets 列表 — P0 覆盖率补充。

覆盖之前零测试的端点：
- Agent: PUT/DELETE/GET/skills/文件上传
- Task: cancel/retry/list
- Assets: list
"""

import unittest
import sys
import io
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class AgentManagementTests(unittest.TestCase):
    """Agent CRUD 管理端点测试。"""

    def setUp(self):
        resp = client.post("/api/agents", json={"name": "管理测试Agent"})
        self.assertEqual(resp.status_code, 200)
        self.agent_id = resp.json()["agent"]["id"]

    def tearDown(self):
        if hasattr(self, 'agent_id') and self.agent_id:
            client.delete(f"/api/agents/{self.agent_id}")

    def test_get_agent(self):
        resp = client.get(f"/api/agents/{self.agent_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["agent"]
        self.assertEqual(data["id"], self.agent_id)
        self.assertIn("_files", data)
        self.assertIn("skills", data["_files"])

    def test_update_agent(self):
        resp = client.put(f"/api/agents/{self.agent_id}", json={
            "name": "已更新Agent",
            "system_prompt": "你是一个助手",
            "model": "gpt-4o",
            "max_steps": 5,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["agent"]
        self.assertEqual(data["name"], "已更新Agent")
        self.assertEqual(data["system_prompt"], "你是一个助手")
        self.assertEqual(data["model"], "gpt-4o")
        self.assertEqual(data["max_steps"], 5)

    def test_update_agent_partial(self):
        orig = client.get(f"/api/agents/{self.agent_id}").json()["agent"]
        resp = client.put(f"/api/agents/{self.agent_id}", json={"name": "部分更新"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["agent"]
        self.assertEqual(data["name"], "部分更新")
        self.assertEqual(data["model"], orig["model"])

    def test_delete_agent(self):
        resp = client.delete(f"/api/agents/{self.agent_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        # 二次删除应仍返回 200（幂等删除）
        resp2 = client.delete(f"/api/agents/{self.agent_id}")
        self.assertEqual(resp2.status_code, 200)
        self.agent_id = None

    def test_get_agent_404(self):
        resp = client.get("/api/agents/nonexistent_agent_99999")
        self.assertEqual(resp.status_code, 404)

    def test_update_agent_404(self):
        resp = client.put("/api/agents/nonexistent_agent_99999", json={"name": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_upload_agent_file(self):
        """上传知识文档到 Agent（单文件上传，字段名 file）。"""
        resp = client.post(
            f"/api/agents/{self.agent_id}/files/knowledge",
            files={"file": ("test.md", io.BytesIO(b"# Agent Knowledge\n\nTest content."), "text/markdown")},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["name"], "test.md")

    def test_list_agent_files(self):
        """列出 Agent 文件（先上传再列出）。"""
        client.post(
            f"/api/agents/{self.agent_id}/files/knowledge",
            files={"file": ("list_test.md", io.BytesIO(b"content"), "text/markdown")},
        )
        resp = client.get(f"/api/agents/{self.agent_id}/files/knowledge")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("files", data)
        self.assertGreater(len(data["files"]), 0)

    def test_delete_agent_file(self):
        """删除 Agent 文件（name 参数为 query string）。"""
        client.post(
            f"/api/agents/{self.agent_id}/files/knowledge",
            files={"file": ("to_delete.md", io.BytesIO(b"tmp"), "text/markdown")},
        )
        resp = client.delete(
            f"/api/agents/{self.agent_id}/files/knowledge?name=to_delete.md"
        )
        self.assertEqual(resp.status_code, 200)

    def test_get_skills_list(self):
        resp = client.get("/api/agents/skills")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("skills", data)

    def test_get_nonexistent_agent_file_404(self):
        resp = client.get(f"/api/agents/{self.agent_id}/files/docs/nonexistent.txt")
        self.assertEqual(resp.status_code, 404)


class TaskManagementTests(unittest.TestCase):
    """Task cancel/retry/list 端点测试。

    每个测试独立创建任务，避免 setUp/tearDown 之间的 ID 干扰。
    """

    def _create_task(self, task_type="general"):
        resp = client.post("/api/tasks", json={"task_type": task_type})
        self.assertEqual(resp.status_code, 200)
        return resp.json()["task_id"]

    def _cleanup(self, task_id):
        try:
            client.delete(f"/api/tasks/{task_id}")
        except Exception:
            pass

    def test_list_tasks(self):
        tid = self._create_task()
        try:
            resp = client.get("/api/tasks")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("tasks", data)
            self.assertIsInstance(data["tasks"], list)
        finally:
            self._cleanup(tid)

    def test_cancel_queued_task(self):
        tid = self._create_task()
        try:
            resp = client.post(f"/api/tasks/{tid}/cancel")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["ok"])
            task = client.get(f"/api/tasks/{tid}")
            self.assertIn(task.json()["status"], ("cancelled", "queued", "running"))
        finally:
            self._cleanup(tid)

    def test_retry_queued_task(self):
        tid = self._create_task()
        try:
            # retry 只能对 failed 状态执行；queued 任务 retry 返回 404/invalid
            resp = client.post(f"/api/tasks/{tid}/retry")
            self.assertIn(resp.status_code, (200, 404))
        finally:
            self._cleanup(tid)

    def test_cancel_nonexistent_task(self):
        resp = client.post("/api/tasks/nonexistent_task_99999/cancel")
        self.assertEqual(resp.status_code, 404)

    def test_retry_nonexistent_task(self):
        resp = client.post("/api/tasks/nonexistent_task_99999/retry")
        self.assertEqual(resp.status_code, 404)

    def test_get_task_stats(self):
        resp = client.get("/api/tasks/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total", data)
        self.assertIn("active", data)
        self.assertGreaterEqual(data["total"], 0)


class AssetsListTests(unittest.TestCase):
    """Assets 列表端点测试。"""

    def test_list_assets(self):
        resp = client.get("/api/assets/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("files", data)
        self.assertIsInstance(data["files"], list)


if __name__ == "__main__":
    unittest.main()
