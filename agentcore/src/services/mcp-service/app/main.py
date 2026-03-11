import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.registry import router as registry_router
from app.routers.tools import router as tools_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger = logging.getLogger(__name__)
    logger.info("MCP Service starting on %s:%s", settings.host, settings.port)
    if not settings.key_vault_url:
        msg = "MCP Service requires Azure Key Vault. Set MCP_SERVICE_KEY_VAULT_URL."
        raise RuntimeError(msg)

    # Initialise database if configured
    if settings.database_url:
        from app.database import init_db

        await init_db(settings.database_url)
        logger.info("Database connected")

    yield

    # Shutdown: clean up all MCP sessions/subprocesses
    logger.info("MCP Service shutting down — cleaning up sessions")
    from app.services.session_service import cleanup_all

    await cleanup_all()
    logger.info("MCP Service shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="MCP Service",
        description="MCP microservice (Model Context Protocol) for AgentCore",
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
    application.include_router(registry_router)
    application.include_router(tools_router)

    @application.get("/health")
    async def health():
        return {"status": "healthy", "service": "mcp-service", "version": "1.0.0"}

    return application


app = create_app()


def run():
    """Entry point for the mcp-service script."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
