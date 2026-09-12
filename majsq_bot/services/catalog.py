"""Catalog access with deterministic local-mode recommendations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache


CACHE_SECONDS = 60
FIXTURE_PATH = Path(settings.BASE_DIR) / "tests" / "fixtures" / "catalog.json"


def _cache_key(query: dict[str, Any]) -> str:
    encoded = json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"catalog-search:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _mock_catalog() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    return payload["events"] if isinstance(payload, dict) else payload


def _normalise_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return only fields the pick API is allowed to expose."""
    try:
        lat = float(event["lat"])
        lng = float(event["lng"])
        title = str(event["title"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or not title:
        return None
    return {
        "lat": lat,
        "lng": lng,
        "title": title[:200],
        "venue": str(event.get("venue", ""))[:200],
        "time": str(event.get("time", ""))[:80],
        "url": str(event.get("url", ""))[:500],
        "matching_tags": [str(tag)[:50] for tag in event.get("tags", event.get("matching_tags", []))][:12],
    }


def _remote_catalog(query: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch a Festro catalog only when a deployment explicitly configures it."""
    if not settings.FESTRO_API_URL:
        return _mock_catalog()
    # Payload intentionally excludes chat, username, and Telegram user identifiers.
    with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        response = client.post(settings.FESTRO_API_URL, json=query)
        response.raise_for_status()
    payload = response.json()
    events = payload.get("events", payload) if isinstance(payload, dict) else payload
    return events if isinstance(events, list) else []


def search_catalog(query: dict[str, Any], *, force_mock: bool = False) -> list[dict[str, Any]]:
    """Search public events, caching every request for exactly 60 seconds."""
    cache_key = _cache_key({"query": query, "mock": force_mock or settings.FESTRO_MOCK})
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        source = _mock_catalog() if force_mock or settings.FESTRO_MOCK else _remote_catalog(query)
    except (OSError, ValueError, httpx.HTTPError, json.JSONDecodeError):
        # Catalog outages never prevent the Telegram webhook from acknowledging
        # an update. The deterministic fixture is a safe degraded response.
        source = _mock_catalog()
    events = [normalised for event in source if (normalised := _normalise_event(event))]
    cache.set(cache_key, events, timeout=CACHE_SECONDS)
    return events
