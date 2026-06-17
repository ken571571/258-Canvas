import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class WorkflowTests(unittest.TestCase):
    """ComfyUI 工作流管理回归测试。"""

    def test_list_workflows_ok(self):
        resp = client.get("/api/comfyui/workflows")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("workflows", data)
        self.assertIsInstance(data["workflows"], list)

    def test_reject_invalid_workflow_name(self):
        """非法工作流名称应被拒绝（路径穿越/名称校验）。"""
        resp = client.get("/api/comfyui/workflows/../evil.json")
        # FastAPI 的 {name:path} 匹配可能导致 404 或 400，都不应 200
        self.assertIn(resp.status_code, (400, 404))
        self.assertNotEqual(resp.status_code, 200)

    def test_reject_path_traversal_in_workflow(self):
        """路径穿越攻击应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/../../API/.env")
        # FastAPI 的 {name:path} 匹配可能导致 404 或 400，都不应 200
        self.assertIn(resp.status_code, (400, 404))
        self.assertNotEqual(resp.status_code, 200)

    def test_create_and_get_custom_workflow(self):
        """创建自定义工作流并读取。"""
        resp = client.post("/api/comfyui/workflows", json={
            "name": "custom/test_regression.json",
            "workflow": {"test": True},
        })
        self.assertIn(resp.status_code, (200, 201))

    def test_builtin_workflow_exists(self):
        """内置工作流 Z-Image.json 应可访问。"""
        resp = client.get("/api/comfyui/workflows/Z-Image.json")
        # 如果有则 200，没有则 404（都不应 500）
        self.assertIn(resp.status_code, (200, 404))

    def test_delete_custom_workflow(self):
        """删除自定义工作流（如果存在）。"""
        # 先创建
        client.post("/api/comfyui/workflows", json={
            "name": "custom/test_to_delete.json",
            "workflow": {"temp": True},
        })
        resp = client.delete("/api/comfyui/workflows/custom/test_to_delete.json")
        self.assertIn(resp.status_code, (200, 404))

    def test_reject_encoded_traversal_in_workflow(self):
        """URL 编码的路径穿越应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/%2e%2e%2fevil.json")
        self.assertIn(resp.status_code, (400, 404))
        self.assertNotEqual(resp.status_code, 200)

    def test_reject_traversal_in_post_name(self):
        """创建工作流时 os.path.basename 会自动剥离目录穿越（安全行为），
        名称 ../evil.json 会被归一化为 custom/evil.json。"""
        resp = client.post("/api/comfyui/workflows", json={
            "name": "../evil.json",
            "workflow": {"hack": True},
        })
        # basename 剥离后 → custom/evil.json，应成功
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "custom/evil.json")

    def test_reject_traversal_with_backslash(self):
        """反斜杠路径穿越应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/..\\evil.json")
        self.assertIn(resp.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
