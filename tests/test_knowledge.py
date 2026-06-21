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


class KnowledgeTests(unittest.TestCase):
    """知识库 CRUD 和文档操作回归测试。"""

    @classmethod
    def setUpClass(cls):
        """创建一个测试知识库供所有测试使用。"""
        resp = client.post("/api/knowledge-bases", json={
            "name": "回归测试知识库",
            "description": "用于自动化测试",
        })
        if resp.status_code == 200:
            data = resp.json()
            cls.kb_id = data.get("knowledge_base", {}).get("id")
        else:
            cls.kb_id = None

    @classmethod
    def tearDownClass(cls):
        """清理测试知识库。"""
        if cls.kb_id:
            client.delete(f"/api/knowledge-bases/{cls.kb_id}")

    def test_list_knowledge_bases_ok(self):
        resp = client.get("/api/knowledge-bases")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("knowledge_bases", data)

    def test_create_knowledge_base(self):
        resp = client.post("/api/knowledge-bases", json={
            "name": "临时测试知识库",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("knowledge_base", data)
        kb_id = data["knowledge_base"]["id"]

        # 清理
        client.delete(f"/api/knowledge-bases/{kb_id}")

    def test_delete_nonexistent_kb(self):
        resp = client.delete("/api/knowledge-bases/nonexistent_kb_99999")
        self.assertEqual(resp.status_code, 404)

    def test_add_document_to_kb(self):
        if not self.__class__.kb_id:
            self.skipTest("知识库创建失败，跳过文档测试")
        resp = client.post(
            f"/api/knowledge-bases/{self.__class__.kb_id}/documents",
            json={
                "filename": "test_doc.md",
                "content": "# 测试文档\n\n这是回归测试用文档内容。",
            },
        )
        self.assertEqual(resp.status_code, 200)

    def test_list_documents(self):
        if not self.__class__.kb_id:
            self.skipTest("知识库创建失败，跳过文档测试")
        resp = client.get(f"/api/knowledge-bases/{self.__class__.kb_id}/documents")
        self.assertEqual(resp.status_code, 200)

    def test_search_knowledge(self):
        resp = client.post("/api/knowledge-bases/search", json={
            "query": "测试",
            "kb_ids": [],
            "top_k": 3,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)

    def test_upload_rejects_path_traversal_filename(self):
        """上传文件名包含 ../ 应返回 200（os.path.basename 已净化）。"""
        if not self.__class__.kb_id:
            self.skipTest("知识库创建失败，跳过")
        resp = client.post(
            f"/api/knowledge-bases/{self.__class__.kb_id}/documents/upload",
            files={"file": ("../../../etc/passwd.txt", io.BytesIO(b"malicious content"), "text/plain")},
        )
        # basename 净化后文件名变为 passwd.txt，上传应成功
        self.assertEqual(resp.status_code, 200)
        # 验证返回的 filename 已净化
        data = resp.json()
        self.assertIn("document", data)
        self.assertEqual(data["document"]["filename"], "passwd.txt")

    def test_search_empty_query_ok(self):
        """空查询应正常返回（不崩溃）。"""
        resp = client.post("/api/knowledge-bases/search", json={
            "query": "",
            "kb_ids": [],
            "top_k": 5,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.json())


if __name__ == "__main__":
    unittest.main()
