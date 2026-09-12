from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from majsq_bot.models import ConnectAttempt, Conversation, FestroCredential, Participant, PickSet
from majsq_bot.services.catalog import search_catalog


@override_settings(
    FESTRO_MOCK=True,
    TELEGRAM_WEBHOOK_SECRET="test-webhook-secret",
    TELEGRAM_BOT_USERNAME="majsq_bot",
    PUBLIC_BASE_URL="https://agent.example.test",
)
class TelegramWebhookTests(TestCase):
    def webhook(self, update: dict) -> object:
        return self.client.post(
            "/telegram/webhook/",
            data=json.dumps(update),
            content_type="application/json",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
        )

    def test_rejects_missing_or_wrong_webhook_secret(self) -> None:
        response = self.client.post("/telegram/webhook/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_group_keyword_creates_pickset_and_deduplicates(self) -> None:
        update = {
            "update_id": 6001,
            "message": {
                "message_id": 11,
                "text": "Quoi faire ce soir pour danser?",
                "chat": {"id": -10042, "type": "supergroup"},
                "from": {"id": 101, "username": "someone"},
            },
        }
        with patch("majsq_bot.views.send_message", return_value=True) as send:
            response = self.webhook(update)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(PickSet.objects.count(), 1)
        self.assertTrue(send.called)

        duplicate = self.webhook(update)
        self.assertEqual(duplicate.json(), {"ok": True, "duplicate": True})
        self.assertEqual(PickSet.objects.count(), 1)

    def test_group_chatter_is_ignored_without_creating_people(self) -> None:
        response = self.webhook(
            {
                "update_id": 6002,
                "message": {
                    "message_id": 12,
                    "text": "Salut tout le monde",
                    "chat": {"id": -10043, "type": "group"},
                    "from": {"id": 102, "username": "another"},
                },
            }
        )
        self.assertEqual(response.json(), {"ok": True, "ignored": True})
        self.assertEqual(Conversation.objects.count(), 0)

    def test_pick_endpoint_exposes_only_public_event_data(self) -> None:
        conversation = Conversation.objects.create(platform_id="-10044", is_group=True)
        pickset = PickSet.objects.create(
            conversation=conversation,
            picks_json=[
                {
                    "lat": 45.5,
                    "lng": -73.5,
                    "title": "Event",
                    "venue": "Venue",
                    "time": "Tonight",
                    "url": "https://festro.com/e/1",
                    "matching_tags": ["music"],
                    "username": "must-not-leak",
                }
            ],
        )
        response = self.client.get(f"/api/picks/{pickset.share_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("username", response.content.decode())
        self.assertEqual(response.json()["picks"][0]["title"], "Event")


@override_settings(FESTRO_MOCK=True)
class CatalogTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_mock_catalog_is_cached_for_sixty_seconds(self) -> None:
        first = search_catalog({"mood": "social"})
        self.assertEqual(len(first), 4)
        with patch("majsq_bot.services.catalog._mock_catalog", side_effect=AssertionError("cache miss")):
            again = search_catalog({"mood": "social"})
        self.assertEqual(first, again)


class ConnectCallbackTests(TestCase):
    @override_settings(FESTRO_CLIENT_ID="client-id")
    @patch("majsq_bot.views.exchange_pkce_code", return_value="opaque-access-token")
    def test_callback_exchanges_state_and_marks_connection(self, exchange: object) -> None:
        participant = Participant.objects.create(platform_user_id="303", username="person")
        ConnectAttempt.objects.create(
            participant=participant,
            state="good-state",
            code_verifier="a" * 64,
            redirect_uri="https://app.example.test/connect/callback",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        response = self.client.post(
            "/api/connect/callback/",
            data=json.dumps({"code": "authorization-code", "state": "good-state"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        participant.refresh_from_db()
        self.assertTrue(participant.festro_connected)
        self.assertEqual(FestroCredential.objects.get(participant=participant).credential, "opaque-access-token")
        self.assertFalse(ConnectAttempt.objects.filter(state="good-state").exists())

