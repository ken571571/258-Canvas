"""ComfyUI 局域网扫描接口单元测试（v2.5.62 新增）。

策略：
  - _detect_lan_networks / _probe_port：纯函数/异步直测，只断言类型与
    可达性，不假设 CI 机器一定有局域网（无网时列表为空也合法）。
  - POST /api/comfyui/scan-lan：本机起一个假 ComfyUI HTTP 服务，patch
    _detect_lan_networks 指向 loopback 网段，端到端验证"探活→身份校验
    →解析版本/设备→added 标记"全链路，不依赖真实网络。
"""

import asyncio
import json
import threading
import unittest
import sys
import ipaddress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
import server.config as config_module
from server.main import app
from server.routes.comfyui import _detect_lan_networks, _probe_port

client = TestClient(app, raise_server_exceptions=False)


class _FakeComfyHandler(BaseHTTPRequestHandler):
    """模拟 ComfyUI：/system_stats 返回伪造统计，其余 404。"""

    def do_GET(self):
        if self.path == "/system_stats":
            body = json.dumps({
                "system": {
                    "comfyui_version": "0.34.6",
                    "device": "cuda: NVIDIA RTX 4090",
                }
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


def _start_fake_comfy():
    srv = HTTPServer(("127.0.0.1", 0), _FakeComfyHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


class DetectNetworksTests(unittest.TestCase):
    """网段探测函数契约测试。"""

    def test_return_types_and_ranges(self):
        networks, local_ips = _detect_lan_networks()
        self.assertIsInstance(networks, list)
        self.assertIsInstance(local_ips, set)
        for net in networks:
            self.assertIsInstance(net, ipaddress.IPv4Network)
            self.assertEqual(net.prefixlen, 24)
            self.assertTrue(net.is_private)
        for ip in local_ips:
            addr = ipaddress.ip_address(ip)
            self.assertIsInstance(addr, ipaddress.IPv4Address)
            self.assertTrue(addr.is_private)
            self.assertFalse(addr.is_loopback)
            self.assertFalse(addr.is_link_local)

    def test_probe_closed_port_is_false(self):
        # 端口 1 在 loopback 上几乎必然拒绝（立即返回而非超时）
        result = asyncio.run(_probe_port("127.0.0.1", 1, 0.3))
        self.assertFalse(result)

    def test_probe_open_port_is_true(self):
        srv = _start_fake_comfy()
        try:
            result = asyncio.run(_probe_port("127.0.0.1", srv.server_port, 1.0))
            self.assertTrue(result)
        finally:
            srv.shutdown()


class ScanLanEndpointTests(unittest.TestCase):
    """POST /api/comfyui/scan-lan 端到端（假服务 + patch 网段）。"""

    def test_invalid_port_rejected(self):
        resp = client.post("/api/comfyui/scan-lan", json={"port": 0})
        # pydantic 422 或处理器 400 均可接受（当前实现：处理器 400）
        self.assertIn(resp.status_code, (400, 422))

    def test_scan_finds_and_parses_fake_comfy(self):
        srv = _start_fake_comfy()
        port = srv.server_port
        # loopback /24：未开放地址立即 refused，扫描很快；local_ips 置空，
        # 否则 127.0.0.1 会被当"本机地址"跳过。
        fake_net = ipaddress.IPv4Network("127.0.0.0/24")
        try:
            with mock.patch(
                "server.routes.comfyui._detect_lan_networks",
                return_value=([fake_net], set()),
            ):
                resp = client.post("/api/comfyui/scan-lan", json={"port": port})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["networks"], ["127.0.0.0/24"])
            self.assertEqual(data["hosts_scanned"], 254)
            self.assertEqual(len(data["found"]), 1)
            item = data["found"][0]
            self.assertEqual(item["address"], f"127.0.0.1:{port}")
            self.assertEqual(item["version"], "0.34.6")
            self.assertEqual(item["device"], "cuda: NVIDIA RTX 4090")
            self.assertFalse(item["added"])
        finally:
            srv.shutdown()

    def test_scan_marks_added_instances(self):
        srv = _start_fake_comfy()
        port = srv.server_port
        fake_net = ipaddress.IPv4Network("127.0.0.0/24")
        addr = f"127.0.0.1:{port}"
        try:
            with mock.patch(
                "server.routes.comfyui._detect_lan_networks",
                return_value=([fake_net], set()),
            ), mock.patch.object(
                # 路由内通过 config.COMFYUI_INSTANCES 读取已配置列表
                config_module, "COMFYUI_INSTANCES", [addr]
            ):
                resp = client.post("/api/comfyui/scan-lan", json={"port": port})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(len(resp.json()["found"]), 1)
            self.assertTrue(resp.json()["found"][0]["added"])
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
