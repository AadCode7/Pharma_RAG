"""Central registry for selectable RAG strategies and their implementation status."""

STRATEGIES = {
    "chunking": [
        {
            "id": "fixed_size_v1",
            "label": "Fixed Size",
            "description": "512-token chunks with overlap. Current V1 baseline.",
            "implemented": True,
            "default": True,
        },
        {
            "id": "recursive",
            "label": "Recursive Character",
            "description": "Splits at paragraph, line, word, then character boundaries with overlap.",
            "implemented": True,
            "default": False,
        },
        {
            "id": "sentence",
            "label": "Sentence Based",
            "description": "Groups complete sentences into bounded chunks with sentence overlap.",
            "implemented": True,
            "default": False,
        },
        {
            "id": "semantic",
            "label": "Semantic Chunking",
            "description": "Groups adjacent sentences using cosine similarity between Cohere embeddings.",
            "implemented": True,
            "default": False,
        },
        {
            "id": "section_aware",
            "label": "Section Aware",
            "description": "Keeps detected headings attached to their sections and safely splits oversized sections.",
            "implemented": True,
            "default": False,
        },
        {
            "id": "parent_child",
            "label": "Parent / Child",
            "description": "Embeds small child chunks and supplies their larger parent passage as answer context.",
            "implemented": True,
            "default": False,
        },
    ],
    "embedding": [
        {
            "id": "bge_small",
            "label": "Cohere English Light",
            "description": "Cohere embed-english-light-v3.0, 384 dimensions. Current V1 baseline.",
            "implemented": True,
            "default": True,
            "model_name": "embed-english-light-v3.0",
            "dimension": 384,
        },
        {
            "id": "bge_base",
            "label": "BGE Base",
            "description": "BAAI/bge-base-en-v1.5.",
            "implemented": False,
            "default": False,
            "model_name": "BAAI/bge-base-en-v1.5",
            "dimension": 768,
        },
        {
            "id": "e5_base",
            "label": "E5 Base",
            "description": "intfloat/e5-base-v2.",
            "implemented": False,
            "default": False,
            "model_name": "intfloat/e5-base-v2",
            "dimension": 768,
        },
        {
            "id": "openai_small",
            "label": "OpenAI Small",
            "description": "OpenAI text-embedding-3-small.",
            "implemented": False,
            "default": False,
            "model_name": "text-embedding-3-small",
            "dimension": 1536,
        },
    ],
    "retrieval": [
        {
            "id": "standard",
            "label": "Standard Dense Retrieval",
            "description": "Dense vector retrieval against document embeddings. Current V1 baseline.",
            "implemented": True,
            "default": True,
        },
        {
            "id": "bm25",
            "label": "BM25",
            "description": "Lexical retrieval using term-frequency / inverse-document-frequency signals.",
            "implemented": False,
            "default": False,
        },
        {
            "id": "hybrid",
            "label": "Hybrid",
            "description": "Combines dense vector and BM25 retrieval signals.",
            "implemented": False,
            "default": False,
        },
        {
            "id": "hyde",
            "label": "HyDE",
            "description": "Generates a hypothetical answer/document first, then retrieves against it.",
            "implemented": False,
            "default": False,
        },
        {
            "id": "mmr",
            "label": "MMR",
            "description": "Balances relevance with diversity across retrieved chunks.",
            "implemented": False,
            "default": False,
        },
    ],
    "reranking": [
        {
            "id": "none",
            "label": "No Reranking",
            "description": "Use retrieval ranking as-is.",
            "implemented": True,
            "default": True,
        },
        {
            "id": "cross_encoder",
            "label": "Cross-Encoder",
            "description": "Re-score retrieved query/chunk pairs with a cross-encoder.",
            "implemented": False,
            "default": False,
        },
        {
            "id": "llm_reranker",
            "label": "LLM Reranker",
            "description": "Use an LLM to score and reorder the retrieved candidates.",
            "implemented": False,
            "default": False,
        },
    ],
}


def get_strategy(group: str, strategy_id: str) -> dict | None:
    return next((item for item in STRATEGIES.get(group, []) if item["id"] == strategy_id), None)


def require_strategy(group: str, strategy_id: str) -> dict:
    strategy = get_strategy(group, strategy_id)
    if not strategy:
        raise ValueError(f"Unknown {group} strategy: {strategy_id}")
    return strategy
