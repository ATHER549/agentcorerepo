import json
import structlog
from openai import AzureOpenAI, OpenAI, BadRequestError
from app.config import settings

logger = structlog.get_logger()

# Cache: once we learn a model doesn't support temperature=0, remember it
_models_without_temperature: set[str] = set()

_client_cache: tuple | None = None


def _get_client() -> tuple:
    """Returns (client, model_name, mini_model_name) based on config. Cached."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache

    if settings.llm_provider == "azure":
        client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        _client_cache = (client, settings.azure_openai_deployment_name, settings.azure_openai_mini_deployment_name)
    else:
        client = OpenAI(api_key=settings.openai_api_key)
        _client_cache = (client, settings.openai_model, settings.openai_mini_model)

    return _client_cache


def _create_completion(client, model: str, **kwargs) -> str:
    """Call LLM, skipping temperature if model doesn't support it."""
    extra = {}
    if model not in _models_without_temperature:
        extra["temperature"] = 0.0

    try:
        response = client.chat.completions.create(model=model, **extra, **kwargs)
    except BadRequestError as e:
        if "temperature" in str(e):
            logger.info("Model does not support temperature=0, caching for future calls", model=model)
            _models_without_temperature.add(model)
            response = client.chat.completions.create(model=model, **kwargs)
        else:
            raise

    return response.choices[0].message.content


def call_llm_text(
    system_prompt: str,
    user_prompt: str,
    use_mini: bool = True,
) -> dict:
    client, model, mini_model = _get_client()
    selected_model = mini_model if use_mini else model

    logger.info("Calling LLM", model=selected_model, use_mini=use_mini)

    content = _create_completion(
        client,
        selected_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(content)


def call_llm_vision(
    system_prompt: str,
    user_prompt: str,
    image_base64: str,
    use_mini: bool = False,
) -> dict:
    client, model, mini_model = _get_client()
    selected_model = mini_model if use_mini else model

    logger.info("Calling Vision LLM", model=selected_model)

    content = _create_completion(
        client,
        selected_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(content)
