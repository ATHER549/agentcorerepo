"""Pure utility functions for MCP operations."""

from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

# RFC 7230 compliant header name pattern
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&\'*+\-.0-9A-Z^_`a-z|~]+$")

# Common allowed headers for MCP connections
ALLOWED_HEADERS = {
    "authorization",
    "accept",
    "accept-encoding",
    "accept-language",
    "cache-control",
    "content-type",
    "user-agent",
    "x-api-key",
    "x-auth-token",
    "x-custom-header",
    "x-agentcore-session",
    "x-mcp-client",
    "x-requested-with",
}


def validate_headers(headers: dict[str, str]) -> dict[str, str]:
    """Validate and sanitize HTTP headers according to RFC 7230."""
    if not headers:
        return {}

    sanitized_headers = {}

    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            logger.warning(f"Skipping non-string header: {name}={value}")
            continue

        if not HEADER_NAME_PATTERN.match(name):
            logger.warning(f"Invalid header name '{name}', skipping")
            continue

        normalized_name = name.lower()

        if normalized_name not in ALLOWED_HEADERS:
            logger.debug(f"Using non-standard header: {normalized_name}")

        if "\r" in value or "\n" in value:
            logger.warning(f"Potential header injection detected in '{name}', skipping")
            continue

        sanitized_value = re.sub(r"[\x00-\x08\x0A-\x1F\x7F]", "", value)
        sanitized_value = sanitized_value.strip()

        if not sanitized_value:
            logger.warning(f"Header '{name}' has empty value after sanitization, skipping")
            continue

        sanitized_headers[normalized_name] = sanitized_value

    return sanitized_headers


def sanitize_mcp_name(name: str, max_length: int = 46) -> str:
    """Sanitize a name for MCP usage by removing emojis, diacritics, and special characters."""
    if not name or not name.strip():
        return ""

    # Remove emojis using regex pattern
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\U00002500-\U00002bef"
        "\U00002702-\U000027b0"
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2b55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"
        "\u3030"
        "]+",
        flags=re.UNICODE,
    )

    name = emoji_pattern.sub("", name)
    name = unicodedata.normalize("NFD", name)
    name = "".join(char for char in name if unicodedata.category(char) != "Mn")
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[-\s]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")

    if name and name[0].isdigit():
        name = f"_{name}"

    name = name.lower()

    if len(name) > max_length:
        name = name[:max_length].rstrip("_")

    if not name:
        name = "unnamed"

    return name


def extract_tool_result(result) -> str:
    """Extract readable text from an MCP CallToolResult.

    Concatenates all TextContent blocks. For ImageContent, includes a
    markdown image tag so the chat UI can render it.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result

    parts: list[str] = []
    content_list = getattr(result, "content", None)
    if content_list:
        for block in content_list:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                parts.append(getattr(block, "text", ""))
            elif block_type == "image":
                mime = getattr(block, "mimeType", "image/png")
                data = getattr(block, "data", "")
                parts.append(f"![chart](data:{mime};base64,{data})")
            else:
                text = getattr(block, "text", None) or str(block)
                parts.append(text)

    structured = getattr(result, "structuredContent", None)
    if structured:
        import json as _json
        parts.append(_json.dumps(structured, ensure_ascii=False))

    return "\n".join(parts) if parts else str(result)


def _is_valid_key_value_item(item: Any) -> bool:
    """Check if an item is a valid key-value dictionary."""
    return isinstance(item, dict) and "key" in item and "value" in item


def process_headers(headers: Any) -> dict:
    """Process the headers input into a valid dictionary."""
    if headers is None:
        return {}
    if isinstance(headers, dict):
        return validate_headers(headers)
    if isinstance(headers, list):
        processed_headers = {}
        try:
            for item in headers:
                if not _is_valid_key_value_item(item):
                    continue
                key = item["key"]
                value = item["value"]
                processed_headers[key] = value
        except (KeyError, TypeError, ValueError):
            return {}
        return validate_headers(processed_headers)
    return {}


def validate_node_installation(command: str) -> str:
    """Validate the npx command."""
    if "npx" in command and not shutil.which("node"):
        msg = "Node.js is not installed. Please install Node.js to use npx commands."
        raise ValueError(msg)
    return command


async def validate_connection_params(mode: str, command: str | None = None, url: str | None = None) -> None:
    """Validate connection parameters based on mode."""
    if mode not in ["Stdio", "SSE"]:
        msg = f"Invalid mode: {mode}. Must be either 'Stdio' or 'SSE'"
        raise ValueError(msg)

    if mode == "Stdio" and not command:
        msg = "Command is required for Stdio mode"
        raise ValueError(msg)
    if mode == "Stdio" and command:
        validate_node_installation(command)
    if mode == "SSE" and not url:
        msg = "URL is required for SSE mode"
        raise ValueError(msg)
