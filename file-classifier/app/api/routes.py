import time
import structlog
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.api.schemas import ClassificationResponse, BatchClassificationResponse, ErrorResponse
from app.classifier.classifier import classify_file
from app.config import settings
from app.utils.file_utils import validate_file_size, SUPPORTED_EXTENSIONS
from pathlib import Path

logger = structlog.get_logger()

router = APIRouter()


@router.post(
    "/classify",
    response_model=ClassificationResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def classify_single_file(file: UploadFile = File(...)):
    # Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    # Read file
    file_bytes = await file.read()

    # Validate file size
    if not validate_file_size(len(file_bytes), settings.max_file_size_mb):
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {settings.max_file_size_mb}MB",
        )

    try:
        result = classify_file(file_bytes, file.filename or "unknown")
        return ClassificationResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Classification failed", error=str(e), filename=file.filename)
        raise HTTPException(status_code=500, detail=f"Classification failed: {str(e)}")


@router.post(
    "/classify-batch",
    response_model=BatchClassificationResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def classify_batch(files: list[UploadFile] = File(...)):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 files per batch request")

    start_time = time.time()
    results = []

    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            logger.warning("Skipping unsupported file", filename=file.filename, ext=ext)
            continue

        file_bytes = await file.read()

        if not validate_file_size(len(file_bytes), settings.max_file_size_mb):
            logger.warning("Skipping oversized file", filename=file.filename)
            continue

        try:
            result = classify_file(file_bytes, file.filename or "unknown")
            results.append(ClassificationResponse(**result))
        except Exception as e:
            logger.error("Classification failed for file", filename=file.filename, error=str(e))

    total_ms = int((time.time() - start_time) * 1000)

    return BatchClassificationResponse(
        results=results,
        total_files=len(results),
        total_processing_time_ms=total_ms,
    )
