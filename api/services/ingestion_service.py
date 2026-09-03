import uuid

from api.services.embedding_service import embed_texts
from config.settings import settings
from database.client import get_service_client
from exception.exceptions import BadRequestError, NotFoundError
from utils.hashing import sha256_hash
from utils.text import chunk_fixed_size


async def ingest_document(
    title: str,
    text: str,
    department_ids: list[str],
    existing_document_id: str | None,
    user_id: str,
) -> dict:
    """Handles both a brand new document and a new version of an existing
    one. For the new-version path, this is where stale-data safety is
    enforced: the previous version's chunks are deactivated BEFORE the new
    version's chunks are created, so there's never a window where both old
    and new content are simultaneously retrievable."""
    # PostgreSQL text columns reject NUL characters, which can appear when a
    # binary file is decoded incorrectly by a client.
    text = text.replace("\x00", "")
    if not text.strip():
        raise BadRequestError("Document text is empty after removing unsupported characters")

    service = get_service_client()
    content_hash = sha256_hash(text)

    document_id = existing_document_id
    version_number = 1

    if document_id:
        existing = service.table("documents").select("id").eq("id", document_id).single().execute()
        if not existing.data:
            raise NotFoundError("Document not found")

        last_version = (
            service.table("document_versions")
            .select("version_number")
            .eq("document_id", document_id)
            .order("version_number", desc=True)
            .limit(1)
            .execute()
        )
        version_number = (last_version.data[0]["version_number"] if last_version.data else 0) + 1

        prev_versions = service.table("document_versions").select("id").eq("document_id", document_id).execute()
        prev_ids = [v["id"] for v in (prev_versions.data or [])]
        if prev_ids:
            service.table("chunks").update({"is_active": False}).in_("document_version_id", prev_ids).execute()
            service.table("document_versions").update({"superseded_at": "now()"}).in_(
                "id", prev_ids
            ).is_("superseded_at", "null").execute()
    else:
        if not department_ids:
            raise BadRequestError("At least one departmentId is required for a new document")

        new_doc = (
            service.table("documents")
            .insert({"title": title, "source_type": "upload", "status": "active", "created_by": user_id})
            .execute()
        )
        document_id = new_doc.data[0]["id"]

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
            }
        )
        .execute()
    )
    version_id = new_version.data[0]["id"]

    service.table("documents").update({"current_version_id": version_id}).eq("id", document_id).execute()

    # Chunk (V1: fixed-size only)
    chunk_drafts = chunk_fixed_size(text)
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

    texts = [c["content"] for c in inserted_chunks.data]
    embeddings = await embed_texts(texts)

    embedding_rows = [
        {"chunk_id": chunk["id"], "model_name": settings.embedding_model, "embedding": embedding}
        for chunk, embedding in zip(inserted_chunks.data, embeddings)
    ]
    service.table("chunk_embeddings").insert(embedding_rows).execute()

    return {
        "document_id": document_id,
        "version_id": version_id,
        "version_number": version_number,
        "chunks_created": len(inserted_chunks.data),
    }
