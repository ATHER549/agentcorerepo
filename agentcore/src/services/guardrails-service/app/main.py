import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.guardrails import router as guardrails_router
from app.routers.registry import router as registry_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    logger.info("Guardrails Service starting on %s:%s", settings.host, settings.port)
    if not settings.key_vault_url:
        msg = "Guardrails Service requires Azure Key Vault. Set GUARDRAILS_SERVICE_KEY_VAULT_URL."
        raise RuntimeError(msg)

    # Initialise database if configured
    if settings.database_url:
        from app.database import init_db

        await init_db(settings.database_url)
        logger.info("Database connected")

    yield
    logger.info("Guardrails Service shutting down")

    # Clear NeMo rails cache and clean up temp directories on shutdown
    from app.services.nemo_service import clear_nemo_guardrails_cache

    count = clear_nemo_guardrails_cache()
    logger.info("NeMo rails cache cleared on shutdown: entries=%d", count)


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="Guardrails Service",
        description="NeMo Guardrails execution microservice for AgentCore",
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

    # Routers — guardrails_router (static paths: /active, /apply, /cache) MUST be
    # registered before registry_router (dynamic path: /{guardrail_id}) so that
    # FastAPI matches /active as a literal string before trying to parse it as a UUID.
    application.include_router(guardrails_router)
    application.include_router(registry_router)

    @application.get("/health")
    async def health():
        return {"status": "healthy", "service": "guardrails-service", "version": "1.0.0"}

    return application


app = create_app()


def run():
    """Entry point for the guardrails-service script."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
