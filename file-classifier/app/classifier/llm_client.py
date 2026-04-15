import json
import structlog
from openai import AzureOpenAI, OpenAI
from app.config import settings

logger = structlog.get_logger()


def _get_client() -> tuple:
    """Returns (client, model_name, mini_model_name) based on config."""
    if settings.llm_provider == "azure":
        client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        return client, settings.azure_openai_deployment_name, settings.azure_openai_mini_deployment_name
    else:
        client = OpenAI(api_key=settings.openai_api_key)
        return client, settings.openai_model, settings.openai_mini_model


def call_llm_text(
    system_prompt: str,
    user_prompt: str,
    use_mini: bool = True,
) -> dict:
    client, model, mini_model = _get_client()
    selected_model = mini_model if use_mini else model

    logger.info("Calling LLM", model=selected_model, use_mini=use_mini)

    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
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

    response = client.chat.completions.create(
        model=selected_model,
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
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    return json.loads(content)
