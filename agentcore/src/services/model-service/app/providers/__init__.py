# Import all providers to trigger @register_provider decorators
from app.providers import (  # noqa: F401
    anthropic,
    azure_openai,
    google,
    groq,
    openai_compatible,
    openai_provider,
)
