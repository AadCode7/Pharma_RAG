# Reranking strategies

Reranking is a second stage after retrieval and before answer generation. The
retriever first finds authorized candidate chunks; the selected reranker changes
their order and returns the best candidates to the existing answer generator.

## Available options

- **No Reranking** (default): keeps the existing retrieval order. It makes no
  reranker API calls and requires no additional configuration.
- **Cohere Rerank**: uses Cohere's `/v2/rerank` endpoint and the
  `rerank-v4.0-fast` model. Cohere trial API keys are free but rate-limited and
  intended for evaluation, not production or commercial use.
- **LLM Reranker (Groq)**: asks the configured Groq chat model to rank a bounded
  list of passages and return JSON scores.

Reranking is bounded to the first 20 candidates returned by the retrieval
strategy to keep API usage and latency predictable. Cohere and Groq each receive
a single request containing the candidate passages. The user-facing answer is still
generated from the original question and retrieved document chunks, not from
any generated reranking text.

**Data handling:** when one of these hosted rerankers is selected, the query and
retrieved passage text are sent to that provider. Confirm that this is allowed
by your organization's pharmaceutical-data and vendor policies before enabling
a hosted reranker for confidential documents.

## Environment variables

Configure these as backend secrets in your deployment environment. Do not
commit real keys to Git.

| Variable | Used by | Required for |
| --- | --- | --- |
| `COHERE_API_KEY` | Existing Cohere embeddings and Cohere Rerank | Cohere operations |
| `GROQ_API_KEY` | Existing answer generation and Groq LLM reranking | LLM Reranker |

Cohere trial keys have endpoint-specific rate limits and are not intended for
production/commercial use; Groq free-tier limits also apply. An error from an
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
