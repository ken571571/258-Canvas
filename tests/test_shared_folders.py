import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class SharedFoldersTests(unittest.TestCase):
    """共享文件夹相关回归测试：注册、系统目录拦截、路径穿越防护。

    注意：测试以 RATE_LIMIT_ENABLED=0 运行，429 不会出现，使用精确断言。
    """

    def test_list_folders_ok(self):
        """GET /api/folders 应返回空列表（未注册任何文件夹时）。"""
        resp = client.get("/api/folders")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("folders", data)
        self.assertIsInstance(data["folders"], list)

    def test_register_rejects_system_directory(self):
        """POST /api/folders 注册系统目录应被拒绝。"""
        resp = client.post("/api/folders", json={
            "path": "C:/Windows",
            "name": "非法 Windows 目录",
        })
        self.assertEqual(resp.status_code, 400)

    def test_register_rejects_unix_system_directory(self):
        """POST /api/folders 注册 Unix 系统目录应被拒绝。"""
        resp = client.post("/api/folders", json={
            "path": "/etc",
            "name": "非法 etc 目录",
        })
        self.assertEqual(resp.status_code, 400)

    def test_register_rejects_nonexistent_path(self):
        """POST /api/folders 注册不存在的路径应被拒绝。"""
        resp = client.post("/api/folders", json={
            "path": "Z:/definitely_not_exist_path_12345",
            "name": "不存在的路径",
        })
        self.assertEqual(resp.status_code, 400)

    def test_delete_nonexistent_folder_404(self):
        """DELETE /api/folders/{id} 对不存在的 ID 应返回 404。"""
        resp = client.delete("/api/folders/nonexistent_folder_99999")
        self.assertEqual(resp.status_code, 404)

    def test_get_tree_nonexistent_not_200(self):
        """GET /api/folders/{id}/tree 对不存在的 ID 应返回 404。"""
        resp = client.get("/api/folders/nonexistent_folder_99999/tree")
        self.assertEqual(resp.status_code, 404)

    def test_get_file_nonexistent_not_200(self):
        """GET /api/folders/{id}/file 对不存在的 ID 应返回 404。"""
        resp = client.get("/api/folders/nonexistent_folder_99999/file?path=test.png")
        self.assertEqual(resp.status_code, 404)

    def test_import_nonexistent_folder_not_200(self):
        """POST /api/folders/import 对不存在的 folder_id 应返回 404。"""
        resp = client.post("/api/folders/import", json={
            "folder_id": "nonexistent_folder_99999",
            "paths": ["test.png"],
        })
        self.assertEqual(resp.status_code, 404)

    def test_get_file_rejects_path_traversal(self):
        """GET /api/folders/{id}/file 路径穿越应返回 404。"""
        resp = client.get("/api/folders/nonexistent_folder_99999/file?path=../../../etc/passwd")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
