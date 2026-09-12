from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone


def generate_share_id() -> str:
    """Return a high-entropy, URL-safe public identifier (192 bits)."""
    return secrets.token_urlsafe(24)


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Conversation(UUIDModel):
    platform_id = models.CharField(max_length=64, unique=True)
    is_group = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Conversation({self.id})"


class Participant(UUIDModel):
    platform_user_id = models.CharField(max_length=64, unique=True)
    username = models.CharField(max_length=255, blank=True)
    festro_connected = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Participant({self.id})"


class Membership(UUIDModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="memberships")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="memberships")
    use_my_taste = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conversation", "participant"], name="unique_membership"),
        ]


class PickSet(UUIDModel):
    share_id = models.CharField(max_length=64, unique=True, default=generate_share_id, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="picksets")
    picks_json = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class ProcessedTelegramUpdate(UUIDModel):
    """Stores only the update ID: enough for idempotency, never message content."""

    update_id = models.BigIntegerField(unique=True)
    received_at = models.DateTimeField(auto_now_add=True)


class ConnectAttempt(UUIDModel):
    """Server-side PKCE state. Create this during the OAuth start flow."""

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="connect_attempts")
    state = models.CharField(max_length=128, unique=True)
    code_verifier = models.CharField(max_length=128)
    redirect_uri = models.URLField(max_length=500)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def expires_in_ten_minutes(cls, **kwargs: object) -> "ConnectAttempt":
        return cls(expires_at=timezone.now() + timedelta(minutes=10), **kwargs)


class FestroCredential(UUIDModel):
    """An opaque Festro credential; never serialize or log this value."""

    participant = models.OneToOneField(Participant, on_delete=models.CASCADE, related_name="festro_credential")
    credential = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

