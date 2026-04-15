from fastapi import FastAPI
from app.api.routes import router
from app.utils.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title="File Classification API",
    description="Classify files as Quotation, MBPC, or Other using LLM",
    version="1.0.0",
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
