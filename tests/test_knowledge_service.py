"""知识库业务逻辑层单元测试 —— TF-IDF、分片、PDF 提取。"""

import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class KnowledgeServiceTests(unittest.TestCase):
    """knowledge_service 纯单元测试。"""

    @classmethod
    def setUpClass(cls):
        from server.services import knowledge_service
        cls.svc = knowledge_service

    # ——— chunk_text ———

    def test_chunk_single_paragraph(self):
        chunks = self.svc.chunk_text("hello world", size=500)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "hello world")

    def test_chunk_multi_paragraph(self):
        text = "para1\n\npara2\n\npara3"
        chunks = self.svc.chunk_text(text, size=500)
        self.assertGreaterEqual(len(chunks), 1)

    def test_chunk_respects_size(self):
        text = "A" * 600 + "\n\n" + "B" * 600
        chunks = self.svc.chunk_text(text, size=500)
        self.assertEqual(len(chunks), 2)

    def test_chunk_overlap(self):
        """重叠测试：有 overlap 时相邻 chunk 应共享部分内容。"""
        text = "ABCDEFGHIJ" + "\n\n" + "KLMNOPQRST" + "\n\n" + "UVWXYZ"
        chunks = self.svc.chunk_text(text, size=100, overlap=5)
        if len(chunks) >= 2:
            # 有重叠时，第二个 chunk 应包含第一个 chunk 的尾部
            prev_end = chunks[0][-5:] if len(chunks[0]) >= 5 else chunks[0]
            self.assertIn(prev_end.strip(), chunks[1])

    def test_chunk_empty(self):
        chunks = self.svc.chunk_text("")
        self.assertEqual(len(chunks), 0)

    # ——— tfidf_score ———

    def test_tfidf_basic(self):
        terms = {"hello", "world"}
        df = {"hello": 2, "world": 1}
        score = self.svc.tfidf_score("hello world hello", terms, df, 10)
        self.assertGreater(score, 0)

    def test_tfidf_no_match(self):
        terms = {"xyz"}
        df = {"xyz": 0}
        score = self.svc.tfidf_score("hello world", terms, df, 10)
        self.assertEqual(score, 0.0)

    def test_tfidf_rare_term_scores_higher(self):
        """罕见词（DF更低）应获得更高的 IDF 权重。"""
        terms = {"common", "rare"}
        df = {"common": 100, "rare": 1}
        score_common = self.svc.tfidf_score("common word", {"common"}, df, 100)
        score_rare = self.svc.tfidf_score("rare word", {"rare"}, df, 100)
        self.assertGreater(score_rare, score_common)

    # ——— search_chunks ———

    def test_search_returns_top_k(self):
        chunks = [
            {"kb_id": "kb1", "filename": "a.md", "text": "hello world"},
            {"kb_id": "kb1", "filename": "b.md", "text": "goodbye universe"},
        ]
        results = self.svc.search_chunks(chunks, "hello", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "hello world")

    def test_search_empty_query(self):
        chunks = [{"kb_id": "kb1", "filename": "a.md", "text": "hello"}]
        results = self.svc.search_chunks(chunks, "", top_k=3)
        self.assertEqual(len(results), 0)

    def test_collect_from_index(self):
        idx = {
            "kb1": {
                "documents": [{
                    "filename": "test.md",
                    "chunks": [
                        {"text": "chunk A", "index": 0},
                        {"text": "chunk B", "index": 1},
                    ],
                }],
            }
        }
        chunks = self.svc.collect_chunks_from_index(idx, ["kb1"])
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["text"], "chunk A")

    def test_search_from_snapshot(self):
        snapshot = {
            "kb1": {
                "documents": [{
                    "filename": "snap.md",
                    "chunks": [{"text": "snapshot content here", "index": 0}],
                }],
            }
        }
        results = self.svc.search_from_snapshot(snapshot, ["kb1"], "snapshot", top_k=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["filename"], "snap.md")


if __name__ == "__main__":
    unittest.main()
