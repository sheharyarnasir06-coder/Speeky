"""AI Conversation Practice (services/conversation_service) — AIC-US-01..16.

Pure-logic + offline-fallback coverage, same style as test_coaching.py: LLM forced
offline via conftest, kv_store swapped for an in-process store. DB-touching paths
(_resolve_level reads BaselineAssessment) are exercised indirectly through the
default-level fallback (E-01: no baseline on file), which needs no DB at all since
prisma_client.db.baselineassessment.find_first would require a real connection —
so this suite monkeypatches db access where a session needs to exist already.
"""

import pytest

from lib import grammar_checker, kv_store, llm_client, pii, prompts, tts_client
from middlewares.error_handler import AuthError
from schemas.coaching_schemas import AudioFeaturesSchema
from services import conversation_service as cvs


@pytest.fixture(autouse=True)
def _no_baseline_lookup(monkeypatch):
    """_start_session resolves proficiency level from BaselineAssessment (E-01: falls
    back to 'intermediate' when none exists) — that DB read needs a live connection this
    suite doesn't have. Every other service test file avoids calling DB-touching
    controllers at all (see test_coaching.py); here the DB call is one line inside an
    otherwise pure orchestration function, so it's stubbed instead of skipping the
    whole start/send/end flow."""

    async def fake_resolve_level(user_id, level_override):
        if level_override:
            return level_override.lower(), "override", None
        return "intermediate", "default", None

    monkeypatch.setattr(cvs, "_resolve_level", fake_resolve_level)


# ── AIC-US-01: custom topic validation (offline path) ──────────────────────────
async def test_validate_topic_offline_routes_preset_match():
    result = await cvs.validate_topic("Travel")
    assert result["verdict"] == "safe"
    assert result["preset_match"] == "travel"


async def test_validate_topic_offline_vague_short():
    result = await cvs.validate_topic("st")
    assert result["verdict"] == "vague"


async def test_validate_topic_offline_accepts_novel_topic():
    result = await cvs.validate_topic("My favorite video games")
    assert result["verdict"] == "safe"
    assert result["preset_match"] is None


# ── AIC-US-03: level resolution + rolling adjustment ────────────────────────────
def test_level_map_covers_all_learning_levels():
    from prisma.enums import LearningLevel

    for level in LearningLevel:
        assert cvs._LEVEL_MAP[level] in prompts.VALID_LEVELS


async def test_level_adjustment_needs_full_window_and_configured_llm():
    session = {"level": "beginner", "level_locked": False, "recent_user_texts": ["hi", "ok"]}
    await cvs._maybe_adjust_level(session)
    assert session["level"] == "beginner"  # window not full yet, untouched


async def test_level_adjustment_locks_after_one_change(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)

    async def fake_generate(system_prompt, user_message="", **kw):
        return "Advanced"

    monkeypatch.setattr(cvs.ai_client, "generate", fake_generate)
    session = {"level": "beginner", "level_locked": False,
               "recent_user_texts": ["one", "two", "three"]}
    await cvs._maybe_adjust_level(session)
    assert session["level"] == "advanced"
    assert session["level_locked"] is True

    # E-04: locked for the rest of the session, no further changes even with new data.
    session["recent_user_texts"].append("four")
    await cvs._maybe_adjust_level(session)
    assert session["level"] == "advanced"


# ── AIC-US-04: grammar chip ──────────────────────────────────────────────────────
async def test_grammar_chip_off_by_default():
    result = await grammar_checker.get_correction_chip("i has a apple", show_corrections=False, is_voice_mode=False)
    assert result["chip"] is None
    assert result["suppressed_reason"] == "toggle_off"


async def test_grammar_chip_suppressed_in_voice_mode(monkeypatch):
    monkeypatch.setattr(llm_client, "is_configured", lambda: True)

    async def fake_chat(messages, **kw):
        return "I have an apple"

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    result = await grammar_checker.get_correction_chip("i has a apple", show_corrections=True, is_voice_mode=True)
    assert result["chip"] is None
    assert result["suppressed_reason"] == "voice_mode"


