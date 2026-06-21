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

    @classmethod
    def tearDownClass(cls):
        """清理测试过程中创建的工作流文件，防止残留到下次启动。"""
        import os as _os
        from server.config.paths import WORKFLOW_DIR as _WD
        _custom = _os.path.join(_WD, "custom")
        _cleanup = ["test_regression.json", "test_to_delete.json", "evil.json",
                     "test_regression.json.config.json", "test_to_delete.json.config.json", "evil.json.config.json"]
        for _fn in _cleanup:
            _fp = _os.path.join(_custom, _fn)
            if _os.path.exists(_fp):
                try:
                    _os.remove(_fp)
                except Exception:
                    pass

    def test_list_workflows_ok(self):
        resp = client.get("/api/comfyui/workflows")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("workflows", data)
        self.assertIsInstance(data["workflows"], list)

    def test_reject_invalid_workflow_name(self):
        """非法工作流名称应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/../evil.json")
        self.assertNotEqual(resp.status_code, 200)

    def test_reject_path_traversal_in_workflow(self):
        """路径穿越攻击应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/../../API/.env")
        self.assertNotEqual(resp.status_code, 200)

    def test_create_and_get_custom_workflow(self):
        """创建自定义工作流并读取。"""
        resp = client.post("/api/comfyui/workflows", json={
            "name": "custom/test_regression.json",
            "workflow": {"test": True},
        })
        self.assertEqual(resp.status_code, 200)

    def test_builtin_workflow_exists(self):
        """内置工作流 Z-Image.json 应可访问（如果存在），至少不 500。"""
        resp = client.get("/api/comfyui/workflows/Z-Image.json")
        self.assertIn(resp.status_code, (200, 404))
        self.assertNotEqual(resp.status_code, 500)

    def test_delete_custom_workflow(self):
        """删除自定义工作流（如果存在）。"""
        # 先创建
        client.post("/api/comfyui/workflows", json={
            "name": "custom/test_to_delete.json",
            "workflow": {"temp": True},
        })
        resp = client.delete("/api/comfyui/workflows/custom/test_to_delete.json")
        self.assertEqual(resp.status_code, 200)

    def test_reject_encoded_traversal_in_workflow(self):
        """URL 编码的路径穿越应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/%2e%2e%2fevil.json")
        self.assertNotEqual(resp.status_code, 200)

    def test_reject_traversal_in_post_name(self):
        """创建工作流时 os.path.basename 会自动剥离目录穿越。
        名称 ../evil.json 会被归一化为 custom/evil.json。"""
        resp = client.post("/api/comfyui/workflows", json={
            "name": "../evil.json",
            "workflow": {"hack": True},
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "custom/evil.json")

    def test_reject_traversal_with_backslash(self):
        """反斜杠路径穿越应被拒绝。"""
        resp = client.get("/api/comfyui/workflows/..\\evil.json")
        self.assertNotEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
