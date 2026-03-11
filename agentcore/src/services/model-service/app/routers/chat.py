import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import verify_api_key
from app.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.services.model_service import chat_completion, chat_completion_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    _api_key: str = Depends(verify_api_key),
):
    """Create a chat completion. Supports streaming and non-streaming modes."""
    try:
        if request.stream:
            return StreamingResponse(
                chat_completion_stream(request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return await chat_completion(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Error processing chat completion")
        raise HTTPException(status_code=500, detail=f"Internal error: {e!s}") from e
