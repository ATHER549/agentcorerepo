import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.pinecone import router as pinecone_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    logger.info("Pinecone Service starting on %s:%s", settings.host, settings.port)

    if settings.database_url:
        from app.database import init_db

        await init_db(settings.database_url)
        logger.info("Database connected")

    yield

    # Shutdown: close database engine if initialised
    logger.info("Pinecone Service shutting down")
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
        title="Pinecone Service",
        description="Pinecone Vector Store microservice for AgentCore",
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

    application.include_router(pinecone_router)

    @application.get("/health")
    async def health():
        from app.services.pinecone_service import _pinecone_client

        pc_ok = _pinecone_client is not None or not settings.pinecone_api_key
        return {
            "status": "healthy" if pc_ok else "degraded",
            "service": "pinecone-service",
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
