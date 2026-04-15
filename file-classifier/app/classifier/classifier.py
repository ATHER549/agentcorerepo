import time
import structlog
from app.config import settings
from app.extractors.base import ExtractionResult
from app.extractors.extractor_factory import get_extractor
from app.classifier.llm_client import call_llm_text, call_llm_vision
from app.classifier.prompt_templates import SYSTEM_PROMPT, USER_PROMPT_TEXT, USER_PROMPT_IMAGE
from app.utils.file_utils import detect_file_type
from app.utils.token_utils import truncate_to_token_limit

logger = structlog.get_logger()

VALID_CLASSIFICATIONS = {"Quotation", "MBPC", "Other"}


def classify_file(file_bytes: bytes, filename: str) -> dict:
    start_time = time.time()

    # Step 1: Detect file type
    file_type = detect_file_type(filename)
    logger.info("File type detected", filename=filename, file_type=file_type)

    # Step 2: Extract content
    extractor = get_extractor(file_type)
    extraction = extractor.extract(file_bytes, filename)
    logger.info("Content extracted", filename=filename, is_image=extraction.is_image_based)

    # Step 3: Classify
    result = _classify_with_llm(extraction, filename, file_type, use_mini=True)

    # Step 4: If low confidence, escalate to stronger model
    if result.get("confidence", 0) < settings.confidence_threshold:
        logger.info(
            "Low confidence, escalating to stronger model",
            confidence=result.get("confidence"),
            filename=filename,
        )
        result = _classify_with_llm(extraction, filename, file_type, use_mini=False)

    # Step 5: Validate and return
    result = _validate_result(result)
    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "filename": filename,
        "file_type": file_type,
        "classification": result["classification"],
        "confidence": result["confidence"],
        "reason": result["reason"],
        "processing_time_ms": elapsed_ms,
    }


def _classify_with_llm(
    extraction: ExtractionResult,
    filename: str,
    file_type: str,
    use_mini: bool,
) -> dict:
    extra_meta = ""
    for key, value in extraction.metadata.items():
        extra_meta += f"- {key}: {value}\n"

    if extraction.is_image_based and extraction.image_base64:
        user_prompt = USER_PROMPT_IMAGE.format(
            filename=filename,
            file_type=file_type,
            extra_metadata=extra_meta,
        )
        return call_llm_vision(SYSTEM_PROMPT, user_prompt, extraction.image_base64, use_mini=use_mini)
    else:
        truncated_content = truncate_to_token_limit(
            extraction.text_content,
            max_tokens=settings.max_content_tokens,
        )
        user_prompt = USER_PROMPT_TEXT.format(
            filename=filename,
            file_type=file_type,
            extra_metadata=extra_meta,
            extracted_content=truncated_content,
        )
        return call_llm_text(SYSTEM_PROMPT, user_prompt, use_mini=use_mini)


def _validate_result(result: dict) -> dict:
    classification = result.get("classification", "Other")
    if classification not in VALID_CLASSIFICATIONS:
        classification = "Other"

    confidence = result.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
        confidence = 0.0

    reason = result.get("reason", "No reason provided")

    return {
        "classification": classification,
        "confidence": round(confidence, 3),
        "reason": reason,
    }
