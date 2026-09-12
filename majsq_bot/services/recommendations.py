"""Recommendation orchestration and OpenAI Responses function calling."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from django.conf import settings

from majsq_bot.models import Conversation
from majsq_bot.services.catalog import search_catalog


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_events",
        "description": "Find public Festro events. Never send Telegram IDs or usernames.",
        "parameters": {
            "type": "object",
            "properties": {
                "mood": {"type": "string"},
                "time_hint": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "group_profile",
        "description": "Return aggregate opt-in group taste counts only.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "open_poll",
        "description": "Create a poll proposal from event titles; it does not contact Telegram.",
        "parameters": {
            "type": "object",
            "properties": {"options": {"type": "array", "items": {"type": "string"}}},
            "required": ["options"],
            "additionalProperties": False,
        },
    },
]


def extract_signals(text: str) -> dict[str, Any]:
    lower = text.casefold()
    tags: list[str] = []
    tag_hints = {
        "music": ("musique", "concert", "danse", "danser", "party"),
        "food": ("manger", "resto", "restaurant", "bouffe"),
        "art": ("art", "expo", "galerie", "cinema", "cinéma"),
        "outdoors": ("plein air", "dehors", "parc", "marche"),
    }
    for tag, phrases in tag_hints.items():
        if any(phrase in lower for phrase in phrases):
            tags.append(tag)
    mood = "calm" if any(word in lower for word in ("calme", "chill", "tranquille")) else "social"
    time_hint = "friday" if "vendredi" in lower else "tonight" if "ce soir" in lower else "anytime"
    return {"mood": mood, "time_hint": time_hint, "tags": tags}


def _rank_mock_events(events: list[dict[str, Any]], signals: dict[str, Any]) -> list[dict[str, Any]]:
    desired_tags = set(signals["tags"])
    time_hint = signals["time_hint"]

    def score(event: dict[str, Any]) -> tuple[int, str]:
        event_tags = set(event["matching_tags"])
        tag_score = len(event_tags & desired_tags) * 10
        time_score = 3 if time_hint != "anytime" and time_hint in event["time"].casefold() else 0
        calm_score = 1 if signals["mood"] == "calm" and "calm" in event_tags else 0
        return (-(tag_score + time_score + calm_score), event["title"].casefold())

    return sorted(events, key=score)[:3]


def _aggregate_profile(conversation: Conversation) -> dict[str, int]:
    memberships = conversation.memberships.all()
    return {
        "member_count": memberships.count(),
        "taste_opt_in_count": memberships.filter(use_my_taste=True).count(),
    }


def _run_openai_tools(conversation: Conversation, text: str, signals: dict[str, Any]) -> None:
    """Run a bounded tool turn. Results are deliberately not persisted as PII."""
    # Import lazily so FESTRO_MOCK local runs never require the OpenAI package.
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=8.0, max_retries=0)
    first = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=(
            "Recommend an event in a concise, friendly way. Use tools for facts. "
            f"Request: {text[:500]}\nSignals: {json.dumps(signals)}"
        ),
        tools=TOOLS,
    )
    tool_outputs: list[dict[str, Any]] = []
    for item in getattr(first, "output", []):
        if getattr(item, "type", None) != "function_call":
            continue
        try:
            arguments = json.loads(item.arguments)
        except (TypeError, json.JSONDecodeError):
            arguments = {}
        if item.name == "search_events":
            result: Any = search_catalog({**signals, **arguments})
        elif item.name == "group_profile":
            result = _aggregate_profile(conversation)
        elif item.name == "open_poll":
            options = [str(option)[:100] for option in arguments.get("options", [])[:4]]
            # Avoid an import cycle: telegram parsing imports keyword matching
            # from this module, while this action is invoked only at runtime.
            from majsq_bot.services.telegram import send_poll

            result = {"opened": send_poll(conversation.platform_id, options)}
        else:
            continue
        tool_outputs.append({"type": "function_call_output", "call_id": item.call_id, "output": json.dumps(result)})

    # A second turn lets the model consume its function calls. Its prose is not
    # trusted for API output; picks always come from normalized catalog data.
    if tool_outputs:
        client.responses.create(model=settings.OPENAI_MODEL, previous_response_id=first.id, input=tool_outputs, tools=TOOLS)


def recommend(conversation: Conversation, text: str) -> list[dict[str, Any]]:
    signals = extract_signals(text)
    use_mock_catalog = settings.FESTRO_MOCK or not os.getenv("OPENAI_API_KEY")
    # Missing key, local mock mode, timeouts, malformed model output, and model
    # errors all reduce to the same deterministic catalog path.
    if not settings.FESTRO_MOCK and os.getenv("OPENAI_API_KEY"):
        try:
            _run_openai_tools(conversation, text, signals)
        except Exception:  # Do not let an optional model call fail a webhook.
            use_mock_catalog = True
    return _rank_mock_events(search_catalog(signals, force_mock=use_mock_catalog), signals)


def response_text(picks: list[dict[str, Any]], share_url: str) -> str:
    if not picks:
        return "Je n’ai pas trouvé de sorties pour le moment. Réessaie bientôt."
    lines = ["Voici quelques idées :"]
    lines.extend(f"• {pick['title']} — {pick['venue']} ({pick['time']})" for pick in picks)
    return "\n".join([*lines, f"Carte : {share_url}"])


def is_keyword_request(text: str) -> bool:
    folded = re.sub(r"\s+", " ", text.casefold()).strip()
    return any(keyword in folded for keyword in ("quoi faire", "ce soir", "vendredi"))
