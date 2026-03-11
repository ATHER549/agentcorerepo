"""Graph RAG endpoints — Neo4j entity/search/community operations."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key
from app.schemas import (
    CommunityDetectRequest,
    CommunityDetectResponse,
    EmbedEntitiesRequest,
    EmbedEntitiesResponse,
    EnsureVectorIndexRequest,
    EnsureVectorIndexResponse,
    FetchUnembeddedRequest,
    FetchUnembeddedResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    StatsRequest,
    StatsResponse,
    StoreCommunityRequest,
    StoreCommunityResponse,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.services.neo4j_service import (
    detect_communities,
    ensure_vector_index,
    fetch_unembedded,
    get_stats,
    ingest_entities,
    search_graph,
    store_communities,
    store_embeddings,
    test_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/graph", tags=["Graph RAG"], dependencies=[Depends(verify_api_key)])


async def _run_sync(func, *args):
    """Run a blocking function in the default executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))


@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(req: IngestRequest):
    try:
        return await _run_sync(ingest_entities, req)
    except ValueError as e:
        logger.error("ingest failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ingest failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during entity ingestion")


@router.post("/fetch-unembedded", response_model=FetchUnembeddedResponse)
async def fetch_unembedded_endpoint(req: FetchUnembeddedRequest):
    try:
        return await _run_sync(fetch_unembedded, req)
    except Exception as e:
        logger.error("fetch_unembedded failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching unembedded entities")


@router.post("/store-embeddings", response_model=EmbedEntitiesResponse)
async def store_embeddings_endpoint(req: EmbedEntitiesRequest):
    try:
        return await _run_sync(store_embeddings, req)
    except Exception as e:
        logger.error("store_embeddings failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error storing embeddings")


@router.post("/ensure-vector-index", response_model=EnsureVectorIndexResponse)
async def ensure_vector_index_endpoint(req: EnsureVectorIndexRequest):
    try:
        return await _run_sync(ensure_vector_index, req)
    except Exception as e:
        logger.error("ensure_vector_index failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error ensuring vector index")


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest):
    try:
        return await _run_sync(search_graph, req)
    except ValueError as e:
        logger.error("search failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during graph search")


@router.post("/stats", response_model=StatsResponse)
async def stats_endpoint(req: StatsRequest):
    try:
        return await _run_sync(get_stats, req)
    except Exception as e:
        logger.error("stats failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching stats")


@router.post("/communities/detect", response_model=CommunityDetectResponse)
async def detect_communities_endpoint(req: CommunityDetectRequest):
    try:
        return await _run_sync(detect_communities, req)
    except Exception as e:
        logger.error("detect_communities failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during community detection")


@router.post("/communities/store", response_model=StoreCommunityResponse)
async def store_communities_endpoint(req: StoreCommunityRequest):
    try:
        return await _run_sync(store_communities, req)
    except Exception as e:
        logger.error("store_communities failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error storing communities")


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection_endpoint(req: TestConnectionRequest):
    return await _run_sync(test_connection, req)
