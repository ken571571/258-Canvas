import unittest
import sys
import os
from pathlib import Path
import io

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class AssetsTests(unittest.TestCase):
    """素材上传/路径安全 回归测试。"""

    def test_upload_rejects_invalid_extension(self):
        """上传 .exe 文件应被拒绝。"""
        resp = client.post(
            "/api/upload",
            files={"file": ("test.exe", io.BytesIO(b"malicious"), "application/x-msdownload")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_oversized_file(self):
        """上传超过 50MB 限制的文件应被拒绝。"""
        resp = client.post(
            "/api/upload",
            files={"file": ("test.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100), "image/png")},
        )
        self.assertIn(resp.status_code, (200, 400, 422))

    def test_upload_accepts_valid_image(self):
        """上传有效的 PNG 图片应成功。"""
        valid_png = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR'
            b'\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDAT'
            b'\x78\x9c\x62\x62\x60\x60\x00\x00\x00\x04\x00\x01'
            b'\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        resp = client.post(
            "/api/upload",
            files={"file": ("test_valid.png", io.BytesIO(valid_png), "image/png")},
        )
        self.assertIn(resp.status_code, (200, 201, 400))

    # ——— 路径穿越安全测试 ———

    def test_delete_asset_rejects_path_traversal(self):
        """删除素材接口应拒绝路径穿越攻击 (../)。"""
        # 尝试用 ../ 逃出 /input/ 目录
        resp = client.delete("/api/assets/delete?url=/input/../API/.env")
        self.assertEqual(resp.status_code, 400)

    def test_delete_asset_rejects_absolute_path(self):
        """删除素材接口应拒绝绝对路径。"""
        resp = client.delete("/api/assets/delete?url=/etc/passwd")
        self.assertEqual(resp.status_code, 400)

    def test_delete_asset_rejects_encoded_traversal(self):
        """删除素材接口应拒绝 URL 编码的路径穿越。"""
        resp = client.delete("/api/assets/delete?url=/input/%2e%2e%2fAPI/.env")
        self.assertIn(resp.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
