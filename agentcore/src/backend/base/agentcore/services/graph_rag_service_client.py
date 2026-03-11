"""HTTP client for the Graph RAG microservice.

Bridges agentcore backend to the standalone RAG microservice by
proxying Neo4j entity ingestion, search, community detection, and stats.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _get_graph_rag_service_settings() -> tuple[str, str]:
    from agentcore.services.deps import get_settings_service

    settings = get_settings_service().settings
    # Prefer unified RAG_SERVICE_URL, fall back to legacy GRAPH_RAG_SERVICE_URL
    url = getattr(settings, "rag_service_url", "") or getattr(settings, "graph_rag_service_url", "")
    api_key = getattr(settings, "rag_service_api_key", "") or getattr(settings, "graph_rag_service_api_key", "")

    if not url:
        msg = "RAG_SERVICE_URL (or GRAPH_RAG_SERVICE_URL) is not configured. Set it in your environment or .env file."
        raise ValueError(msg)

    return url.rstrip("/"), api_key or ""


def _headers(api_key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def _raise_with_detail(resp: httpx.Response) -> None:
    """Raise an error that includes the actual detail message from the microservice."""
    if resp.is_success:
        return
    try:
        body = resp.json()
        detail = body.get("detail", resp.text)
    except Exception:
        detail = resp.text
    raise httpx.HTTPStatusError(
        message=detail,
        request=resp.request,
        response=resp,
    )


def is_service_configured() -> bool:
    try:
        _get_graph_rag_service_settings()
        return True
    except (ValueError, Exception):
        return False


# ---------------------------------------------------------------------------
# Ingest entities
# ---------------------------------------------------------------------------


def ingest_via_service(entities: list[dict], graph_kb_id: str = "default") -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(
            f"{url}/v1/graph/ingest",
            headers=_headers(api_key),
            json={"entities": entities, "graph_kb_id": graph_kb_id},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Fetch unembedded entities
# ---------------------------------------------------------------------------


def fetch_unembedded_via_service(graph_kb_id: str = "default", batch_size: int = 200) -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{url}/v1/graph/fetch-unembedded",
            headers=_headers(api_key),
            json={"graph_kb_id": graph_kb_id, "batch_size": batch_size},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Store embeddings
# ---------------------------------------------------------------------------


def store_embeddings_via_service(
    graph_kb_id: str,
    embeddings: list[dict],
) -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{url}/v1/graph/store-embeddings",
            headers=_headers(api_key),
            json={"graph_kb_id": graph_kb_id, "embeddings": embeddings},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Ensure vector index
# ---------------------------------------------------------------------------


def ensure_vector_index_via_service(graph_kb_id: str = "default") -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{url}/v1/graph/ensure-vector-index",
            headers=_headers(api_key),
            json={"graph_kb_id": graph_kb_id},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_via_service(
    query: str,
    query_embedding: list[float] | None = None,
    graph_kb_id: str = "default",
    search_type: str = "vector_similarity",
    number_of_results: int = 10,
    expansion_hops: int = 2,
    include_source_chunks: bool = True,
) -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{url}/v1/graph/search",
            headers=_headers(api_key),
            json={
                "query": query,
                "query_embedding": query_embedding,
                "graph_kb_id": graph_kb_id,
                "search_type": search_type,
                "number_of_results": number_of_results,
                "expansion_hops": expansion_hops,
                "include_source_chunks": include_source_chunks,
            },
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def get_stats_via_service(graph_kb_id: str = "default") -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{url}/v1/graph/stats",
            headers=_headers(api_key),
            json={"graph_kb_id": graph_kb_id},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------


def detect_communities_via_service(
    graph_kb_id: str = "default",
    max_communities: int = 10,
    min_community_size: int = 2,
) -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{url}/v1/graph/communities/detect",
            headers=_headers(api_key),
            json={
                "graph_kb_id": graph_kb_id,
                "max_communities": max_communities,
                "min_community_size": min_community_size,
            },
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Store community summaries
# ---------------------------------------------------------------------------


def store_communities_via_service(
    graph_kb_id: str,
    communities: list[dict],
) -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{url}/v1/graph/communities/store",
            headers=_headers(api_key),
            json={"graph_kb_id": graph_kb_id, "communities": communities},
        )
        _raise_with_detail(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


def test_connection_via_service(
    neo4j_uri: str | None = None,
    neo4j_username: str | None = None,
    neo4j_password: str | None = None,
    neo4j_database: str | None = None,
) -> dict:
    url, api_key = _get_graph_rag_service_settings()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{url}/v1/graph/test-connection",
            headers=_headers(api_key),
            json={
                "neo4j_uri": neo4j_uri,
                "neo4j_username": neo4j_username,
                "neo4j_password": neo4j_password,
                "neo4j_database": neo4j_database,
            },
        )
        _raise_with_detail(resp)
        return resp.json()
