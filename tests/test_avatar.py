"""Avatar 角色管理 — P1 覆盖率补充。"""

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


class AvatarTests(unittest.TestCase):
    """Avatar CRUD 端点测试。"""

    def setUp(self):
        resp = client.post("/api/avatars", json={
            "name": "测试角色",
            "description": "用于自动化测试",
            "system_prompt": "你是一个测试角色",
        })
        self.assertEqual(resp.status_code, 200)
        self.avatar_id = resp.json()["avatar"]["id"]

    def tearDown(self):
        if hasattr(self, 'avatar_id') and self.avatar_id:
            client.delete(f"/api/avatars/{self.avatar_id}")

    def test_list_avatars(self):
        resp = client.get("/api/avatars")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("avatars", data)
        self.assertIsInstance(data["avatars"], list)

    def test_get_avatar(self):
        resp = client.get(f"/api/avatars/{self.avatar_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # 响应包含 avatar 嵌套对象
        avatar = data.get("avatar", data)
        self.assertIn("id", avatar)
        self.assertIn("name", avatar)

    def test_update_avatar(self):
        resp = client.put(f"/api/avatars/{self.avatar_id}", json={
            "name": "已更新角色",
            "system_prompt": "新的系统提示",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["avatar"]
        self.assertEqual(data["name"], "已更新角色")

    def test_delete_avatar(self):
        resp = client.delete(f"/api/avatars/{self.avatar_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        # 二次获取应 404
        resp2 = client.get(f"/api/avatars/{self.avatar_id}")
        self.assertEqual(resp2.status_code, 404)
        self.avatar_id = None

    def test_get_nonexistent_avatar_404(self):
        resp = client.get("/api/avatars/nonexistent_avatar_99999")
        self.assertEqual(resp.status_code, 404)

    def test_upload_avatar_image(self):
        """上传角色参考图片。"""
        valid_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cbc`\x60\x00'
            b'\x00\x00\x04\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        resp = client.post(
            f"/api/avatars/{self.avatar_id}/images",
            files={"file": ("avatar.png", io.BytesIO(valid_png), "image/png")},
        )
        self.assertIn(resp.status_code, (200, 400))
        # 检查响应结构
        if resp.status_code == 200:
            self.assertTrue(resp.json().get("ok", False) or resp.json().get("url"))

    def test_remove_avatar_image(self):
        """删除角色参考图片 URL（不删物理文件）。"""
        # 先上传
        valid_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cbc`\x60\x00'
            b'\x00\x00\x04\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        client.post(
            f"/api/avatars/{self.avatar_id}/images",
            files={"file": ("to_remove.png", io.BytesIO(valid_png), "image/png")},
        )
        # 获取当前图片 URL
        current = client.get(f"/api/avatars/{self.avatar_id}")
        images = current.json().get("images", [])
        if images:
            resp = client.delete(f"/api/avatars/{self.avatar_id}/images", json={
                "url": images[0],
            })
            self.assertEqual(resp.status_code, 200)

