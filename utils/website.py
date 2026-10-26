"""Chunk-level provenance enrichment for crawled website pages."""
from __future__ import annotations

import re
from api.models.chunk import ChunkDraft

_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")


def _safe_metadata_value(value: str, limit: int) -> str:
    return re.sub(r"[\r\n\t]+", " ", value or "").strip()[:limit]


def enrich_website_chunks(
    chunks: list[ChunkDraft],
    source_text: str,
    source_url: str,
    page_title: str,
) -> list[ChunkDraft]:
    """Add compact URL/title/heading/order context before embedding and storage.

    Character offsets remain relative to the unprefixed Markdown, so any future
    source highlighting still points at the original extracted page text.
    """
    if not chunks:
        return chunks
    title = _safe_metadata_value(page_title, 200)
    url = _safe_metadata_value(source_url, 2048)
    headings = [
        (match.start(), len(match.group(1)), match.group(2).strip())
        for match in _HEADING_RE.finditer(source_text)
    ]

    enriched: list[ChunkDraft] = []
    heading_cursor = 0
    active: list[tuple[int, str]] = []
    for index, chunk in enumerate(chunks, start=1):
        while heading_cursor < len(headings) and headings[heading_cursor][0] <= chunk.char_start:
            _, level, heading = headings[heading_cursor]
            while active and active[-1][0] >= level:
                active.pop()
            active.append((level, heading))
            heading_cursor += 1

        section = " > ".join(item[1] for item in active)
        metadata_lines = [f"Source URL: {url}"]
        if title:
            metadata_lines.append(f"Page title: {title}")
        if section:
            metadata_lines.append(f"Section: {section}")
        metadata_lines.append(f"Page chunk: {index} of {len(chunks)}")
        prefix = "\n".join(metadata_lines) + "\n\n"

        parent_content = chunk.parent_content
        if parent_content is not None:
            parent_prefix = f"Source URL: {url}\n"
            if title:
                parent_prefix += f"Page title: {title}\n"
            if section:
                parent_prefix += f"Section: {section}\n"
            parent_content = parent_prefix + "\n" + parent_content

        enriched.append(
            ChunkDraft(
                chunk_index=chunk.chunk_index,
                content=prefix + chunk.content,
                chunk_strategy=chunk.chunk_strategy,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                parent_content=parent_content,
            )
        )
    return enriched
