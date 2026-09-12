from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from majsq_bot.models import ConnectAttempt, Conversation, FestroCredential, Membership, Participant, PickSet, ProcessedTelegramUpdate
from majsq_bot.services.festro import FestroExchangeError, exchange_pkce_code
from majsq_bot.services.recommendations import recommend, response_text
from majsq_bot.services.telegram import send_message, should_respond, update_message, valid_secret


def _json_body(request: HttpRequest) -> dict[str, Any] | None:
    if len(request.body) > 1_000_000:
        return None
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _remember_update(update_id: Any) -> bool:
    if not isinstance(update_id, int):
        return False
    try:
        with transaction.atomic():
            ProcessedTelegramUpdate.objects.create(update_id=update_id)
    except IntegrityError:
        return False
    return True


def _conversation_and_member(message: dict[str, Any]) -> Conversation:
    chat = message["chat"]
    sender = message["from"]
    conversation, created = Conversation.objects.get_or_create(
        platform_id=str(chat["id"]),
        defaults={"is_group": chat.get("type") in {"group", "supergroup"}},
    )
    if not created and conversation.is_group != (chat.get("type") in {"group", "supergroup"}):
        conversation.is_group = chat.get("type") in {"group", "supergroup"}
        conversation.save(update_fields=["is_group"])
    participant, _ = Participant.objects.update_or_create(
        platform_user_id=str(sender["id"]),
        defaults={"username": str(sender.get("username", ""))[:255]},
    )
    Membership.objects.get_or_create(conversation=conversation, participant=participant)
    return conversation


@csrf_exempt
def telegram_webhook(request: HttpRequest) -> JsonResponse | HttpResponseNotAllowed:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not valid_secret(request.headers.get("X-Telegram-Bot-Api-Secret-Token")):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    update = _json_body(request)
    if update is None or not isinstance(update.get("update_id"), int):
        return JsonResponse({"ok": False, "error": "invalid_update"}, status=400)
    if not _remember_update(update["update_id"]):
        # Duplicate delivery is a successful no-op.
        return JsonResponse({"ok": True, "duplicate": True})
    message = update_message(update)
    if message is None or not should_respond(message):
        return JsonResponse({"ok": True, "ignored": True})
    if not isinstance(message.get("chat"), dict) or not isinstance(message.get("from"), dict):
        return JsonResponse({"ok": True, "ignored": True})
    if "id" not in message["chat"] or "id" not in message["from"]:
        return JsonResponse({"ok": True, "ignored": True})

    conversation = _conversation_and_member(message)
    picks = recommend(conversation, str(message.get("text", "")))
    pickset = PickSet.objects.create(conversation=conversation, picks_json=picks)
    share_url = f"{settings.PUBLIC_BASE_URL}/api/picks/{pickset.share_id}/"
    text = response_text(picks, share_url)
    message_id = message.get("message_id")
    send_message(str(message["chat"]["id"]), text, message_id if isinstance(message_id, int) else None)
    return JsonResponse({"ok": True, "pick_share_id": pickset.share_id})


def pickset_detail(request: HttpRequest, share_id: str) -> JsonResponse | HttpResponseNotAllowed:
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        pickset = PickSet.objects.only("picks_json").get(share_id=share_id)
    except PickSet.DoesNotExist:
        return JsonResponse({"detail": "not found"}, status=404)
    picks = pickset.picks_json if isinstance(pickset.picks_json, list) else []
    public_picks = [
        {
            "lat": pick.get("lat"),
            "lng": pick.get("lng"),
            "title": pick.get("title", ""),
            "venue": pick.get("venue", ""),
            "time": pick.get("time", ""),
            "url": pick.get("url", ""),
            "matching_tags": pick.get("matching_tags", []),
        }
        for pick in picks
        if isinstance(pick, dict)
    ]
    return JsonResponse({"picks": public_picks})


@csrf_exempt
def connect_callback(request: HttpRequest) -> JsonResponse | HttpResponseNotAllowed:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"detail": "invalid JSON"}, status=400)
    code, state = payload.get("code"), payload.get("state")
    if not isinstance(code, str) or not isinstance(state, str) or not code or not state:
        return JsonResponse({"detail": "code and state are required"}, status=400)
    try:
        attempt = ConnectAttempt.objects.select_related("participant").get(state=state)
    except ConnectAttempt.DoesNotExist:
        return JsonResponse({"detail": "invalid state"}, status=400)
    if attempt.expires_at <= timezone.now():
        attempt.delete()
        return JsonResponse({"detail": "expired state"}, status=400)
    try:
        credential = exchange_pkce_code(code=code, code_verifier=attempt.code_verifier, redirect_uri=attempt.redirect_uri)
    except FestroExchangeError:
        return JsonResponse({"detail": "connection could not be completed"}, status=502)
    with transaction.atomic():
        FestroCredential.objects.update_or_create(participant=attempt.participant, defaults={"credential": credential})
        Participant.objects.filter(pk=attempt.participant_id).update(festro_connected=True)
        attempt.delete()
    return JsonResponse({"connected": True})
