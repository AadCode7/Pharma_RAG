import uuid

from api.services.embedding_service import embed_texts
from config.settings import settings
from config.strategies import require_strategy
from database.client import get_service_client
from exception.exceptions import BadRequestError, NotFoundError
from logger.logger import get_logger
from utils.hashing import sha256_hash
from utils.text import chunk_fixed_size

logger = get_logger(__name__)


async def ingest_document(
    title: str,
    text: str,
    department_ids: list[str],
    existing_document_id: str | None,
    user_id: str,
    chunking_strategy: str = "fixed_size_v1",
    embedding_strategy: str = "bge_small",
) -> dict:
    """Handles both a brand new document and a new version of an existing
    one.

    Ordering is deliberate and fixes a real bug: chunk + embed the new text
    FIRST, before writing anything chunk-related to the DB. Only once
    embedding has actually succeeded do we create the new version's chunks
    and (for an update) deactivate the old version's. Previously, chunks
    were inserted BEFORE calling embed_texts() — if that call then failed
    (a flaky/misconfigured embedding API, exactly what happened here), the
    chunks stayed in the DB with is_active=true but no chunk_embeddings row.
    match_chunks() joins FROM chunk_embeddings, so those chunks silently
    never appeared in retrieval — no error, no trace, nothing. That's what
    happened to the HPLC document.
    """
    # PostgreSQL text columns reject NUL characters, which can appear when a
    # binary file is decoded incorrectly by a client.
    text = text.replace("\x00", "")
    if not text.strip():
        raise BadRequestError("Document text is empty after removing unsupported characters")

    service = get_service_client()
    document_id = existing_document_id
    created_new_document = False

    # Validate early, before doing any expensive/flaky work below.
    if document_id:
        existing = service.table("documents").select("id").eq("id", document_id).single().execute()
        if not existing.data:
            raise NotFoundError("Document not found")
    elif not department_ids:
        raise BadRequestError("At least one departmentId is required for a new document")

    chunk_config = require_strategy("chunking", chunking_strategy)
    embedding_config = require_strategy("embedding", embedding_strategy)

    # The selectors are intentionally introduced before the algorithms.
    # Only the V1 baseline is executable in this milestone; future choices
    # are accepted by the UI but blocked here until their implementation is
    # added. This prevents a selected strategy from silently running a
    # different algorithm than the one the manager chose.
    if not chunk_config["implemented"]:
        raise BadRequestError(
            f"Chunking strategy '{chunk_config['label']}' is not implemented yet. "
            "The strategy selector is ready for its implementation in the next milestone."
        )
    if not embedding_config["implemented"]:
        raise BadRequestError(
            f"Embedding strategy '{embedding_config['label']}' is not implemented yet. "
            "The strategy selector is ready for its implementation in the next milestone."
        )

    chunk_drafts = chunk_fixed_size(text)
    if not chunk_drafts:
        raise BadRequestError("Document produced no chunks — check the extracted text")

    # The expensive, flaky, external part — done before any further DB
    # writes, and BEFORE the old version's chunks (if any) are touched.
    embeddings = await embed_texts(
        [c.content for c in chunk_drafts],
        model_name=embedding_config["model_name"],
    )

    content_hash = sha256_hash(text)
    version_number = 1

    try:
        if document_id:
            last_version = (
                service.table("document_versions")
                .select("version_number")
                .eq("document_id", document_id)
                .order("version_number", desc=True)
                .limit(1)
                .execute()
            )
            version_number = (last_version.data[0]["version_number"] if last_version.data else 0) + 1
        else:
            new_doc = (
                service.table("documents")
                .insert({"title": title, "source_type": "upload", "status": "active", "created_by": user_id})
                .execute()
            )
            document_id = new_doc.data[0]["id"]
            created_new_document = True

            service.table("document_departments").insert(
                [{"document_id": document_id, "department_id": dept_id} for dept_id in department_ids]
            ).execute()

        # NOTE (untested, see progress.md): supabase-py's storage upload signature
        # has shifted across versions — verify this call against your installed
        # `supabase` package version before relying on it.
        storage_path = f"{document_id}/v{version_number}-{uuid.uuid4()}.txt"
        service.storage.from_("documents").upload(
            storage_path, text.encode("utf-8"), {"content-type": "text/plain"}
        )

        new_version = (
            service.table("document_versions")
            .insert(
                {
                    "document_id": document_id,
                    "version_number": version_number,
                    "content_hash": content_hash,
                    "storage_path": storage_path,
                    "chunking_strategy": chunk_config["id"],
                    "embedding_strategy": embedding_config["id"],
                    "embedding_model": embedding_config["model_name"],
                }
            )
            .execute()
        )
        version_id = new_version.data[0]["id"]

        inserted_chunks = (
            service.table("chunks")
            .insert(
                [
                    {
                        "document_version_id": version_id,
                        "chunk_index": c.chunk_index,
                        "content": c.content,
                        "chunk_strategy": c.chunk_strategy,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                    }
                    for c in chunk_drafts
                ]
            )
            .execute()
        )

        embedding_rows = [
            {"chunk_id": chunk["id"], "model_name": settings.embedding_model, "embedding": embedding}
            for chunk, embedding in zip(inserted_chunks.data, embeddings)
        ]
        service.table("chunk_embeddings").insert(embedding_rows).execute()

        # Only now — once the new version is fully chunked AND embedded —
        # flip the pointer and retire the old version's chunks. Up until
        # this line, retrieval has been serving the previous version the
        # entire time, uninterrupted. If this is a version update and
        # anything above failed, the old version is still fully intact and
        # active; nothing was ever taken offline.
        service.table("documents").update({"current_version_id": version_id}).eq("id", document_id).execute()

        if not created_new_document:
            prev_versions = (
                service.table("document_versions")
                .select("id")
                .eq("document_id", document_id)
                .neq("id", version_id)
                .execute()
            )
            prev_ids = [v["id"] for v in (prev_versions.data or [])]
            if prev_ids:
                service.table("chunks").update({"is_active": False}).in_("document_version_id", prev_ids).execute()
                service.table("document_versions").update({"superseded_at": "now()"}).in_(
                    "id", prev_ids
                ).is_("superseded_at", "null").execute()

        return {
            "document_id": document_id,
            "version_id": version_id,
            "version_number": version_number,
            "chunks_created": len(inserted_chunks.data),
            "chunking_strategy": chunk_config["id"],
            "embedding_strategy": embedding_config["id"],
            "embedding_model": embedding_config["model_name"],
        }

    except Exception:
        if created_new_document and document_id:
            # Nothing usable was ever finished — remove the empty shell
            # instead of leaving an invisible, version-less document behind
            # (or, worse, exactly the orphaned-chunks state this fixes).
            try:
                service.table("documents").delete().eq("id", document_id).execute()
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.error(f"Failed to clean up document {document_id} after a failed ingest: {cleanup_exc}")
        raise


