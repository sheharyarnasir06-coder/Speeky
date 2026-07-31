# Speeky AI — Backend (FastAPI)

FastAPI REST API for the Speeky AI application. Started as a 1:1 port of the original
Express auth backend (same routes, cookies, DB schema — frontend needed zero changes for
that slice) and has since grown to cover Sprint 1's full feature set: baseline assessment,
AI Conversation Practice, Interview Coach, Workplace English Coach, resume/JD intake, and
cross-session memory — on top of the same Prisma schema/migrations, via
[prisma-client-py](https://prisma-client-py.readthedocs.io/).

---

## Tech Stack

| Layer            | Choice                                                                              |
| ---------------- | ------------------------------------------------------------------------------------ |
| Runtime          | Python 3.11+                                                                        |
| Framework        | FastAPI + Uvicorn                                                                   |
| ORM              | prisma-client-py (reuses the original `prisma/schema.prisma` and migrations as-is)  |
| Database         | PostgreSQL (Prisma Postgres cloud or local Docker) — structured data (users, sessions, assessments) |
| KV store         | `KvEntry` Prisma table (`lib/kv_store.py`) — variable-shaped session state for the ported features (interview coach, session memory, resume/JD, conversation practice) |
| Auth             | JWT (access + refresh tokens via HTTP-only cookies) — PyJWT                         |
| Validation       | Pydantic v2                                                                         |
| Password hashing | `bcrypt` (cost 12)                                                                  |
| Email            | aiosmtplib (SMTP_HOST/PORT/USER/PASS from env — Brevo SMTP relay)                   |
| LLM              | Groq (`lib/llm_client.py`, OpenAI-compatible `/chat/completions`) — every LLM-backed feature has an offline heuristic fallback when `GROQ_API_KEY` isn't set, so the app (and the test suite) run network-free |
| TTS              | [Piper](https://github.com/OHF-Voice/piper1-gpl) neural voice, local ONNX model (`lib/tts_client.py`) — see `data/tts/README.md` |
| Rate limiting    | `slowapi` (global) + per-conversation-session throttling in `conversation_service.py` |

---

## Project Structure

```
backend/
├── main.py                  # FastAPI app setup + entrypoint, mounts every router below
├── pyproject.toml / uv.lock
│
├── routers/                 # /api/* route definitions — thin, delegate straight to services
│   ├── auth_routes.py             # /api/auth
│   ├── user_routes.py             # /api/users
│   ├── assessment_routes.py       # /api/assessment      (BAS-US: baseline assessment, gating, re-assessment)
│   ├── conversation_routes.py     # /api/conversation     (AIC-US: AI Conversation Practice)
│   ├── coaching_routes.py         # /api/coaching         (WEC-US: Workplace English Coach)
│   ├── interview_coach_routes.py  # /api/interview-coach  (INT-US: mock interviews, peer review sharing)
│   ├── resume_jd_routes.py        # /api/resume-jd-intake (resume/JD intake feeding Interview Coach)
│   ├── session_memory_routes.py   # /api/session-memory   (interruption/resume + cross-session memory, generic across features)
│   ├── pronunciation_routes.py    # /api/pronunciation-coach (US-95: word-level pronunciation feedback)
│   └── accent_routes.py           # /api/accent-assessment  (US-93 passage scoring, US-89 profile + exercises)
│
├── services/                 # Business logic — one module per router above, plus:
│   ├── auth_serivce.py
│   ├── gating_service.py          # feature-access gating (assessment required to unlock most features)
│   ├── reassessment_service.py    # periodic re-assessment cadence/eligibility
│   ├── pronunciation_coach_service.py  # US-95
│   ├── accent_assessment_service.py    # US-93
│   └── accent_profile_service.py       # US-89 — triggered by accent_assessment_service on a COMPLETED assessment
│
├── middlewares/
│   ├── auth_middleware.py   # require_auth / require_admin — FastAPI dependencies
│   └── error_handler.py     # Global exception handlers
│
├── lib/
│   ├── prisma_client.py     # Singleton Prisma() client instance (`db`)
│   ├── kv_store.py          # KvEntry-backed store for the ported features (swapped for an in-memory store in tests)
│   ├── llm_client.py        # Groq chat client
│   ├── ai_client.py         # generate() — llm_client wrapper with an offline fallback
│   ├── prompts.py           # All LLM prompt templates in one place (conversation, interview, workplace coaching)
│   ├── grammar_checker.py   # AIC-US-04 inline grammar correction chip
│   ├── pii.py                # Shared PII detection/redaction (resume intake + conversation practice)
│   ├── tts_client.py         # AIC-US-16 text-to-speech via Piper
│   ├── confidence_engine.py  # Aggregate confidence score (fluency/vocabulary/pronunciation)
│   ├── session_scorer.py     # TEXT vs. AUDIO scoring pipelines shared by assessment/coaching/conversation
│   ├── speech_config.py      # Single source of truth for every Pronunciation Coach/Accent Assessment env value
│   ├── audio_io.py           # Raw upload decoding (PyAV) + RMS/dBFS waveform math
│   ├── vad_engine.py         # Silero VAD — speech segments, silence/incomplete detection, noise/SNR estimate
│   ├── stt_engine.py         # faster-whisper wrapper — transcript + word timings + per-word confidence
│   ├── prosody_engine.py     # praat-parselmouth wrapper — pitch/intensity/syllable-nuclei, multi-voice heuristic
│   ├── text_alignment.py     # difflib target↔transcript word alignment + CMU-dict stress lookup
│   └── recording_engine.py   # Shared Assessment/Recording Engine (US-95/US-93/US-89 foundation) — ties the six above together
│
├── schemas/                  # Pydantic request models, one file per feature
│
├── utils/
│   ├── app_error.py          # AppError class
│   ├── feature_errors.py     # Typed errors (404/400/409/429/413/422) for the ported + pronunciation/accent features
│   ├── jwt_utils.py          # Token sign/verify helpers, cookie option factories, hash_token
│   └── email_utils.py        # send_password_reset_email
│
├── data/
│   ├── assessment_qs.json           # Baseline assessment question bank
│   ├── pronunciation_sentences.json # US-95 target-sentence bank
│   ├── accent_passages.json         # US-93 target-passage bank
│   └── tts/                         # Piper voice model (not committed — see data/tts/README.md)
│
├── tests/                    # pytest — offline/network-free (LLM + kv_store both mocked, see tests/conftest.py)
│
└── prisma/
    ├── schema.prisma         # generator switched to prisma-client-py
    └── migrations/
```

---

## Feature Modules

| Router prefix           | Covers                                                                                          |
| ------------------------ | ------------------------------------------------------------------------------------------------ |
| `/api/auth`, `/api/users`| Signup/login/refresh/logout/password-reset, profile self-service, avatar upload, admin roles     |
| `/api/assessment`        | Initial + periodic baseline assessment, confidence scoring, feature-access gating, skip/re-assessment flows |
| `/api/conversation`      | AI Conversation Practice — preset/custom topics, proficiency-adaptive difficulty, grammar-correction toggle, PII safety, rate-limiting, cross-session memory, transcript review, TTS playback |
| `/api/coaching`          | Workplace English Coach — email/client/meeting/presentation scenarios, roleplay, tone-first grading |
| `/api/interview-coach`   | Mock interviews (standard/panel/case-study/multi-round), peer review sharing                     |
| `/api/resume-jd-intake`  | Resume/CV + job-description upload, PII redaction, resume↔JD mismatch check (feeds Interview Coach) |
| `/api/session-memory`    | Session interruption/auto-resume and cross-session personalization — generic, reused by Conversation Practice and Interview Coach via `session_type` |
| `/api/pronunciation-coach` | US-95 — read-a-sentence-aloud word-level pronunciation feedback (correct/mispronounced/stress-error/skipped), unlimited retries |
| `/api/accent-assessment` | US-93 passage-level rhythm/stress/intonation/clarity/pronunciation scoring + US-89 accent profile & generated practice exercises |

---

## What changed vs. the Express version (and why)

- **`prisma/schema.prisma`**: only the `generator client` block changed, from
  `provider = "prisma-client-js"` to `provider = "prisma-client-py"`. `@map` table names
  stay the same as the original migrations; new models (`CoachingSession`, `KvEntry`, etc.)
  were added on top as later features were ported, each with its own migration.
- **`datasource.url`**: added directly into `schema.prisma` (`url = env("DATABASE_URL")`).
  The original relied on `prisma.config.js` for this (a Prisma 7 JS-only feature);
  prisma-client-py doesn't read that file, so the url has to live in the schema itself.
- **Response shapes** (auth/users slice): kept **exactly** the same as the Express version
  on purpose, since the frontend already expects them:
  - Validation failures → `{"error": {"formErrors": [...], "fieldErrors": {...}}}`, 400
    (Pydantic now validates automatically; the response shape mimics Zod's `.flatten()`).
  - `requireAuth` failures → `{"error": "..."}`, 401 (bypasses the general error handler,
    same as the original — see `middlewares/error_handler.py`'s `AuthError`).
  - Everything else (business-logic failures like "already registered") → `{"error": "..."}`
    with the original status code, same as before.
  - Uncaught/unexpected errors → `{"status": "error", "message": "Something went wrong!"}`, 500.
  - 404 catch-all → `{"status": "fail", "message": "Route not found: ..."}` (same as `app.js`).
  - The features ported later (assessment, coaching, interview coach, resume/JD, session
    memory, conversation) didn't exist in the Express version — their response shapes are
    new, and their domain errors (404/400/409/429) go through `utils/feature_errors.py` on
    top of the same `AppError` mechanism.
- **Login's constant-time dummy hash**: the JS file hardcodes a dummy bcrypt string for
  timing-attack resistance when the user doesn't exist. That exact string isn't a
  structurally valid hash for Python's `bcrypt` package (raises `Invalid salt` instead of
  just failing the comparison) — regenerated an equivalent dummy hash at the same cost
  factor (12) instead. Same property, different literal string.
- **Email TLS**: nodemailer's `secure: false` does _opportunistic_ STARTTLS (upgrade if the
  server offers it, don't require it). The naive Python mapping (`start_tls=True`) actually
  means "require STARTTLS, hard-fail if unsupported" in `aiosmtplib` — fixed to use
  `start_tls=None` (aiosmtplib's own opportunistic default) to match nodemailer's real behavior.
- **`catchAsync`**: dropped — never actually used in the controllers (Express 5 already
  auto-propagates async errors, and so does FastAPI). Nothing lost.

Everything else in the auth/users slice — validation rules, token TTLs, cookie paths/flags,
refresh-token rotation + reuse detection, password-reset one-time-use + expiry checks, the
constant-time login comparison — is a direct line-for-line port.

---

## Environment Variables

See `.env.example` for the full list. In addition to the original auth-slice variables
(`DATABASE_URL`, `JWT_ACCESS_SECRET`, `CLIENT_ORIGIN`, etc.):

> **Dev email**: `SMTP_HOST`/`PORT`/`USER`/`PASS` required — point at Brevo's SMTP relay
> (`smtp-relay.brevo.com:587`). Signup OTP and reset link also log to console when
> `NODE_ENV != production`.

> **LLM (Groq)**: `GROQ_API_KEY` powers Conversation Practice, Interview Coach, and
> Workplace Coach grading/dialogue. Without it, every one of those features falls back to
> a deterministic offline heuristic — the app and the test suite both run fully without it.

> **TTS**: no env var required beyond optionally `TTS_VOICE_MODEL` to pick a different
> voice file name. Needs the model file present at `data/tts/` — see `data/tts/README.md`.
> Without it, `/api/conversation/tts` returns 503 and the client is expected to fall back
> to its own native TTS.

> **Pronunciation Coach / Accent Assessment**: every threshold (STT model/device, audio
> limits, silence/noise/word-confidence/coverage cutoffs, exercise batch size, etc.) has a
> default and lives in `lib/speech_config.py` — see `.env.example`'s dedicated section.
> Nothing in that module is hardcoded.

---

## Getting Started

### 1. Install dependencies

```bash
uv sync
```

### 2. Generate the Prisma Python client

```bash
uv run prisma generate
```

This reads `prisma/schema.prisma` and generates the typed `db.*` client used throughout
`services/*.py`. **Re-run this any time `schema.prisma` changes** — a stale generated
client (e.g. missing a newly added enum) fails at import time for every service that
touches the affected model.

> Added `PronunciationAttempt` / `AccentAssessment` / `AccentProfile`? Generate + apply
> the migration against a running Postgres before starting the server:
> `uv run prisma migrate dev --name add_pronunciation_accent`.

### 3. Set up the database

Tables already exist if you're pointing `DATABASE_URL` at the same DB previous migrations
ran against. Fresh DB:

```bash
uv run prisma migrate deploy
```

### 4. Start the dev server

```bash
uv run python main.py
# or: uv run uvicorn main:app --reload
# → Speeky-AI backend listening on port 8000
```

Health check: `GET http://localhost:8000/health`

Interactive API docs: `http://localhost:8000/docs`

### 5. Run tests

```bash
uv run pytest
```

Fully offline — `tests/conftest.py` forces the LLM offline and swaps the KV store for an
in-process one, so no network or DB connection is needed.

### 6. Voice mode (Conversation / Scenario / Coaching / Interview Coach / Assessment / Public Speaking)

No separate service to run. The browser streams raw 16-bit PCM mic audio straight to
this API over a WebSocket (`GET /api/<feature>/.../voice-ws`); `lib/voice_ws.py`
segments it into utterances with Silero VAD and transcribes each one with
faster-whisper — the same `faster-whisper` / `silero-vad` deps that already power
Pronunciation Coach / Accent Assessment's one-shot recording uploads
(`lib/stt_engine.py`, `lib/vad_engine.py`). The client fills its message input with the
transcript, same "review then hit Send" flow as typing — this API never auto-sends on
the user's behalf.

---

## API Reference

All routes below are prefixed as shown. See `/docs` for full request/response schemas.

### `/api/auth` — Public

| Method | Path               | Body                         | Description                                                         |
| ------ | ------------------ | ----------------------------- | -------------------------------------------------------------------- |
| `POST` | `/signup`          | `{ email, password, name? }` | Register. Sets access + refresh cookies. Returns `{ user }`.        |
| `POST` | `/login`           | `{ email, password }`        | Login. Sets access + refresh cookies. Returns `{ user }`.           |
| `POST` | `/refresh`         | —                             | Rotate refresh token (reads cookie). Returns `{ user }`.            |
| `POST` | `/logout`          | —                             | Revokes refresh token, clears cookies. Returns `204`.               |
| `POST` | `/forgot-password` | `{ email }`                   | Sends reset email. Always returns `200` (no user enumeration).      |
| `POST` | `/reset-password`  | `{ token, password }`        | Resets password, revokes all refresh tokens. Returns `{ message }`. |

### `/api/users` — requires `access_token` cookie

| Method   | Path            | Description                                    |
| -------- | --------------- | ------------------------------------------------ |
| `GET`    | `/me`           | Current user profile.                           |
| `PATCH`  | `/me`           | Update name/email.                              |
| `DELETE` | `/me`           | Delete own account (password-confirmed).        |
| `PATCH`  | `/me/avatar`    | Upload/replace avatar.                          |
| `GET`    | `/`             | Admin: list all users.                          |
| `PATCH`  | `/{id}/role`    | Admin: change a user's role.                    |

### `/api/assessment`

`/start`, `/{id}/respond`, `/{id}/status`, `/{id}/summary`, `/progress`, `/access`,
`/skip`, `/skip/confirm`, `/reassessment/eligibility`, `/reassessment/start`,
`/reassessment/dismiss`.

### `/api/conversation`

`GET /topics`, `GET /topics/validate?topic=...`, `POST /sessions`, `GET /sessions`,
`POST /sessions/{id}/messages`, `POST /sessions/{id}/end`, `GET /sessions/{id}/transcript`,
`GET /memory`, `DELETE /memory/{fact_id}`, `PATCH /memory/opt-out`, `POST /tts`.

### `/api/coaching`

`GET /scenarios`, `POST /start`, `POST /{id}/turn`, `POST /{id}/submit`, `GET /{id}`.

### `/api/interview-coach`

`POST /sessions`, `POST /sessions/{id}/answer`, `POST /sessions/{id}/pause`,
`POST /sessions/{id}/resume`, `POST /sessions/{id}/break`, `POST /sessions/{id}/end`,
`POST /reviews`, `POST /reviews/{share_id}/comments`, `GET /reviews/{share_id}/comments`,
`POST /reviews/{share_id}/revoke`, `POST /reviews/comments/{id}/report`.

### `/api/resume-jd-intake`

`POST /resumes`, `GET /resumes`, `GET /resumes/{id}`, `POST /jds`, `GET /jds/{id}`,
`POST /mismatch-check`.

### `/api/session-memory`

`POST /interruptions`, `GET /interruptions/{session_id}/status`, `POST /resume`,
`POST /profile/record-session`, `GET /profile`, `GET /profile/personalized-opening`.

### `/api/pronunciation-coach` — requires `access_token` cookie

| Method | Path                              | Body                                        | Description |
| ------ | --------------------------------- | -------------------------------------------- | ------------ |
| `GET`  | `/sentences`                      | query: `sentence_id?`, `difficulty?`        | Fetch a specific or random target sentence. |
| `POST` | `/sentences/{sentence_id}/attempts` | multipart: `audio` (file), `accent_profile?` (form field, US-90 stub) | Submit a recording against that sentence. Word-level `correct/mispronounced/stress_error/skipped` results + overall score. Retries **replace** the sentence's stored score (no history). `422` with a `reason` code if the recording fails a quality check. |

### `/api/accent-assessment` — requires `access_token` cookie

| Method | Path                              | Body                     | Description |
| ------ | --------------------------------- | ------------------------- | ------------ |
| `GET`  | `/passages`                       | query: `passage_id?`, `difficulty?` | Fetch a specific or random target passage. |
| `POST` | `/passages/{passage_id}/assessments` | multipart: `audio` (file) | Submit a full-passage recording. Returns 4 separate scores (pronunciation/stress/rhythm/intonation/clarity) + weak points on success. `422` with a `reason` code (`no_speech_detected` / `audio_too_quiet` / `background_noise_too_high` / `incomplete_recording` / `multiple_voices_detected`) instead of a false baseline otherwise. A `COMPLETED` result automatically generates/updates the user's Accent Profile (US-89). |
| `GET`  | `/profile`                        | —                          | Latest Accent Profile (4 scores + weak points). `404` if no assessment has ever completed. |
| `GET`  | `/profile/exercises`              | —                          | Targeted practice sentences generated from the profile's weak points (Groq LLM, deterministic offline fallback). `404` under the same condition as `/profile`. |

---

## Authentication Flow

```
Client                        Server
  │── POST /signup ──────────▶│ hash password, create user
  │◀── Set-Cookie: access_token, refresh_token ──│
  │
  │── GET /me (cookie auto-sent) ──▶│ require_auth dependency verifies access_token
  │◀── { user } ────────────────────│
  │
  │── POST /refresh ─────────▶│ verify refresh_token, rotate (revoke old, issue new)
  │◀── Set-Cookie (new tokens) ──────│
  │
  │── POST /logout ──────────▶│ revoke refresh_token, clear cookies
  │◀── 204 ──────────────────────────│
```

### Token details

| Token           | Storage                            | TTL                   | Purpose                   |
| --------------- | ----------------------------------- | ---------------------- | --------------------------- |
| `access_token`  | HTTP-only cookie, `path=/`         | 30 min (configurable) | Authenticate API requests |
| `refresh_token` | HTTP-only cookie, `path=/api/auth` | 7 days (configurable) | Obtain new access tokens  |

- Refresh tokens are **hashed (SHA-256)** before DB storage — raw token never persisted.
- **Token rotation** on every refresh — old token immediately revoked.
- **Reuse detection** — if a revoked refresh token is presented, all tokens for that user are revoked.

---

## Data Models

See `prisma/schema.prisma`: `User`, `RefreshToken`, `PasswordResetToken`,
`BaselineAssessment`, `ReassessmentRequest`, `PromptLog`, `CoachingSession`, and the
generic `KvEntry` table backing the kv_store-based features (Interview Coach, Session &
Memory, Resume/JD Intake, Conversation Practice).

Pronunciation Coach / Accent Assessment add three more: `PronunciationAttempt` (one row
per `userId`+`sentenceId`, updated in place on retry), `AccentAssessment` (one row per
passage-reading attempt, history kept — `REJECTED_*` statuses carry no scores), and
`AccentProfile` (generated from a `COMPLETED` `AccentAssessment`; history kept, latest
is canonical).

---

## Error Handling

`AppError(message, status_code)` and its typed subclasses in `utils/feature_errors.py`
(`SessionNotFoundError` → 404, `InvalidSubmissionError` → 400, `SessionAlreadyEndedError`
→ 409, `RateLimitedError` → 429) all render through the same handler
(`middlewares/error_handler.py`'s `app_error_handler`). `requireAuth` failures bypass it
(`AuthError`, its own 401 shape). Everything else uncaught → 500 generic message.

Pronunciation Coach / Accent Assessment add `UnreadableAudioError` (400 — corrupt/empty
upload), `UploadTooLargeError` (413), `SentenceNotFoundError`/`PassageNotFoundError` (404),
and `NoCompletedAssessmentError` (404 — profile/exercises requested before any assessment
completed). A recording that's readable but fails a *quality* check (silence, too quiet,
too noisy, incomplete, multiple voices) is **not** one of these exceptions — it's a normal
`422` JSON response with a `reason` code (see `lib/recording_engine.RejectionReason`),
since it's an expected outcome the client needs to branch on, not a server error.

---

## Security Notes

- All JWT secrets must be at least 256-bit random hex.
- `access_token` cookie has `path=/`; `refresh_token` has `path=/api/auth`.
- Both cookies are `httponly`, `secure` (in production), `samesite=none` (prod) / `lax` (dev).
- Login uses constant-time bcrypt comparison even when the user doesn't exist.
- Forgot-password always returns 200 regardless of whether the email exists.
- Password reset tokens are hashed in DB (never stored raw).
- On password reset, all existing refresh tokens are revoked.
- PII (phone/email/national ID/card numbers) is redacted before it ever reaches an LLM or
  long-term storage in both the resume/JD intake and Conversation Practice flows (`lib/pii.py`).

**Before this goes anywhere near production**: rotate `JWT_ACCESS_SECRET` /
`JWT_REFRESH_SECRET` and the `DATABASE_URL` credentials in `.env` — they were carried
over as-is from the JS backend's `.env` for a zero-friction drop-in, but that means
they're now sitting in two places.
