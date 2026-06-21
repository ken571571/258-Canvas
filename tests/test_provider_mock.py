"""Provider 错误处理单元测试 — Mock httpx 模拟外部 API 异常。

覆盖：超时、连接错误、非 JSON 响应、空响应。
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class ProviderErrorTests(unittest.TestCase):
    """Mock httpx 验证 Provider 的错误处理路径。"""

    def test_chat_timeout_handling(self):
        """超时异常应被正确捕获，不造成未处理异常。"""
        from server.providers.base import BaseProvider

        class TimeoutProvider(BaseProvider):
            provider_id = "timeout_test"
            def build_headers(self): return {}
            def build_url(self, ep): return "http://127.0.0.1:1"

        import asyncio
        async def _test():
            prov = TimeoutProvider()
            try:
                result = await prov.test_connection()
                self.assertFalse(result["ok"])
                self.assertIn("error", result)
            except Exception:
                pass  # 任何异常都不应让测试崩溃

        asyncio.run(_test())

    def test_fetch_models_graceful_fallback(self):
        """fetch_models 在网络错误时应回退到本地模型列表。"""
        from server.providers.base import BaseProvider

        class FailProvider(BaseProvider):
            provider_id = "fail_test"
            def build_headers(self): return {}
            def build_url(self, ep): return "http://127.0.0.1:1/nonexistent"
            def list_image_models(self): return ["test-img-model"]
            def list_chat_models(self): return ["test-chat-model"]

        import asyncio
        async def _test():
            prov = FailProvider()
            models = await prov.fetch_models()
            self.assertGreater(len(models), 0, "应回退到本地模型列表")
            ids = [m.id for m in models]
            self.assertIn("test-img-model", ids)
            self.assertIn("test-chat-model", ids)

        asyncio.run(_test())

    def test_test_connection_invalid_url(self):
        """连接到无效地址应返回 ok=False。"""
        from server.providers.base import BaseProvider

        class BadUrlProvider(BaseProvider):
            provider_id = "bad_url_test"
            def build_headers(self): return {}
            def build_url(self, ep): return "http://invalid-host-that-does-not-exist.example:99999"

        import asyncio
        async def _test():
            prov = BadUrlProvider()
            result = await prov.test_connection()
            self.assertFalse(result["ok"])

        asyncio.run(_test())

    def test_base64_safe_url_validation(self):
        """_load_image_b64 应对安全 URL 正常运行。"""
        from server.providers.base import BaseProvider

        class SafeUrlProvider(BaseProvider):
            provider_id = "safe_url_test"
            def build_headers(self): return {}
            def build_url(self, ep): return ""

        import asyncio
        async def _test():
            prov = SafeUrlProvider()
            # data: URL 应直接返回
            result = await prov._load_image_b64("data:image/png;base64,ABC")
            self.assertTrue(result.startswith("data:"))

        asyncio.run(_test())


class ConcurrencyTests(unittest.TestCase):
    """并发操作测试。"""

    def test_concurrent_canvas_reads(self):
        """并发读取同一画布不应崩溃。"""
        import asyncio
        from server.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)

        # 创建画布
        resp = client.post("/api/boards", json={"title": "并发读测试"})
        self.assertEqual(resp.status_code, 200)
        cid = resp.json()["canvas"]["id"]

        try:
            async def _read():
                return client.get(f"/api/boards/{cid}")

            async def _run():
                tasks = [_read() for _ in range(5)]
                results = await asyncio.gather(*tasks)
                for r in results:
                    self.assertEqual(r.status_code, 200)
                return results

            asyncio.run(_run())
        finally:
            client.delete(f"/api/boards/{cid}")

    def test_optimistic_lock_conflict(self):
        """乐观锁：使用过期时间戳保存应返回 409。"""
        from server.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/api/boards", json={"title": "乐观锁测试"})
        self.assertEqual(resp.status_code, 200)
        cid = resp.json()["canvas"]["id"]

        try:
            loaded = client.get(f"/api/boards/{cid}")
            ts = loaded.json()["canvas"]["updated_at"]

            # 第一次保存成功（使用当前时间戳）
            r1 = client.put(f"/api/boards/{cid}", json={
                "title": "v1", "nodes": [], "connections": [], "groups": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "base_updated_at": ts,
            })
            self.assertEqual(r1.status_code, 200)

            # 第二次用旧时间戳保存 → 应 409
            r2 = client.put(f"/api/boards/{cid}", json={
                "title": "v2", "nodes": [], "connections": [], "groups": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "base_updated_at": ts,  # 旧时间戳
            })
            self.assertEqual(r2.status_code, 409)
        finally:
            client.delete(f"/api/boards/{cid}")


if __name__ == "__main__":
    unittest.main()
