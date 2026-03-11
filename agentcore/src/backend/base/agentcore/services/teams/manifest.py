# Path: src/backend/base/agentcore/services/teams/manifest.py
"""Teams app manifest generation, icon creation, and ZIP packaging."""

from __future__ import annotations

import io
import json
import os
import zipfile
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from loguru import logger

if TYPE_CHECKING:
    from agentcore.services.database.models.agent.model import Agent


def generate_manifest(
    agent: Agent,
    bot_app_id: str,
    display_name: str,
    short_description: str | None = None,
    long_description: str | None = None,
    base_url: str = os.getenv("LOCALHOST_TEAMS_BOT_BASE_URL", "https://localhost:7860"),
    version: str = "1.0.0",
) -> dict:
    """Generate a Teams app manifest.json for a given agent.

    See: https://learn.microsoft.com/en-us/microsoftteams/platform/resources/schema/manifest-schema
    """
    # Generate a deterministic app ID from the agent ID
    manifest_id = str(uuid5(NAMESPACE_URL, f"agentcore-teams-{agent.id}"))

    short_desc = (short_description or agent.description or f"AgentCore: {agent.name}")[:80]
    full_desc = (
        long_description
        or agent.description
        or f"Interact with the {agent.name} agent built on AgentCore."
    )[:4000]

    return {
        "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
        "manifestVersion": "1.17",
        "version": version,
        "id": manifest_id,
        "developer": {
            "name": "AgentCore",
            "websiteUrl": base_url,
            "privacyUrl": f"{base_url}/privacy",
            "termsOfUseUrl": f"{base_url}/terms",
        },
        "name": {
            "short": display_name[:30],
            "full": display_name[:100],
        },
        "description": {
            "short": short_desc,
            "full": full_desc,
        },
        "icons": {
            "color": "color.png",
            "outline": "outline.png",
        },
        "accentColor": "#4F46E5",
        "bots": [
            {
                "botId": bot_app_id,
                "scopes": ["personal", "team", "groupChat"],
                "supportsFiles": False,
                "isNotificationOnly": False,
                "commandLists": [
                    {
                        "scopes": ["personal"],
                        "commands": [
                            {
                                "title": "Ask",
                                "description": f"Send a message to {display_name}",
                            },
                        ],
                    },
                ],
            },
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": [
            base_url.replace("https://", "").replace("http://", "").split("/")[0],
        ],
        "webApplicationInfo": {
            "id": bot_app_id,
            "resource": f"api://botid-{bot_app_id}",
        },
        "defaultInstallScope": "personal",
        "defaultGroupCapability": {
            "team": "bot",
            "groupchat": "bot",
        },
    }


def generate_icons(display_name: str) -> tuple[bytes, bytes]:
    """Generate color (192x192) and outline (32x32) PNG icons.

    Creates a colored circle with the first letter of the display name.
    Uses Pillow which is already a dependency (pillow>=11.1.0).
    """
    from PIL import Image, ImageDraw, ImageFont

    letter = display_name[0].upper() if display_name else "A"
    bg_color = "#4F46E5"  # Indigo accent
    text_color = "#FFFFFF"

    # Color icon: 192x192
    color_img = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
    draw = ImageDraw.Draw(color_img)
    draw.rounded_rectangle([(0, 0), (191, 191)], radius=32, fill=bg_color)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 96)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96)
        except (OSError, IOError):
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), letter, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (192 - text_w) / 2 - bbox[0]
    y = (192 - text_h) / 2 - bbox[1]
    draw.text((x, y), letter, fill=text_color, font=font)

    color_buffer = io.BytesIO()
    color_img.save(color_buffer, format="PNG")
    color_bytes = color_buffer.getvalue()

    # Outline icon: 32x32 (monochrome with transparent background)
    outline_img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw_outline = ImageDraw.Draw(outline_img)
    draw_outline.rounded_rectangle([(0, 0), (31, 31)], radius=6, outline="#FFFFFF", width=2)

    try:
        small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    except (OSError, IOError):
        try:
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        except (OSError, IOError):
            small_font = ImageFont.load_default()

    bbox = draw_outline.textbbox((0, 0), letter, font=small_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (32 - text_w) / 2 - bbox[0]
    y = (32 - text_h) / 2 - bbox[1]
    draw_outline.text((x, y), letter, fill="#FFFFFF", font=small_font)

    outline_buffer = io.BytesIO()
    outline_img.save(outline_buffer, format="PNG")
    outline_bytes = outline_buffer.getvalue()

    logger.debug(f"Generated Teams icons for '{display_name}' (color={len(color_bytes)}B, outline={len(outline_bytes)}B)")

    return color_bytes, outline_bytes


def create_teams_app_package(manifest: dict, color_icon: bytes, outline_icon: bytes) -> bytes:
    """Create a Teams app .zip package in memory.

    The package contains:
    - manifest.json
    - color.png (192x192)
    - outline.png (32x32)
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("color.png", color_icon)
        zf.writestr("outline.png", outline_icon)

    package = buffer.getvalue()
    logger.debug(f"Created Teams app package ({len(package)} bytes)")
    return package
