from pydantic import BaseModel, Field


class ClassificationResponse(BaseModel):
    filename: str
    file_type: str
    classification: str = Field(description="RFQ, Quotation, MPBC, BER, E-Auction, or Other")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    key_signals: list[str] = Field(default_factory=list)
    fields_matched: list[str] = Field(default_factory=list)
    fields_missing: list[str] = Field(default_factory=list)
    processing_time_ms: int


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class BatchClassificationResponse(BaseModel):
    results: list[ClassificationResponse]
    total_files: int
    total_processing_time_ms: int
