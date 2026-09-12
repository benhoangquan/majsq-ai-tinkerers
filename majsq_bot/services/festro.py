"""Festro PKCE callback exchange."""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any

import httpx
from django.conf import settings

from majsq_bot.models import ConnectAttempt, Participant


class FestroExchangeError(Exception):
    """A deliberately non-specific OAuth exchange failure."""


def begin_pkce_connect(*, participant: Participant, redirect_uri: str) -> tuple[ConnectAttempt, str]:
    """Create server-side OAuth state and return the S256 code challenge.

    The caller sends ``state`` and the challenge to Festro's authorization
    endpoint; the verifier remains solely in this database until callback.
    """
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    attempt = ConnectAttempt.expires_in_ten_minutes(
        participant=participant,
        state=secrets.token_urlsafe(32),
        code_verifier=verifier,
        redirect_uri=redirect_uri,
    )
    attempt.save()
    return attempt, challenge


def exchange_pkce_code(*, code: str, code_verifier: str, redirect_uri: str) -> str:
    """Exchange an authorization code and return its opaque access credential."""
    if not settings.FESTRO_CLIENT_ID:
        raise FestroExchangeError("Festro OAuth is not configured")
    form: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.FESTRO_CLIENT_ID,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }
    if settings.FESTRO_CLIENT_SECRET:
        form["client_secret"] = settings.FESTRO_CLIENT_SECRET
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = client.post(settings.FESTRO_TOKEN_URL, data=form, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise FestroExchangeError("Festro token exchange failed") from error
    credential = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(credential, str) or not credential:
        raise FestroExchangeError("Festro returned no credential")
    return credential