async def test_grammar_chip_offline_has_no_correction():
    result = await grammar_checker.get_correction_chip("i has a apple", show_corrections=True, is_voice_mode=False)
    assert result["chip"] is None
    assert result["suppressed_reason"] == "no_correction_needed"


def test_pick_chip_caps_to_single_highest_impact():
    chip = grammar_checker.pick_chip("i has a apple and i seen it", "I have an apple and I saw it")
    assert chip is not None
    assert "from" in chip and "to" in chip


# ── AIC-US-06: memory facts ──────────────────────────────────────────────────────
async def test_memory_defaults_empty_and_not_opted_out():
    memory = await cvs._get_memory("user-1")
    assert memory["facts"] == []
    assert memory["opted_out"] is False


async def test_memory_opt_out_purges_facts():
    await kv_store.store.create(cvs.MEMORY_NS, "user-1", {
        "user_id": "user-1", "opted_out": False,
        "facts": [{"fact_id": "f1", "category": "job", "value": "nurse"}],
    })
    result = await cvs._set_memory_opt_out("user-1", True)
    assert result["opted_out"] is True
    assert result["facts"] == []


async def test_extract_facts_noop_when_opted_out():
    await kv_store.store.create(cvs.MEMORY_NS, "user-1", {"user_id": "user-1", "opted_out": True, "facts": []})
    facts = await cvs._extract_and_store_facts("user-1", ["I work as a nurse"])
    assert facts == []


async def test_extract_facts_noop_when_llm_unconfigured():
    facts = await cvs._extract_and_store_facts("user-2", ["I work as a nurse"])
    assert facts == []  # llm_client.is_configured() is False offline


def test_memory_callback_note_caps_at_two_facts():
    memory = {"facts": [
        {"category": "job", "value": "nurse"},
        {"category": "hobby", "value": "chess"},
        {"category": "goal", "value": "get promoted"},
    ]}
    note = cvs._memory_callback_note(memory)
    assert "get promoted" in note  # most recent two only
    assert "nurse" not in note


# ── AIC-US-07: PII redaction ──────────────────────────────────────────────────────
def test_pii_redacts_email_and_phone():
    redacted, types = pii.redact("Call me at 555-123-4567 or email me at test@example.com")
    assert "[REDACTED]" in redacted
    assert "phone_number" in types
    assert "email" in types
    assert "555-123-4567" not in redacted


def test_pii_no_redaction_for_clean_text():
    redacted, types = pii.redact("I love hiking on weekends")
    assert types == []
    assert redacted == "I love hiking on weekends"


# ── AIC-US-08: abuse / rate-limit / gibberish ─────────────────────────────────────
def test_rate_limit_trips_after_threshold():
    session = {"message_timestamps": [cvs.time.time()] * (cvs.RATE_LIMIT_MAX_MESSAGES)}
    with pytest.raises(cvs.RateLimitedError):
        cvs._check_rate_limit(session)


def test_rate_limit_allows_normal_pace():
    session = {"message_timestamps": []}
    for _ in range(3):
        cvs._check_rate_limit(session)  # should not raise


def test_gibberish_detects_repetitive_chars():
    assert cvs._looks_like_gibberish("aaaaaaaaaa") is True


def test_gibberish_ignores_normal_text():
    assert cvs._looks_like_gibberish("I went to the market yesterday") is False


# ── End-to-end (offline LLM, in-memory kv_store) ──────────────────────────────────
async def test_start_and_send_message_offline_preset_topic():
    session = await cvs._start_session("user-3", cvs.StartConversationSchema(topic_key="daily_life"))
    assert session["topic_key"] == "daily_life"
    assert session["level"] == "intermediate"  # E-01: no baseline -> default
    assert session["opening_message"]

    reply = await cvs._send_message(
        "user-3", session["session_id"], cvs.SendMessageSchema(text="I like reading books"),
    )
    assert reply["reply"]
    assert reply["session_ended"] is False


