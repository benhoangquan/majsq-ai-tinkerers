# majsq-agent

Production-oriented Django 5 core for a Festro recommendation agent on
Telegram. It uses raw Django JSON endpoints, rather than adding a REST layer,
to keep the runtime dependency set to Django, `httpx`, and `openai`.

## Run locally

```bash
cp .env.example .env
# Replace the placeholder secrets, then export the file for this shell.
set -a; source .env; set +a
python3.12 -m venv .venv
.venv/bin/pip install -e .
FESTRO_MOCK=1 .venv/bin/python manage.py migrate
FESTRO_MOCK=1 .venv/bin/python manage.py runserver
```

`FESTRO_MOCK=1` is the default local workflow. It prevents Festro and OpenAI
network calls and deterministically reads [catalog.json](tests/fixtures/catalog.json).
Every catalog-query result, including mock results, uses Django's explicit
60-second in-memory cache. The app deliberately does not parse `.env` itself,
so load it through your process manager or export it as shown above.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `POST /telegram/webhook/` | Requires exact `X-Telegram-Bot-Api-Secret-Token`; persists only update IDs for deduplication. Group messages need a bot @mention, reply to this bot, or one of `quoi faire`, `ce soir`, `vendredi`. |
| `GET /api/picks/{share_id}/` | Public MapLibre-ready event data only: coordinates, title, venue, time, URL, and tags. It never returns conversation or participant data. |
| `POST /api/connect/callback/` | Exchanges a server-created PKCE `state` and authorization `code` at Festro, then stores the resulting opaque credential. |

The callback body is JSON: `{"code": "…", "state": "…"}`. Create a
server-side authorization attempt before redirecting to Festro with
`majsq_bot.services.festro.begin_pkce_connect()`. It returns the persisted
attempt and the S256 challenge; never expose its verifier.

When configured with `OPENAI_API_KEY`, the agent uses the Responses API tools
`search_events`, `group_profile`, and `open_poll`. Tool inputs omit Telegram
identifiers and usernames. `group_profile` returns aggregate opt-in counts;
`open_poll` sends only an anonymous Telegram poll after the model explicitly
calls it. A missing key, timeout, or model failure falls back to the
deterministic fixture; no incoming content or credentials are logged by
application code.

## Deployment notes

Set a long random `TELEGRAM_WEBHOOK_SECRET`, Telegram bot token and bot ID,
`PUBLIC_BASE_URL`, `DJANGO_SECRET_KEY`, and `DJANGO_DEBUG=0`. Leaving
`DATABASE_URL` unset selects SQLite; a `postgresql://` URL selects Django's
PostgreSQL backend. Supply the standard PostgreSQL driver in the deployment
image, keeping the app's direct dependency list constrained as requested. The
production defaults redirect HTTP and enable HSTS preload; set
`DJANGO_HSTS_PRELOAD=0` temporarily only if every HTTPS subdomain is not yet
ready.

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py test
```
