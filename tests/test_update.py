import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class UpdateTests(unittest.TestCase):
    """更新系统相关回归测试：版本信息、安全校验。

    注意：测试以 RATE_LIMIT_ENABLED=0 运行，429 不会出现，使用精确断言。
    """

    def test_app_info_returns_version(self):
        """GET /api/app-info 应返回 version 字段。"""
        resp = client.get("/api/app-info")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("version", data)
        self.assertIsInstance(data["version"], str)
        self.assertTrue(len(data["version"]) > 0)

    def test_check_update_ok(self):
        """GET /api/check-update 应正常返回。"""
        resp = client.get("/api/check-update")
        self.assertEqual(resp.status_code, 200)

    def test_list_backups_ok(self):
        """GET /api/update/backups 应正常返回。"""
        resp = client.get("/api/update/backups")
        self.assertEqual(resp.status_code, 200)

    def test_update_requires_confirm(self):
        """POST /api/update 不带 confirm=true 应被拒绝。"""
        resp = client.post("/api/update", json={})
        self.assertEqual(resp.status_code, 400)

    def test_update_confirm_false_rejected(self):
        """POST /api/update confirm=false 应被拒绝。"""
        resp = client.post("/api/update", json={"confirm": False})
        self.assertEqual(resp.status_code, 400)

    def test_update_without_repo_url_rejected(self):
        """POST /api/update confirm=true 无 GITHUB_REPO 时应被拒绝。"""
        resp = client.post("/api/update", json={"confirm": True})
        self.assertEqual(resp.status_code, 400)

    def test_rollback_empty_backup_id_rejected(self):
        """POST /api/update/rollback 空 backup_id 应被拒绝。"""
        resp = client.post("/api/update/rollback?backup_id=")
        self.assertEqual(resp.status_code, 400)

    def test_rollback_bad_format_rejected(self):
        """POST /api/update/rollback 非法格式 backup_id 应返回 400。"""
        resp = client.post("/api/update/rollback?backup_id=../../../etc")
        self.assertEqual(resp.status_code, 400)

    def test_rollback_valid_format_nonexistent_returns_404(self):
        """POST /api/update/rollback 格式合法但不存在的 backup_id 应返回 404。"""
        resp = client.post("/api/update/rollback?backup_id=20990101-000000")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
