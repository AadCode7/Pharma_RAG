"""Offline unit tests for reranking response parsing and safety defaults."""
import os
import unittest

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("COHERE_API_KEY", "test-cohere-key")

from api.services import reranking_service as reranking
from config.strategies import STRATEGIES


class RerankingServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_json_parser_accepts_fenced_json(self):
        parsed = reranking._json_object('```json\n{"ranked_ids": [{"id": 1, "score": 0.8}]}\n```')
        self.assertEqual(parsed["ranked_ids"][0]["id"], 1)

    def test_removed_cross_encoder_is_not_configured(self):
        self.assertNotIn("cross_encoder", [s["id"] for s in STRATEGIES["reranking"]])

    def test_scores_are_bounded_for_existing_source_ui(self):
        chunk = {"chunk_id": "1", "similarity": 0.2}
        self.assertEqual(reranking._with_score(chunk, 1.4)["similarity"], 1.0)
        self.assertEqual(reranking._with_score(chunk, -0.1)["similarity"], 0.0)
        self.assertEqual(chunk["similarity"], 0.2)

    async def test_empty_candidates_do_not_call_external_provider(self):
        self.assertEqual(
            await reranking.rerank_chunks("question", [], "cohere_rerank", 5),
            [],
        )


if __name__ == "__main__":
    unittest.main()
