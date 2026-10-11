# Reranking strategies

Reranking is a second stage after retrieval and before answer generation. The
retriever first finds authorized candidate chunks; the selected reranker changes
their order and returns the best candidates to the existing answer generator.

## Available options

- **No Reranking** (default): keeps the existing retrieval order. It makes no
  reranker API calls and requires no additional configuration.
- **Cross-Encoder**: sends query/passage pairs to the hosted
  `cross-encoder/ms-marco-MiniLM-L-6-v2` model through Hugging Face Inference.
- **Cohere Rerank**: uses Cohere's `/v2/rerank` endpoint and the
  `rerank-v4.0-fast` model.
- **LLM Reranker (Groq)**: asks the configured Groq chat model to rank a bounded
  list of passages and return JSON scores.

Reranking is bounded to the first 20 candidates returned by the retrieval
strategy to keep API cost and latency predictable. The user-facing answer is
still generated from the original question and retrieved document chunks, not
from any generated reranking text.

## Environment variables

Configure these as backend secrets in your deployment environment. Do not
commit real keys to Git.

| Variable | Used by | Required for |
| --- | --- | --- |
| `COHERE_API_KEY` | Existing Cohere embeddings and Cohere Rerank | Cohere operations |
| `HF_API_TOKEN` | Hugging Face hosted Cross-Encoder inference | Cross-Encoder only |
| `GROQ_API_KEY` | Existing answer generation and Groq LLM reranking | LLM Reranker |

Hugging Face inference availability and free-tier quotas can vary by account,
model, and provider. Groq and Cohere rate limits also apply. An error from an
explicitly selected provider is surfaced as an API error; it does not silently
change the ranking algorithm. The default **No Reranking** option remains
independent of these reranker-specific credentials.

## Tests

Run offline unit tests from the repository root:

```bash
python -m unittest discover -s tests
```

These tests cover response parsing and score handling without making paid or
external API calls. Provider integration should also be smoke-tested with
valid backend keys before deploying.
