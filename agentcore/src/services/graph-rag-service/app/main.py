import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.graph_rag import router as graph_rag_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    logger.info("Graph RAG Service starting on %s:%s", settings.host, settings.port)

    if settings.database_url:
        from app.database import init_db

        await init_db(settings.database_url)
        logger.info("Database connected")

    # Pre-warm Neo4j driver singleton if URI is configured
    if settings.neo4j_uri:
        try:
            from app.services.neo4j_service import get_driver

            get_driver()
            logger.info("Neo4j driver connected")
        except Exception as e:
            logger.warning("Neo4j driver pre-warm failed (will retry on first request): %s", e)

    yield

    # Shutdown: close Neo4j driver and database engine
    logger.info("Graph RAG Service shutting down")
    try:
        from app.services.neo4j_service import close_driver

        close_driver()
        logger.info("Neo4j driver closed")
    except Exception:
        pass

    try:
        from app.database import _engine

        if _engine is not None:
            await _engine.dispose()
            logger.info("Database engine disposed")
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="Graph RAG Service",
        description="Neo4j Graph RAG microservice for AgentCore",
        version="1.0.0",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    has_wildcard = "*" in origins
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not has_wildcard,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["x-api-key", "content-type", "authorization"],
    )

    application.include_router(graph_rag_router)

    @application.get("/health")
    async def health():
        from app.services.neo4j_service import _driver

        neo4j_ok = _driver is not None or not settings.neo4j_uri
        return {
            "status": "healthy" if neo4j_ok else "degraded",
            "service": "graph-rag-service",
        }

    return application


app = create_app()


def run():
    settings = get_settings()
    is_dev = os.getenv("ENV", "development").lower() in ("development", "dev", "local")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=is_dev,
    )


if __name__ == "__main__":
    run()
