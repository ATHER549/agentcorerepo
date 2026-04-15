from pydantic import BaseModel, Field


class ClassificationResponse(BaseModel):
    filename: str
    file_type: str
    classification: str = Field(description="Quotation, MBPC, or Other")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    processing_time_ms: int


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class BatchClassificationResponse(BaseModel):
    results: list[ClassificationResponse]
    total_files: int
    total_processing_time_ms: int
