import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.chat import router as chat_router
from app.routers.embeddings import router as embeddings_router
from app.routers.models import router as models_router
from app.routers.registry import router as registry_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    logger.info("Model Service starting on %s:%s", settings.host, settings.port)
    if not settings.key_vault_url:
        msg = (
            "Model Service requires Azure Key Vault. "
            "Set MODEL_SERVICE_KEY_VAULT_URL."
        )
        raise RuntimeError(msg)

    # Import providers to trigger registration
    import app.providers  # noqa: F401

    # Initialise database if configured
    if settings.database_url:
        from app.database import init_db

        await init_db(settings.database_url)
        logger.info("Database connected")

    yield
    logger.info("Model Service shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="Model Service",
        description="OpenAI-compatible Model microservice (LLM & Embeddings) for AgentCore",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    origins = [origin.strip() for origin in settings.cors_origins.split(",")]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    application.include_router(chat_router)
    application.include_router(embeddings_router)
    application.include_router(models_router)
    application.include_router(registry_router)

    @application.get("/health")
    async def health():
        return {"status": "healthy", "service": "model-service", "version": "1.0.0"}

    return application


app = create_app()


def run():
    """Entry point for the model-service script."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
