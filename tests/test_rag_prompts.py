"""Tests for source-grounded GraphRAG prompt assembly."""
import unittest

from prompt_lib.rag_prompts import build_user_prompt


class GraphPromptTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            {
                "chunk_id": "chunk-1",
                "document_title": "Diabetes SOP",
                "content": "Metformin treats Type 2 diabetes.",
            }
        ]
        self.relation = {
            "chunk_id": "chunk-1",
            "subject": "Metformin",
            "predicate": "treats",
            "object": "Type 2 diabetes",
            "document_title": "Diabetes SOP",
            "confidence": 0.9,
        }

    def test_graph_relation_is_linked_to_correct_numbered_source(self):
        prompt = build_user_prompt(
            "What does metformin treat?", self.chunks, [self.relation]
        )
        self.assertIn("[1] (source: Diabetes SOP)\nMetformin treats Type 2 diabetes.", prompt)
        self.assertIn(
            "Metformin --treats--> Type 2 diabetes; supporting source [1]",
            prompt,
        )
        self.assertIn("extraction confidence 90%", prompt)

    def test_graph_relation_is_omitted_when_its_supporting_chunk_is_missing(self):
        unsupported = dict(self.relation, chunk_id="different-chunk")
        prompt = build_user_prompt(
            "What does metformin treat?", self.chunks, [unsupported]
        )
        self.assertNotIn("Graph relationships (retrieval hints", prompt)
        self.assertNotIn("Metformin --treats-->", prompt)

    def test_regular_rag_prompt_works_without_graph_context(self):
        prompt = build_user_prompt("What does metformin treat?", self.chunks)
        self.assertIn("Source context:", prompt)
        self.assertIn("Question: What does metformin treat?", prompt)
        self.assertNotIn("Graph relationships (retrieval hints", prompt)


if __name__ == "__main__":
    unittest.main()
