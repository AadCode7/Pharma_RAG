"""Unit tests for retrieval ranking algorithms; run with python -m unittest discover -s tests."""
import os
import unittest
from unittest.mock import patch

# Settings are loaded at import time; supply harmless test-only values before
# importing the service module. No network calls are made by these tests.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("COHERE_API_KEY", "test-cohere-key")

from api.services import retrieval_service as retrieval


CORPUS = [
    {
        "chunk_id": "1",
        "document_id": "doc-a",
        "document_title": "Adverse Events",
        "content": "Adverse events should be reported within twenty four hours.",
    },
    {
        "chunk_id": "2",
        "document_id": "doc-b",
        "document_title": "Drug Storage",
        "content": "Store the medicine between two and eight degrees Celsius.",
    },
    {
        "chunk_id": "3",
        "document_id": "doc-c",
        "document_title": "Safety Reporting",
        "content": "Report serious adverse events to the safety department.",
    },
]


class RetrievalAlgorithmTests(unittest.TestCase):
    @patch.object(retrieval, "visible_chunks", return_value=CORPUS)
    def test_bm25_ranks_term_matches_and_returns_normalized_scores(self, _visible):
        result = retrieval.bm25_chunks("adverse events report", "user-1", 3)
        self.assertTrue(result)
        self.assertEqual(result[0]["chunk_id"], "3")
        self.assertTrue(all(0.0 <= row["similarity"] <= 1.0 for row in result))

    @patch.object(retrieval, "visible_chunks", return_value=CORPUS)
    def test_tfidf_returns_only_matching_documents(self, _visible):
        result = retrieval.tfidf_chunks("medicine storage", "user-1", 3)
        self.assertEqual([row["chunk_id"] for row in result], ["2"])
        self.assertGreater(result[0]["similarity"], 0.0)
        self.assertLessEqual(result[0]["similarity"], 1.0)

    @patch.object(retrieval, "bm25_chunks")
    @patch.object(retrieval, "match_chunks")
    def test_hybrid_fuses_dense_and_lexical_results(self, dense_mock, bm25_mock):
        dense_mock.return_value = [dict(CORPUS[0], similarity=0.9), dict(CORPUS[1], similarity=0.8)]
        bm25_mock.return_value = [dict(CORPUS[1], similarity=1.0), dict(CORPUS[2], similarity=0.5)]
        result = retrieval.hybrid_chunks("adverse events", [0.1, 0.2], "user-1", 3, 3)
        self.assertEqual(result[0]["chunk_id"], "2")
        self.assertEqual(len({row["chunk_id"] for row in result}), len(result))
        self.assertTrue(all(0.0 <= row["similarity"] <= 1.0 for row in result))

    @patch.object(retrieval, "match_chunks")
    def test_mmr_returns_at_most_k_distinct_candidates(self, dense_mock):
        dense_mock.return_value = [
            dict(CORPUS[0], similarity=0.95),
            dict(CORPUS[2], similarity=0.90),
            dict(CORPUS[1], similarity=0.75),
        ]
        result = retrieval.mmr_chunks([0.1, 0.2], "user-1", 2, 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(len({row["chunk_id"] for row in result}), 2)
        self.assertTrue(all(0.0 <= row["similarity"] <= 1.0 for row in result))

    def test_empty_lexical_query_returns_no_results(self):
        self.assertEqual(retrieval.bm25_chunks("!!!", "user-1", 5), [])
        self.assertEqual(retrieval.tfidf_chunks("!!!", "user-1", 5), [])


if __name__ == "__main__":
    unittest.main()
