from fastapi import APIRouter, Request

from exception.exceptions import BadRequestError
from api.services.ingestion_service import ingest_document
from api.services.web_crawler_service import crawl_website
from api.services.rbac_service import require_manager, require_user
from schemas.ingest import IngestRequest

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
async def ingest(payload: IngestRequest, request: Request):
    user_id, _user_client, _token = require_user(request)
    require_manager(user_id)

    title = payload.title.strip()
    text = payload.text
    extraction_source = payload.extraction_source
    source_url = None
    website_truncated = False

    if payload.website_url:
        if text.strip():
            raise BadRequestError("Provide either a website URL or pasted/uploaded text, not both.")
        crawled = await crawl_website(payload.website_url)
        source_url = crawled.url
        website_truncated = crawled.truncated
        extraction_source = "website"
        text = crawled.markdown
        if not title:
            title = crawled.title or source_url
    elif extraction_source == "website":
        raise BadRequestError("A website URL is required for website ingestion.")

    if not title:
        raise BadRequestError("Document title is required.")

    result = await ingest_document(
        title=title,
        text=text,
        department_ids=payload.department_ids,
        existing_document_id=payload.existing_document_id,
        user_id=user_id,
        chunking_strategy=payload.chunking_strategy,
        embedding_strategy=payload.embedding_strategy,
        index_graph=payload.index_graph,
        extraction_source=extraction_source,
        source_url=source_url,
    )

    return {
        "documentId": result["document_id"],
        "versionId": result["version_id"],
        "versionNumber": result["version_number"],
        "chunksCreated": result["chunks_created"],
        "chunkingStrategy": result["chunking_strategy"],
        "embeddingStrategy": result["embedding_strategy"],
        "embeddingModel": result["embedding_model"],
        "graphIndexingStatus": result["graph_indexing_status"],
        "graphEntities": result["graph_entities"],
        "graphRelationships": result["graph_relationships"],
        "graphIndexingError": result.get("graph_indexing_error"),
        "extractionSource": result["extraction_source"],
        "sourceUrl": result.get("source_url"),
        "websiteTruncated": website_truncated,
    }
