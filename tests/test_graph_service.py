"""Offline tests for GraphRAG scoring and hybrid rank fusion."""
import os
import unittest

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("COHERE_API_KEY", "test-cohere-key")

from api.services.graph_service import (
    _rank_graph_edges, _validate_extracted_relationships, fuse_rankings_rrf, normalize_name,
)


class GraphServiceTests(unittest.TestCase):
    def test_entity_normalization_preserves_word_boundaries(self):
        self.assertEqual(normalize_name("  Type-2 Diabetes! "), "type 2 diabetes")

    def test_graph_retrieval_prefers_query_entity_and_neighbour_edges(self):
        edges = [
            {"subject_entity_id":"drug-1","subject_name":"Metformin","subject_type":"drug",
             "predicate":"treats","object_entity_id":"disease-1","object_name":"Type 2 diabetes",
             "object_type":"disease","chunk_id":"chunk-1","document_id":"doc-1",
             "document_title":"Diabetes SOP","content":"Metformin is used to treat Type 2 diabetes.","confidence":0.9},
            {"subject_entity_id":"drug-1","subject_name":"Metformin","subject_type":"drug",
             "predicate":"may cause","object_entity_id":"symptom-1","object_name":"Nausea",
             "object_type":"symptom","chunk_id":"chunk-2","document_id":"doc-1",
             "document_title":"Diabetes SOP","content":"Metformin may cause nausea.","confidence":0.8},
            {"subject_entity_id":"drug-2","subject_name":"Aspirin","subject_type":"drug",
             "predicate":"may cause","object_entity_id":"symptom-2","object_name":"Heartburn",
             "object_type":"symptom","chunk_id":"chunk-3","document_id":"doc-2",
             "document_title":"Medication Guide","content":"Aspirin may cause heartburn.","confidence":0.7},
        ]
        candidates, context, stats = _rank_graph_edges("What does metformin treat?", edges, 10)
        self.assertEqual(candidates[0]["chunk_id"], "chunk-1")
        self.assertEqual(stats["matched_entities"], 1)
        self.assertTrue(any(item["subject"] == "Metformin" for item in context))
        self.assertNotIn("chunk-3", [item["chunk_id"] for item in candidates])

    def test_query_without_graph_overlap_returns_no_candidates(self):
        edges = [{
            "subject_entity_id":"a","subject_name":"Metformin","predicate":"treats",
            "object_entity_id":"b","object_name":"Diabetes","chunk_id":"chunk-1",
            "document_id":"doc-1","document_title":"Medical guide","content":"Metformin treats diabetes.",
        }]
        candidates, context, stats = _rank_graph_edges("quantum satellite telemetry", edges, 10)
        self.assertEqual(candidates, [])
        self.assertEqual(context, [])
        self.assertEqual(stats["matched_relationships"], 0)

    def test_relationship_validation_discards_entities_not_in_cited_chunk(self):
        batch = [{"chunk_ref":0,"chunk_id":"chunk-1","content":"Metformin may cause nausea."}]
        good = {"chunk_ref":0,"subject":"Metformin","subject_type":"drug","predicate":"may cause",
                "object":"nausea","object_type":"symptom","confidence":0.9}
        hallucinated = {"chunk_ref":0,"subject":"Metformin","subject_type":"drug",
                        "predicate":"interacts with","object":"warfarin","object_type":"drug","confidence":0.99}
        valid = _validate_extracted_relationships([good, hallucinated], batch)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["object_norm"], "nausea")

    def test_hybrid_rrf_fuses_graph_and_vector_results(self):
        graph = [{"chunk_id":"shared","document_id":"d1","content":"graph"},
                 {"chunk_id":"graph-only","document_id":"d1","content":"graph"}]
        vector = [{"chunk_id":"shared","document_id":"d1","content":"vector"},
                  {"chunk_id":"vector-only","document_id":"d2","content":"vector"}]
        fused = fuse_rankings_rrf([graph, vector], 5)
        self.assertEqual(fused[0]["chunk_id"], "shared")
        self.assertEqual({row["chunk_id"] for row in fused}, {"shared","graph-only","vector-only"})
        self.assertTrue(all(0.0 <= row["similarity"] <= 1.0 for row in fused))


if __name__ == "__main__":
    unittest.main()
