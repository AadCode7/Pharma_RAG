import unittest

from api.services.evaluation_service import evaluate_trace, summarize_results


class EvaluationServiceTests(unittest.TestCase):
    def setUp(self):
        self.trace = {
            "id": "trace-1",
            "request_id": "request-1",
            "query_text": "What is the dose?",
            "stage": {
                "retrieval_strategy": "hybrid",
                "reranking_strategy": "none",
                "retrieved_chunks": [
                    {"document_id": "doc-a", "content": "The recommended dose is 5 mg."},
                    {"document_id": "doc-b", "content": "Take with water."},
                ],
                "grounded_answer": "The recommended dose is 5 mg.",
            },
            "latency_breakdown": {"total_ms": 125},
        }

    def test_retrieval_metrics_use_relevant_document_ids(self):
        result = evaluate_trace(
            self.trace,
            {"trace_id": "trace-1", "relevant_document_ids": ["doc-b", "doc-c"]},
            2,
        )
        self.assertEqual(result["recall_at_k"], 0.5)
        self.assertEqual(result["precision_at_k"], 0.5)
        self.assertEqual(result["mrr_at_k"], 0.5)

    def test_reference_metrics_are_optional_and_deterministic(self):
        result = evaluate_trace(
            self.trace,
            {
                "trace_id": "trace-1",
                "reference_answer": "The recommended dose is 5 mg.",
                "relevant_document_ids": [],
            },
            5,
        )
        self.assertEqual(result["answer_token_f1"], 1.0)
        self.assertEqual(result["answer_rouge_l"], 1.0)
        self.assertIsNotNone(result["context_token_recall"])
        self.assertIsNone(result["recall_at_k"])

    def test_summary_reports_metric_coverage(self):
        results = [
            {"recall_at_k": 1.0, "precision_at_k": 1.0, "mrr_at_k": 1.0,
             "context_token_recall": None, "answer_token_f1": None,
             "answer_rouge_l": None, "latency_ms": 100,
             "reference_answer_provided": False, "expected_document_ids": ["doc-a"]},
            {"recall_at_k": None, "precision_at_k": None, "mrr_at_k": None,
             "context_token_recall": 0.5, "answer_token_f1": 0.5,
             "answer_rouge_l": 0.4, "latency_ms": 300,
             "reference_answer_provided": True, "expected_document_ids": []},
        ]
        summary = summarize_results(results)
        self.assertEqual(summary["evaluated_queries"], 2)
        self.assertEqual(summary["recall_at_k"], 1.0)
        self.assertEqual(summary["recall_at_k_coverage"], 1)
        self.assertEqual(summary["latency_ms"], 200)


if __name__ == "__main__":
    unittest.main()