async def test_start_session_rejects_unsafe_custom_topic(monkeypatch):
    async def fake_validate(topic):
        return {"verdict": "unsafe", "preset_match": None, "reason": "unsafe"}

    monkeypatch.setattr(cvs, "validate_topic", fake_validate)
    with pytest.raises(cvs.InvalidSubmissionError):
        await cvs._start_session("user-4", cvs.StartConversationSchema(custom_topic="something bad"))


async def test_custom_topic_matching_preset_routes_silently(monkeypatch):
    async def fake_validate(topic):
        return {"verdict": "safe", "preset_match": "travel", "reason": "matches"}

    monkeypatch.setattr(cvs, "validate_topic", fake_validate)
    session = await cvs._start_session("user-5", cvs.StartConversationSchema(custom_topic="Travel"))
    assert session["topic_key"] == "travel"


async def test_gibberish_strikes_end_session():
    session = await cvs._start_session("user-6", cvs.StartConversationSchema(topic_key="work"))
    session_id = session["session_id"]
    for _ in range(cvs.GIBBERISH_STRIKE_LIMIT):
        reply = await cvs._send_message("user-6", session_id, cvs.SendMessageSchema(text="aaaaaaaaaa"))
    assert reply["session_ended"] is True

    with pytest.raises(cvs.InvalidSubmissionError):
        await cvs._send_message("user-6", session_id, cvs.SendMessageSchema(text="hello again"))


async def test_pii_redacted_before_storage():
    session = await cvs._start_session("user-7", cvs.StartConversationSchema(topic_key="work"))
    reply = await cvs._send_message(
        "user-7", session["session_id"],
        cvs.SendMessageSchema(text="my email is secret@example.com and I like my job"),
    )
    assert "pii_redacted" in reply["flags"]
    stored = await kv_store.store.get(cvs.NAMESPACE, session["session_id"])
    user_turns = [t for t in stored["turns"] if t["role"] == "user"]
    assert "secret@example.com" not in user_turns[-1]["content"]


async def test_end_session_scores_and_marks_completed():
    session = await cvs._start_session("user-8", cvs.StartConversationSchema(topic_key="daily_life"))
    await cvs._send_message("user-8", session["session_id"],
                            cvs.SendMessageSchema(text="I usually read books and go for long walks on weekends"))
    feedback = await cvs._end_session("user-8", session["session_id"])
    assert feedback["status"] == "completed"
    assert feedback["fluency_score"] >= 0

    with pytest.raises(cvs.InvalidSubmissionError):
        await cvs._end_session("user-8", session["session_id"])


async def test_list_sessions_scoped_to_user():
    await cvs._start_session("user-9", cvs.StartConversationSchema(topic_key="travel"))
    await cvs._start_session("user-10", cvs.StartConversationSchema(topic_key="travel"))
    mine = await cvs._list_sessions("user-9")
    assert len(mine) == 1


async def test_transcript_reflects_turns():
    session = await cvs._start_session("user-11", cvs.StartConversationSchema(topic_key="education"))
    await cvs._send_message("user-11", session["session_id"], cvs.SendMessageSchema(text="Math was my favorite"))
    transcript = await cvs._get_transcript("user-11", session["session_id"])
    assert transcript["status"] == "active"
    assert len(transcript["turns"]) >= 3  # opening + user + AI reply


# ── AIC-US-16: TTS ───────────────────────────────────────────────────────────────
def test_tts_not_configured_when_model_missing(monkeypatch):
    monkeypatch.setattr(tts_client, "PiperVoice", None)
    assert tts_client.is_configured() is False


