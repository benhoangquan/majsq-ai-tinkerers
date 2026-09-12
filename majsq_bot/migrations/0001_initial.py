# Generated manually for the initial majsq-agent schema.

import datetime
import majsq_bot.models
import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("platform_id", models.CharField(max_length=64, unique=True)),
                ("is_group", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Participant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("platform_user_id", models.CharField(max_length=64, unique=True)),
                ("username", models.CharField(blank=True, max_length=255)),
                ("festro_connected", models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name="ProcessedTelegramUpdate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("update_id", models.BigIntegerField(unique=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Membership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("use_my_taste", models.BooleanField(default=False)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="majsq_bot.conversation")),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="majsq_bot.participant")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("conversation", "participant"), name="unique_membership")]},
        ),
        migrations.CreateModel(
            name="PickSet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("share_id", models.CharField(default=majsq_bot.models.generate_share_id, editable=False, max_length=64, unique=True)),
                ("picks_json", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="picksets", to="majsq_bot.conversation")),
            ],
        ),
        migrations.CreateModel(
            name="FestroCredential",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("credential", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("participant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="festro_credential", to="majsq_bot.participant")),
            ],
        ),
        migrations.CreateModel(
            name="ConnectAttempt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("state", models.CharField(max_length=128, unique=True)),
                ("code_verifier", models.CharField(max_length=128)),
                ("redirect_uri", models.URLField(max_length=500)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("participant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="connect_attempts", to="majsq_bot.participant")),
            ],
        ),
    ]

