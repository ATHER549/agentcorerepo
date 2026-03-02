# Path: src/backend/base/agentcore/services/teams/adaptive_cards.py
"""Adaptive Card templates for Teams bot responses."""

from __future__ import annotations


def text_response_card(agent_name: str, response_text: str) -> dict:
    """Simple text response card."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": agent_name,
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
            },
            {
                "type": "TextBlock",
                "text": response_text,
                "wrap": True,
            },
        ],
    }


def error_card(agent_name: str, error_message: str) -> dict:
    """Error response card."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": f"{agent_name} - Error",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
            },
            {
                "type": "TextBlock",
                "text": error_message,
                "wrap": True,
                "color": "Attention",
            },
        ],
    }


def thinking_card(agent_name: str) -> dict:
    """Card shown while the flow is executing."""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": agent_name,
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
            },
            {
                "type": "TextBlock",
                "text": "Processing your request...",
                "wrap": True,
                "isSubtle": True,
            },
        ],
    }


def welcome_card(agent_name: str, agent_description: str | None = None) -> dict:
    """Welcome card shown when a user first interacts with the bot."""
    body = [
        {
            "type": "TextBlock",
            "text": f"Welcome to {agent_name}!",
            "weight": "Bolder",
            "size": "Large",
            "color": "Accent",
        },
    ]

    if agent_description:
        body.append(
            {
                "type": "TextBlock",
                "text": agent_description,
                "wrap": True,
            }
        )

    body.append(
        {
            "type": "TextBlock",
            "text": "Send me a message to get started.",
            "wrap": True,
            "isSubtle": True,
        }
    )

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
    }


def structured_response_card(agent_name: str, data: dict) -> dict:
    """Card for structured/JSON responses with key-value layout."""
    facts = [{"title": str(k), "value": str(v)} for k, v in data.items()]

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": agent_name,
                "weight": "Bolder",
                "size": "Medium",
                "color": "Accent",
            },
            {
                "type": "FactSet",
                "facts": facts,
            },
        ],
    }
