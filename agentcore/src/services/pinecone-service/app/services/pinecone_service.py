"""Core Pinecone operations — ingest, search, hybrid, rerank."""

from __future__ import annotations

import hashlib
import logging
import time

from app.config import get_settings
from app.schemas import (
    DocumentItem,
    EnsureIndexRequest,
    EnsureIndexResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    TestConnectionRequest,
    TestConnectionResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached Pinecone client (singleton)
# ---------------------------------------------------------------------------

_pinecone_client = None


def _get_pinecone_client(api_key: str | None = None):
    """Return cached client for default key, or create a new one for custom keys."""
    global _pinecone_client
    from pinecone import Pinecone

    if api_key:
        # Custom key: always create fresh (used by test-connection)
        return Pinecone(api_key=api_key)

    if _pinecone_client is not None:
        return _pinecone_client

    key = get_settings().pinecone_api_key
    if not key:
        raise ValueError(
            "Pinecone API key not configured. "
            "Set PINECONE_API_KEY or PINECONE_SERVICE_PINECONE_API_KEY in .env."
        )
    _pinecone_client = Pinecone(api_key=key)
    logger.info("Pinecone client initialised")
    return _pinecone_client


def _stable_doc_id(namespace: str, index: int, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{namespace or 'ns'}_{index}_{digest}"


# ---------------------------------------------------------------------------
# Ensure index
# ---------------------------------------------------------------------------


def ensure_index(req: EnsureIndexRequest) -> EnsureIndexResponse:
    pc = _get_pinecone_client()
    existing = pc.list_indexes()
    names = [idx.name for idx in existing] if existing else []

    if req.index_name in names:
        return EnsureIndexResponse(exists=True, created=False, index_name=req.index_name)

    from pinecone import ServerlessSpec

    pc.create_index(
        name=req.index_name,
        dimension=req.embedding_dimension,
        metric="dotproduct",
        vector_type="dense",
        spec=ServerlessSpec(cloud=req.cloud_provider, region=req.cloud_region),
    )
    for attempt in range(30):
        try:
            desc = pc.describe_index(req.index_name)
            if desc.status and desc.status.get("ready", False):
                logger.info("Index '%s' ready after %ds", req.index_name, (attempt + 1) * 2)
                break
        except Exception as e:
            logger.debug("Index readiness check attempt %d failed: %s", attempt + 1, e)
        time.sleep(2)

    return EnsureIndexResponse(exists=True, created=True, index_name=req.index_name)


# ---------------------------------------------------------------------------
# Sparse vector generation
# ---------------------------------------------------------------------------


def _generate_sparse_vectors(pc, texts: list[str], sparse_model: str, input_type: str = "passage") -> list[dict]:
    all_sparse = []
    batch_size = get_settings().sparse_batch_size
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = pc.inference.embed(
            model=sparse_model,
            inputs=batch,
            parameters={"input_type": input_type, "truncate": "END"},
        )
        for item in response:
            indices = getattr(item, "sparse_indices", None) or getattr(item, "indices", [])
            values = getattr(item, "sparse_values", None) or getattr(item, "values", [])
            all_sparse.append({"indices": list(indices), "values": list(values)})
    return all_sparse


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def ingest_documents(req: IngestRequest) -> IngestResponse:
    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)
    settings = get_settings()

    texts = [doc.page_content for doc in req.documents]

    # Sparse vectors (optional)
    sparse_vectors = None
    if req.use_hybrid_search:
        try:
            sparse_vectors = _generate_sparse_vectors(pc, texts, req.sparse_model, input_type="passage")
        except Exception as e:
            logger.warning("Sparse embedding failed, ingesting dense-only: %s", e)

    # Build vector records
    vectors = []
    for i, (doc, dense) in enumerate(zip(req.documents, req.embedding_vectors)):
        metadata = dict(doc.metadata) if doc.metadata else {}
        metadata[req.text_key] = doc.page_content[:40000]
        vec_id = _stable_doc_id(req.namespace, i, doc.page_content)

        vec_data: dict = {"id": vec_id, "values": dense, "metadata": metadata}
        if sparse_vectors and i < len(sparse_vectors):
            vec_data["sparse_values"] = sparse_vectors[i]
        vectors.append(vec_data)

    # Batch upsert
    batch_size = settings.ingest_batch_size
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=req.namespace or "")

    return IngestResponse(
        vectors_upserted=len(vectors),
        index_name=req.index_name,
        namespace=req.namespace,
    )


