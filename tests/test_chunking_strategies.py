import unittest
from unittest.mock import AsyncMock, patch

from utils.text import (
    chunk_parent_child,
    chunk_recursive_character,
    chunk_section_aware,
    chunk_semantic,
    chunk_sentence_based,
)


class ChunkingStrategyTests(unittest.TestCase):
    def setUp(self):
        self.text = (
            "## Purpose\nThis document explains the purpose. It describes the main goal.\n\n"
            "## Scope\nThis section defines the scope. It lists applicable procedures."
        )

    def test_recursive_chunking_preserves_content(self):
        chunks = chunk_recursive_character(self.text, chunk_size_chars=50, overlap_chars=5)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.chunk_strategy == "recursive" for chunk in chunks))
        self.assertTrue(all(chunk.content for chunk in chunks))

    def test_sentence_chunking_keeps_sentences_together(self):
        chunks = chunk_sentence_based("First sentence. Second sentence! Third sentence?", chunk_size_chars=40, overlap_sentences=0)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(chunk.chunk_strategy == "sentence" for chunk in chunks))
        self.assertTrue(all(chunk.content[-1] in ".!?" for chunk in chunks))

    def test_section_aware_chunking_keeps_headings(self):
        chunks = chunk_section_aware(self.text, chunk_size_chars=100)
        combined = "\n".join(chunk.content for chunk in chunks)
        self.assertIn("Purpose", combined)
        self.assertIn("Scope", combined)
        self.assertTrue(all(chunk.chunk_strategy == "section_aware" for chunk in chunks))

    def test_parent_child_chunks_include_parent_context(self):
        chunks = chunk_parent_child("A" * 1700, parent_size_chars=800, child_size_chars=200, child_overlap_chars=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.parent_content for chunk in chunks))
        self.assertTrue(all(len(chunk.content) <= 200 for chunk in chunks))
        self.assertTrue(all(chunk.chunk_strategy == "parent_child" for chunk in chunks))


class SemanticChunkingTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_chunking_groups_similar_adjacent_sentences(self):
        vector_a = [1.0, 0.0]
        vector_b = [0.99, 0.01]
        vector_c = [0.0, 1.0]
        with patch(
            "api.services.embedding_service.embed_texts",
            new=AsyncMock(return_value=[vector_a, vector_b, vector_c]),
        ):
            chunks = await chunk_semantic(
                "Alpha process starts. Alpha process continues. Completely different topic.",
                model_name="embed-english-light-v3.0",
                similarity_threshold=0.68,
            )
        self.assertEqual(len(chunks), 2)
        self.assertIn("Alpha process starts.", chunks[0].content)
        self.assertIn("Alpha process continues.", chunks[0].content)
        self.assertEqual(chunks[0].chunk_strategy, "semantic")


if __name__ == "__main__":
    unittest.main()
