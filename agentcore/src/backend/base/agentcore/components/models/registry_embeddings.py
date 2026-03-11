"""Unified Embeddings component — thin wrapper around the Model microservice.

All embedding invocations are delegated to the Model microservice via
``MicroserviceEmbeddings``.  No provider SDKs are imported here.
"""

from __future__ import annotations

from loguru import logger

from agentcore.base.embeddings.model import LCEmbeddingsModel
from agentcore.field_typing import Embeddings
from agentcore.io import DropdownInput, IntInput

from agentcore.components.models._rbac_helpers import (
    check_model_access_sync,
    fetch_model_by_id_sync,
    filter_models_by_rbac,
    resolve_user_id,
)

# Display label → DB key mapping (embedding providers — no Anthropic/Groq)
PROVIDER_LABEL_TO_KEY = {
    "OpenAI": "openai",
    "Azure": "azure",
    "Google": "google",
    "Custom Model": "openai_compatible",
}
PROVIDER_KEY_TO_LABEL = {v: k for k, v in PROVIDER_LABEL_TO_KEY.items()}
PROVIDER_OPTIONS = list(PROVIDER_LABEL_TO_KEY.keys())


def _fetch_embedding_models_for_provider(provider: str, user_id: str | None = None) -> list[str]:
    """Fetch active embedding models from the microservice, filtered by provider and RBAC.

    Returns a list of strings formatted as ``'display_name | model_name | uuid'``.
    """
    if not provider:
        return []
    try:
        from agentcore.services.model_service_client import fetch_registry_models

        results = fetch_registry_models(provider=provider, model_type="embedding")
        if user_id:
            results = filter_models_by_rbac(results, user_id)
        return [
            f"{r['display_name']} | {r['model_name']} | {r['id']}"
            for r in results
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch embeddings via microservice: {e}")
        return []


class RegistryEmbeddingsComponent(LCEmbeddingsModel):
    """A unified Embeddings component that dynamically loads models from the Model Registry.

    Users onboard embedding models via the Model Registry page. This component
    lets them pick a provider, then select a registered embedding model.
    """

    display_name: str = "Embeddings Model"
    description: str = "Select a provider and embedding model from the Model Registry."
    icon = "Binary"
    name = "RegistryEmbeddingsComponent"
    priority = 0

    inputs = [
        DropdownInput(
            name="provider",
            display_name="Provider",
            info="Select the AI provider. Embedding models onboarded for this provider will appear below.",
            options=PROVIDER_OPTIONS,
            value="",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="registry_model",
            display_name="Registry Model",
            info="Select an embedding model from the Model Registry.",
            options=[],
            value="",
            refresh_button=True,
            real_time_refresh=True,
            combobox=True,
        ),
        IntInput(
            name="dimensions",
            display_name="Dimensions",
            info="Override output embedding dimensions. Leave empty for model default.",
            advanced=True,
        ),
    ]

    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):
        """Refresh dropdowns when provider changes or registry_model refresh is clicked."""
        current_user_id = resolve_user_id(self)

        if field_name == "provider":
            provider_key = PROVIDER_LABEL_TO_KEY.get(field_value, field_value)
            try:
                options = _fetch_embedding_models_for_provider(provider_key, user_id=current_user_id)
                build_config["registry_model"]["options"] = options if options else []
                build_config["registry_model"]["value"] = options[0] if options else ""
            except Exception as e:
                logger.warning(f"Error fetching embeddings for provider {provider_key}: {e}")
                build_config["registry_model"]["options"] = []
                build_config["registry_model"]["value"] = ""

        elif field_name == "registry_model":
            provider_label = build_config.get("provider", {}).get("value", "")
            provider_key = PROVIDER_LABEL_TO_KEY.get(provider_label, provider_label)
            if provider_key:
                try:
                    options = _fetch_embedding_models_for_provider(provider_key, user_id=current_user_id)
                    build_config["registry_model"]["options"] = options if options else []
                    if options and not build_config["registry_model"].get("value"):
                        build_config["registry_model"]["value"] = options[0]
                except Exception as e:
                    logger.warning(f"Error refreshing registry embeddings: {e}")
                    build_config["registry_model"]["options"] = []

        return build_config

    def build_embeddings(self) -> Embeddings:
        """Build a MicroserviceEmbeddings proxy that delegates to the Model microservice."""
        from agentcore.services.model_service_client import MicroserviceEmbeddings, _get_model_service_settings

        selected = self.registry_model
        if not selected:
            msg = "No model selected. Please select a model from the Registry Model dropdown."
            raise ValueError(msg)

        parts = [p.strip() for p in selected.split("|")]
        if len(parts) < 3:
            msg = f"Invalid registry model format: {selected}. Please refresh the dropdown."
            raise ValueError(msg)

        model_name = parts[1]
        model_id = parts[2]

        # Defence-in-depth: verify RBAC access before building proxy
        current_user_id = resolve_user_id(self)
        if current_user_id:
            model_dict = fetch_model_by_id_sync(model_id)
            if model_dict and not check_model_access_sync(model_dict, current_user_id):
                raise ValueError("Access denied to selected embedding model due to RBAC scope")

        provider_label = self.provider or ""
        provider_key = PROVIDER_LABEL_TO_KEY.get(provider_label, provider_label).lower()

        dimensions = self.dimensions if self.dimensions not in (None, "") else None
        if dimensions is not None:
            dimensions = int(dimensions)

        service_url, service_api_key = _get_model_service_settings()

        return MicroserviceEmbeddings(
            service_url=service_url,
            service_api_key=service_api_key,
            provider=provider_key,
            model=model_name,
            registry_model_id=model_id,
            dimensions=dimensions,
        )
