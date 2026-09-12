"""Telegram parsing and delivery with no message-content logging."""

from __future__ import annotations

import secrets
from typing import Any

import httpx
from django.conf import settings

from majsq_bot.services.recommendations import is_keyword_request


def valid_secret(value: str | None) -> bool:
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    return bool(expected and value and secrets.compare_digest(value, expected))


def update_message(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message") or update.get("edited_message")
    return message if isinstance(message, dict) else None


def _is_direct_mention(message: dict[str, Any]) -> bool:
    username = settings.TELEGRAM_BOT_USERNAME.casefold()
    if not username:
        return False
    text = str(message.get("text", "")).casefold()
    # Entity validation avoids treating a venue's text like an accidental ping.
    for entity in message.get("entities", []):
        if entity.get("type") != "mention":
            continue
        offset, length = entity.get("offset"), entity.get("length")
        if isinstance(offset, int) and isinstance(length, int) and text[offset : offset + length] == f"@{username}":
            return True
    return f"@{username}" in text


def _is_reply_to_this_bot(message: dict[str, Any]) -> bool:
    sender = message.get("reply_to_message", {}).get("from", {})
    configured_id = str(settings.TELEGRAM_BOT_ID)
    if configured_id:
        return str(sender.get("id", "")) == configured_id
    configured_username = settings.TELEGRAM_BOT_USERNAME.casefold()
    return bool(configured_username and str(sender.get("username", "")).casefold() == configured_username)


def should_respond(message: dict[str, Any]) -> bool:
    chat = message.get("chat", {})
    if chat.get("type") not in {"group", "supergroup"}:
        return True
    text = str(message.get("text", ""))
    return _is_direct_mention(message) or _is_reply_to_this_bot(message) or is_keyword_request(text)


def send_message(chat_id: str, text: str, reply_to_message_id: int | None = None) -> bool:
    """Send an outgoing message. Token and request data are never logged."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_to_message_id is not None:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
            )
            return response.is_success
    except httpx.HTTPError:
        return False


def send_poll(chat_id: str, options: list[str]) -> bool:
    """Open a Telegram poll after an explicit ``open_poll`` model tool call."""
    if not settings.TELEGRAM_BOT_TOKEN or not 2 <= len(options) <= 10:
        return False
    payload = {
        "chat_id": chat_id,
        "question": "Quelle sortie vous tente le plus ?",
        "options": options,
        "is_anonymous": True,
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendPoll",
                json=payload,
            )
            return response.is_success
    except httpx.HTTPError:
        return False
