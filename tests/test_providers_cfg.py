import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app, raise_server_exceptions=False)


class ProvidersCfgTests(unittest.TestCase):
    """Provider 配置相关回归测试：API Key 保存/脱敏/热刷新。"""

    def test_get_api_keys_returns_ok(self):
        resp = client.get("/api/settings/api-keys")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("keys", data)

    def test_save_and_masked_display(self):
        # 保存一个测试 Key（使用白名单内的键名前缀）
        resp = client.post("/api/settings/api-keys", json={
            "API_PROVIDER_TEST_KEY": "sk-this-is-a-secret-key-1234",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        # 读取时应该被脱敏
        resp = client.get("/api/settings/api-keys")
        self.assertEqual(resp.status_code, 200)
        keys = resp.json()["keys"]
        self.assertIn("API_PROVIDER_TEST_KEY", keys)
        # 敏感 Key 应显示为 **** 开头
        displayed = keys["API_PROVIDER_TEST_KEY"]
        self.assertTrue(displayed.startswith("****"), f"Key 未脱敏: {displayed}")

        # 清理
        client.post("/api/settings/api-keys", json={
            "API_PROVIDER_TEST_KEY": "",
        })

    def test_save_rejects_disallowed_key(self):
        """非白名单键名应被拒绝"""
        resp = client.post("/api/settings/api-keys", json={
            "PATH": "/evil/path",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("PATH", resp.json()["detail"])

    def test_provider_list_returns_ok(self):
        resp = client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("providers", data)
        self.assertIsInstance(data["providers"], list)
        # 至少应有 openai provider
        ids = [p["id"] for p in data["providers"]]
        self.assertIn("openai", ids)

    def test_test_connection_requires_valid_provider(self):
        # 无 Key 时请求应该不会崩溃，返回错误信息
        resp = client.post("/api/providers/openai/test-connection", json={})
        # 应该返回 JSON（可能 ok=False，但不应该 500）
        # 无 Key 时返回 200（ok=false），不崩溃
        self.assertEqual(resp.status_code, 200)

    def test_fetch_models_returns_ok(self):
        # 不传 Key 时应回退到本地模型列表（不会 500）
        resp = client.post("/api/providers/openai/fetch-models", json={})
        # 不传 Key 时应回退到本地模型列表（200，非 500）
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("models", data)


if __name__ == "__main__":
    unittest.main()
