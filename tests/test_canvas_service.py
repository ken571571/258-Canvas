"""画布业务逻辑层单元测试 —— 不经过 HTTP，直接测试 service 函数。"""

import unittest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class CanvasServiceTests(unittest.TestCase):
    """canvas_service 纯单元测试。"""

    @classmethod
    def setUpClass(cls):
        from server.services import canvas_service
        cls.svc = canvas_service

    # ——— _safe_name ———

    def test_safe_name_normal(self):
        result = self.svc._safe_name("我的画布")
        self.assertEqual(result, "我的画布")

    def test_safe_name_special_chars(self):
        result = self.svc._safe_name("test/../evil")
        self.assertNotIn("/", result)
        self.assertNotIn("..", result)

    def test_safe_name_truncation(self):
        result = self.svc._safe_name("A" * 100)
        self.assertLessEqual(len(result), 60)

    def test_safe_name_blank(self):
        result = self.svc._safe_name("")
        self.assertEqual(result, "canvas")

    # ——— _validate_canvas_id ———

    def test_validate_valid_id(self):
        # 不应抛出异常
        self.svc._validate_canvas_id("a1b2c3d4e5f6a7b8")

    def test_validate_invalid_id(self):
        from server.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.svc._validate_canvas_id("../etc/passwd")

    # ——— _resolve_file_source ———

    def test_resolve_output_url(self):
        result = self.svc._resolve_file_source("/output/images/test.png")
        self.assertTrue(result.endswith("test.png"))

    def test_resolve_traversal_blocked(self):
        result = self.svc._resolve_file_source("/output/../../../etc/passwd")
        self.assertEqual(result, "")

    def test_resolve_non_local_url(self):
        result = self.svc._resolve_file_source("https://example.com/img.png")
        self.assertEqual(result, "")

    # ——— create / merge / duplicate ———

    def test_create_returns_valid_structure(self):
        canvas, dir_name = self.svc.create("测试")
        self.assertIn("id", canvas)
        self.assertEqual(canvas["title"], "测试")
        self.assertEqual(canvas["nodes"], [])
        self.assertIn("created_at", canvas)
        self.assertTrue(dir_name)

    def test_merge_from_payload_updates_fields(self):
        existing = {
            "id": "test123456789012",
            "title": "原始",
            "created_at": 1000,
            "updated_at": 1000,
            "nodes": [],
            "connections": [],
            "groups": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "icon": "layers",
            "kind": "default",
            "logs": [],
            "settings": {},
        }
        payload = {
            "title": "新标题",
            "nodes": [{"id": "n1", "type": "image"}],
            "base_updated_at": 1000,
        }
        merged = self.svc.merge_from_payload(existing, payload)
        self.assertEqual(merged["title"], "新标题")
        self.assertEqual(len(merged["nodes"]), 1)
        self.assertGreater(merged["updated_at"], 1000)

    def test_merge_conflict_raises(self):
        from server.exceptions import ConflictError
        existing = {
            "id": "test123456789012",
            "title": "原始",
            "updated_at": 2000,
            "nodes": [], "connections": [], "groups": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
        }
        payload = {"base_updated_at": 1000}  # 过期时间戳
        with self.assertRaises(ConflictError):
            self.svc.merge_from_payload(existing, payload)

    def test_merge_no_lock_when_base_missing(self):
        """base_updated_at 缺失时跳过乐观锁（向后兼容）。"""
        existing = {
            "id": "test123456789012",
            "title": "原始",
            "updated_at": 2000,
            "nodes": [], "connections": [], "groups": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
        }
        payload = {"title": "无锁更新"}  # 无 base_updated_at
        merged = self.svc.merge_from_payload(existing, payload)
        self.assertEqual(merged["title"], "无锁更新")

    def test_duplicate_deep_copies(self):
        existing = {
            "id": "orig12345678901",
            "title": "原始",
            "nodes": [{"id": "n1", "type": "image", "url": "/output/a.png"}],
            "connections": [{"id": "c1", "from": "n1", "to": "n2"}],
            "groups": [{"id": "g1", "childIds": ["n1", "n2"]}],
            "logs": [{"msg": "test"}],
            "settings": {"theme": "dark"},
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "icon": "layers",
            "kind": "default",
        }
        new_canvas, dir_name = self.svc.duplicate(existing)
        # 新画布应不同 ID
        self.assertNotEqual(new_canvas["id"], existing["id"])
        # nodes 应为深拷贝（独立对象）
        self.assertIsNot(new_canvas["nodes"], existing["nodes"])
        new_canvas["nodes"][0]["url"] = "/canvases/new/files/a.png"
        self.assertEqual(existing["nodes"][0]["url"], "/output/a.png",
                         "修改副本不应影响原始画布")
        # connections 应深拷贝
        self.assertIsNot(new_canvas["connections"], existing["connections"])
        # groups 应深拷贝
        self.assertIsNot(new_canvas["groups"], existing["groups"])


if __name__ == "__main__":
    unittest.main()