# Voice mode moved from LiveKit token-minting to a WebSocket transport
# (backend/lib/voice_ws.py, served via conversation_service's websocket route) in a
# later merge — LiveKit was dropped as a dependency, and services.conversation_service
# no longer exposes _voice_token. The old token-minting tests above went with it;
# no equivalent unit test exists yet for the WebSocket path (it's endpoint-level,
# not a plain async function this test style can call directly).


async def test_agent_send_message_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_AGENT_SECRET", "correct-secret")
    with pytest.raises(AuthError):
        await cvs._agent_send_message("some-session", cvs.SendMessageSchema(text="hi"), "wrong-secret")


async def test_agent_send_message_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("INTERNAL_AGENT_SECRET", raising=False)
    with pytest.raises(AuthError):
        await cvs._agent_send_message("some-session", cvs.SendMessageSchema(text="hi"), None)


async def test_agent_send_message_feeds_audio_pipeline(monkeypatch):
    monkeypatch.setenv("INTERNAL_AGENT_SECRET", "correct-secret")
    session = await cvs._start_session("user-15", cvs.StartConversationSchema(topic_key="daily_life"))
    session_id = session["session_id"]

    payload = cvs.SendMessageSchema(
        input_mode="audio",
        audio_features=AudioFeaturesSchema(
            transcript="I usually read books and go for long walks on weekends",
            duration_seconds=6.0,
        ),
    )
    reply = await cvs._agent_send_message(session_id, payload, "correct-secret")
    assert reply["reply"]

    feedback = await cvs._end_session("user-15", session_id)
    assert feedback["status"] == "completed"
    assert feedback["pronunciation_score"] is not None  # AUDIO pipeline ran, not TEXT


async def test_send_message_stores_audio_turn_timing(monkeypatch):
    """duration_seconds/word_timings from the agent's AudioFeaturesSchema must survive
    onto the stored turn — _end_session's scoring aggregation reads them from there."""
    monkeypatch.setenv("INTERNAL_AGENT_SECRET", "correct-secret")
    session = await cvs._start_session("user-16", cvs.StartConversationSchema(topic_key="daily_life"))
    session_id = session["session_id"]

    payload = cvs.SendMessageSchema(
        input_mode="audio",
        audio_features=AudioFeaturesSchema(
            transcript="hello world", duration_seconds=1.2,
            word_timings=[
                {"word": "hello", "start": 0.0, "end": 0.4},
                {"word": "world", "start": 0.7, "end": 1.1},
            ],
        ),
    )
    await cvs._agent_send_message(session_id, payload, "correct-secret")

    stored = await kv_store.store.get(cvs.NAMESPACE, session_id)
    user_turn = next(t for t in stored["turns"] if t["role"] == "user")
    assert user_turn["duration_seconds"] == 1.2
    assert user_turn["word_timings"] == payload.audio_features.word_timings


def test_aggregate_audio_turns_derives_per_turn_timing():
    """aggregate_audio_turns must derive speech_rate/pause_count per turn, not by
    concatenating word_timings across turns (a turn boundary includes the AI's reply,
    so gluing raw timings would count that gap as user pause time)."""
    from lib.session_scorer import AudioFeatures, aggregate_audio_turns

    turn1 = AudioFeatures(
        transcript="hello world", duration_seconds=1.2,
        word_timings=[{"word": "hello", "start": 0.0, "end": 0.4}, {"word": "world", "start": 0.7, "end": 1.1}],
    )
    turn2 = AudioFeatures(
        transcript="foo bar", duration_seconds=0.8,
        word_timings=[{"word": "foo", "start": 0.0, "end": 0.3}, {"word": "bar", "start": 0.35, "end": 0.6}],
    )

    result = aggregate_audio_turns([turn1, turn2])

    assert result.transcript == "hello world foo bar"
    assert result.duration_seconds == pytest.approx(2.0)
    assert result.pause_count == 1  # only turn1's 0.3s gap clears the 0.2s threshold
    assert result.mean_pause_duration == pytest.approx(0.3)
    assert result.speech_rate == pytest.approx(2.0)  # 4 words / 2.0s combined duration