async def delete_document(document_id: str) -> None:
    """Hard delete. document_versions, chunks, chunk_embeddings, and
    document_departments all have ON DELETE CASCADE back to documents (see
    database/migrations/0001_initial_schema.sql), so removing the
    documents row alone removes every chunk and every embedding that ever
    belonged to it — no separate cleanup needed on the Postgres side.
    Storage files live in a separate system with no FK relationship to
    Postgres, so those are removed explicitly first.

    This is a deliberate exception to architecture.md's "documents are
    never deleted" principle, which exists for regulatory audit-trail
    reasons — added because it was explicitly requested for admin cleanup.
    Treat it as a break-glass action, not routine workflow, for any
    document that's ever been used to answer a real query in a regulated
    context. If an audit trail needs to survive removal, set
    documents.status = 'archived' instead — archived documents are
    already excluded from retrieval (see match_chunks' `d.status = 'active'`
    filter) without losing history.
    """
    service = get_service_client()

    existing = service.table("documents").select("id").eq("id", document_id).single().execute()
    if not existing.data:
        raise NotFoundError("Document not found")

    versions = service.table("document_versions").select("storage_path").eq("document_id", document_id).execute()
    storage_paths = [v["storage_path"] for v in (versions.data or []) if v.get("storage_path")]
    if storage_paths:
        try:
            service.storage.from_("documents").remove(storage_paths)
        except Exception as exc:  # noqa: BLE001 — don't block the DB delete on a storage cleanup failure
            logger.error(f"Failed to remove storage files for document {document_id}: {exc}")

    service.table("documents").delete().eq("id", document_id).execute()


async def repair_document_embeddings(document_id: str) -> dict:
    """Re-embed active chunks that are missing chunk_embeddings rows.

    This repairs documents that were ingested while the embedding API was
    failing — those chunks exist with is_active=true but never appear in
    match_chunks() because the RPC joins from chunk_embeddings.
    """
    service = get_service_client()

    doc = (
        service.table("documents")
        .select("id, current_version_id")
        .eq("id", document_id)
        .single()
        .execute()
    )
    if not doc.data:
        raise NotFoundError("Document not found")

    version_id = doc.data.get("current_version_id")
    if not version_id:
        raise BadRequestError("Document has no published version to repair")

    chunks = (
        service.table("chunks")
        .select("id, content")
        .eq("document_version_id", version_id)
        .eq("is_active", True)
        .execute()
    )
    if not chunks.data:
        raise BadRequestError("Document has no active chunks")

    chunk_ids = [chunk["id"] for chunk in chunks.data]
    existing = (
        service.table("chunk_embeddings")
        .select("chunk_id")
        .in_("chunk_id", chunk_ids)
        .eq("model_name", settings.embedding_model)
        .execute()
    )
    embedded_ids = {row["chunk_id"] for row in (existing.data or [])}
    missing = [chunk for chunk in chunks.data if chunk["id"] not in embedded_ids]
    if not missing:
        return {"repaired": 0, "chunksTotal": len(chunks.data)}

    embeddings = await embed_texts([chunk["content"] for chunk in missing])
    service.table("chunk_embeddings").insert(
        [
            {"chunk_id": chunk["id"], "model_name": settings.embedding_model, "embedding": embedding}
            for chunk, embedding in zip(missing, embeddings)
        ]
    ).execute()

    return {"repaired": len(missing), "chunksTotal": len(chunks.data)}
