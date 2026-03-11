"""Pinecone vector store endpoints."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key
from app.schemas import (
    EnsureIndexRequest,
    EnsureIndexResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.services.pinecone_service import (
    ensure_index,
    ingest_documents,
    search_documents,
    test_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/pinecone", tags=["Pinecone"], dependencies=[Depends(verify_api_key)])


async def _run_sync(func, *args):
    """Run a blocking function in the default executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))


@router.post("/ensure-index", response_model=EnsureIndexResponse)
async def ensure_index_endpoint(req: EnsureIndexRequest):
    try:
        return await _run_sync(ensure_index, req)
    except ValueError as e:
        logger.error("ensure_index failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ensure_index failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during index creation")


@router.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(req: IngestRequest):
    try:
        return await _run_sync(ingest_documents, req)
    except ValueError as e:
        logger.error("ingest failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ingest failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during document ingestion")


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest):
    try:
        return await _run_sync(search_documents, req)
    except ValueError as e:
        logger.error("search failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error during search")


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection_endpoint(req: TestConnectionRequest):
    return await _run_sync(test_connection, req)