# ---------------------------------------------------------------------------
# Hybrid score normalization
# ---------------------------------------------------------------------------


def _hybrid_score_norm(dense: list[float], sparse: dict, alpha: float):
    return (
        [v * alpha for v in dense],
        {"indices": sparse["indices"], "values": [v * (1 - alpha) for v in sparse["values"]]},
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_documents(req: SearchRequest) -> SearchResponse:
    pc = _get_pinecone_client()
    index = pc.Index(req.index_name)

    retrieve_k = req.number_of_results
    if req.use_reranking:
        retrieve_k = max(req.number_of_results, 20)

    search_method = "dense"

    if req.use_hybrid_search:
        docs, scores = _hybrid_search(pc, index, req, retrieve_k)
        search_method = f"hybrid (alpha={req.hybrid_alpha})"
    else:
        docs, scores = _dense_search(index, req, retrieve_k)
        search_method = "dense"

    # Reranking
    rerank_info = "disabled"
    if req.use_reranking and docs:
        try:
            docs, scores = _rerank_documents(pc, req.query, docs, req.rerank_model, req.rerank_top_n)
            rerank_info = f"{req.rerank_model} (top {len(docs)})"
        except Exception as e:
            rerank_info = "failed"
            logger.warning("Reranking failed: %s", e)

    # Build results
    results = []
    for rank, (doc, score_info) in enumerate(zip(docs, scores)):
        results.append(SearchResultItem(
            text=doc["text"],
            metadata=doc["metadata"],
            score=score_info.get("score", score_info.get("rerank_score", 0.0)),
            score_info=score_info,
            rank=rank + 1,
        ))

    return SearchResponse(results=results, search_method=search_method, rerank_info=rerank_info)


def _dense_search(index, req: SearchRequest, k: int):
    results = index.query(
        namespace=req.namespace or "",
        top_k=k,
        vector=req.query_embedding,
        include_metadata=True,
    )
    docs = []
    scores = []
    for match in results.get("matches", []):
        metadata = match.get("metadata", {})
        text = metadata.pop(req.text_key, "")
        score = match.get("score", 0.0)
        docs.append({"text": text, "metadata": metadata})
        scores.append({"score": round(score, 4), "type": "dense"})
    return docs, scores


def _hybrid_search(pc, index, req: SearchRequest, k: int):
    sparse_vector = _generate_sparse_vectors(pc, [req.query], req.sparse_model, input_type="query")
    sparse = sparse_vector[0] if sparse_vector else {"indices": [], "values": []}

    alpha = max(0.0, min(req.hybrid_alpha, 1.0))
    hdense, hsparse = _hybrid_score_norm(req.query_embedding, sparse, alpha)

    results = index.query(
        namespace=req.namespace or "",
        top_k=k,
        vector=hdense,
        sparse_vector=hsparse,
        include_metadata=True,
    )

    docs = []
    scores = []
    for match in results.get("matches", []):
        metadata = match.get("metadata", {})
        text = metadata.pop(req.text_key, "")
        score = match.get("score", 0.0)
        docs.append({"text": text, "metadata": metadata})
        scores.append({"score": round(score, 4), "type": "hybrid", "alpha": alpha})
    return docs, scores


def _rerank_documents(pc, query: str, docs: list[dict], rerank_model: str, top_n: int):
    rerank_input = [
        {"id": str(i), "text": doc["text"]}
        for i, doc in enumerate(docs)
    ][:100]

    response = pc.inference.rerank(
        model=rerank_model,
        query=query,
        documents=rerank_input,
        top_n=min(top_n, len(rerank_input)),
        return_documents=True,
        parameters={"truncate": "END"},
    )

    reranked_docs = []
    rerank_scores = []
    for rank, r in enumerate(response.data):
        if r.index < len(docs):
            reranked_docs.append(docs[r.index])
            rerank_scores.append({
                "rerank_score": round(r.score, 4),
                "rerank_position": rank + 1,
                "rerank_model": rerank_model,
                "type": "reranked",
            })
    return reranked_docs, rerank_scores


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


def test_connection(req: TestConnectionRequest) -> TestConnectionResponse:
    try:
        pc = _get_pinecone_client(api_key=req.pinecone_api_key)
        existing = pc.list_indexes()
        names = [idx.name for idx in existing] if existing else []
        return TestConnectionResponse(
            success=True,
            message=f"Connected. {len(names)} index(es) found.",
            indexes=names,
        )
    except Exception as e:
        logger.warning("Pinecone test-connection failed: %s", e)
        return TestConnectionResponse(success=False, message=str(e))
