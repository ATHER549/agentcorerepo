from typing_extensions import TypedDict

from agentcore.base.models.model import LCModelNode
from agentcore.components.models.azure_openai import AzureChatOpenAIComponent
from agentcore.components.models.google_generative_ai import GoogleGenerativeAIComponent
from agentcore.components.models.groq import GroqModel
from agentcore.inputs.inputs import InputTypes, SecretStrInput
from agentcore.template.field.base import Input


class ModelProvidersDict(TypedDict):
    fields: dict
    inputs: list[InputTypes]
    prefix: str
    component_class: LCModelNode
    icon: str
    is_active: bool


def get_filtered_inputs(component_class):
    base_input_names = {field.name for field in LCModelNode._base_inputs}
    component_instance = component_class()

    return [process_inputs(input_) for input_ in component_instance.inputs if input_.name not in base_input_names]


def process_inputs(component_data: Input):
    """Processes and modifies an input configuration based on its type or name.

    Adjusts properties such as value, advanced status, real-time refresh, and additional information for specific
    input types or names to ensure correct behavior in the UI and provider integration.

    Args:
        component_data: The input configuration to process.

    Returns:
        The modified input configuration.
    """
    if isinstance(component_data, SecretStrInput):
        component_data.value = ""
        component_data.load_from_db = False
        component_data.real_time_refresh = True
        if component_data.name == "api_key":
            component_data.required = False
    elif component_data.name == "tool_model_enabled":
        component_data.advanced = True
        component_data.value = True
    elif component_data.name in {"temperature", "base_url"}:
        component_data = set_advanced_true(component_data)
    elif component_data.name == "model_name":
        component_data = set_real_time_refresh_false(component_data)
        component_data = add_combobox_true(component_data)
        component_data = add_info(
            component_data,
            "To see the model names, first choose a provider. Then, enter your API key and click the refresh button "
            "next to the model name.",
        )
    return component_data


def set_advanced_true(component_input):
    component_input.advanced = True
    return component_input


def set_real_time_refresh_false(component_input):
    component_input.real_time_refresh = False
    return component_input


def add_info(component_input, info_str: str):
    component_input.info = info_str
    return component_input


def add_combobox_true(component_input):
    component_input.combobox = True
    return component_input


def create_input_fields_dict(inputs: list[Input], prefix: str) -> dict[str, Input]:
    return {f"{prefix}{input_.name}": input_.to_dict() for input_ in inputs}


def _get_google_generative_ai_inputs_and_fields():
    try:
        from agentcore.components.models.google_generative_ai import GoogleGenerativeAIComponent

        google_generative_ai_inputs = get_filtered_inputs(GoogleGenerativeAIComponent)
    except ImportError as e:
        msg = (
            "Google Generative AI is not installed. Please install it with "
            "`pip install langchain-google-generative-ai`."
        )
        raise ImportError(msg) from e
    return google_generative_ai_inputs, create_input_fields_dict(google_generative_ai_inputs, "")


def _get_azure_inputs_and_fields():
    try:
        from agentcore.components.models.azure_openai import AzureChatOpenAIComponent

        azure_inputs = get_filtered_inputs(AzureChatOpenAIComponent)
    except ImportError as e:
        msg = "Azure OpenAI is not installed. Please install it with `pip install langchain-azure-openai`."
        raise ImportError(msg) from e
    return azure_inputs, create_input_fields_dict(azure_inputs, "")


def _get_groq_inputs_and_fields():
    try:
        from agentcore.components.models.groq import GroqModel

        groq_inputs = get_filtered_inputs(GroqModel)
    except ImportError as e:
        msg = "Groq is not installed. Please install it with `pip install langchain-groq`."
        raise ImportError(msg) from e
    return groq_inputs, create_input_fields_dict(groq_inputs, "")


MODEL_PROVIDERS_DICT: dict[str, ModelProvidersDict] = {}

try:
    azure_inputs, azure_fields = _get_azure_inputs_and_fields()
    MODEL_PROVIDERS_DICT["Azure OpenAI"] = {
        "fields": azure_fields,
        "inputs": azure_inputs,
        "prefix": "",
        "component_class": AzureChatOpenAIComponent(),
        "icon": AzureChatOpenAIComponent.icon,
        "is_active": False,
    }
except ImportError:
    pass

try:
    groq_inputs, groq_fields = _get_groq_inputs_and_fields()
    MODEL_PROVIDERS_DICT["Groq"] = {
        "fields": groq_fields,
        "inputs": groq_inputs,
        "prefix": "",
        "component_class": GroqModel(),
        "icon": GroqModel.icon,
        "is_active": True,
    }
except ImportError:
    pass


try:
    google_generative_ai_inputs, google_generative_ai_fields = _get_google_generative_ai_inputs_and_fields()
    MODEL_PROVIDERS_DICT["Google Generative AI"] = {
        "fields": google_generative_ai_fields,
        "inputs": google_generative_ai_inputs,
        "prefix": "",
        "component_class": GoogleGenerativeAIComponent(),
        "icon": GoogleGenerativeAIComponent.icon,
        "is_active": True,
    }
except ImportError:
    pass

ACTIVE_MODEL_PROVIDERS_DICT: dict[str, ModelProvidersDict] = {
    name: prov for name, prov in MODEL_PROVIDERS_DICT.items() if prov.get("is_active", True)
}

MODEL_PROVIDERS: list[str] = list(ACTIVE_MODEL_PROVIDERS_DICT.keys())

ALL_PROVIDER_FIELDS: list[str] = [field for prov in ACTIVE_MODEL_PROVIDERS_DICT.values() for field in prov["fields"]]

MODEL_DYNAMIC_UPDATE_FIELDS = ["api_key", "model", "tool_model_enabled", "base_url", "model_name"]

MODELS_METADATA = {name: {"icon": prov["icon"]} for name, prov in ACTIVE_MODEL_PROVIDERS_DICT.items()}
