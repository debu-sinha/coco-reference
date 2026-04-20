"""Knowledge base retrieval via Databricks Vector Search.

Queries the `coco_knowledge_idx` index created by the setup notebook.
The index is a Delta Sync index over the `knowledge_chunks` Delta table,
embedded with `databricks-bge-large-en` via managed embeddings.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from databricks.vector_search.client import VectorSearchClient

from coco.agent.models import KnowledgeRAGResult
from coco.config import get_config

logger = logging.getLogger(__name__)


def _fully_qualified_index_name(config) -> str:
    """Build `catalog.schema.index` from config, matching the setup notebook."""
    return f"{config.catalog.name}.{config.catalog.schema}.{config.vector_search.index_name}"


async def retrieve_knowledge(
    query: str,
    top_k: int = 5,
    filters: Optional[dict[str, Any]] = None,
) -> KnowledgeRAGResult:
    """Retrieve the top_k most relevant knowledge chunks for `query`.

    Args:
        query: Natural-language query.
        top_k: Number of chunks to return.
        filters: Optional metadata filters in the format the VS client
            expects (dicts are JSON-serialized internally).

    Returns:
        KnowledgeRAGResult with the chunks list populated. On any failure
        (index not yet ready, VS unavailable, etc.) returns an empty
        result and logs the error — the agent treats RAG as best-effort.
    """
    try:
        config = get_config()
        vs_config = config.vector_search

        client = VectorSearchClient(workspace_url=config.workspace.host)

        index = client.get_index(
            endpoint_name=vs_config.endpoint_name,
            index_name=_fully_qualified_index_name(config),
        )

        # Columns we request back. The primary key + text column come from
        # config so they stay in sync with the index definition.
        columns = [vs_config.primary_key, vs_config.text_column]

        response = index.similarity_search(
            columns=columns,
            query_text=query,
            num_results=top_k,
            filters=filters,
            query_type="HYBRID" if vs_config.hybrid else "ANN",
        )

        # VS response shape:
        #   {"manifest": {"columns": [{"name": "chunk_id"}, {"name": "content"}, {"name": "score"}]},
        #    "result":   {"data_array": [[pk_value, text_value, score], ...]}}
        # The score column is auto-appended to the manifest after the
        # requested columns.
        manifest_cols = [c.get("name") for c in response.get("manifest", {}).get("columns", [])]
        rows = response.get("result", {}).get("data_array", [])

        chunks: list[dict[str, Any]] = []
        for row in rows:
            record = {manifest_cols[i]: row[i] for i in range(min(len(manifest_cols), len(row)))}
            chunks.append(
                {
                    "chunk_id": record.get(vs_config.primary_key),
                    "content": record.get(vs_config.text_column),
                    "score": record.get("score", 0.0),
                }
            )

        return KnowledgeRAGResult(
            chunks=chunks,
            total_chunks=len(chunks),
            search_query=query,
        )

    except Exception as e:
        logger.warning("Knowledge retrieval failed (non-fatal): %s", e)
        return KnowledgeRAGResult(
            chunks=[],
            total_chunks=0,
            search_query=query,
        )
