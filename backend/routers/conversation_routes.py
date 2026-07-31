from fastapi import APIRouter

from services.conversation_service import (
    agent_send_message,
    check_topic,
    delete_memory_fact,
    end_session,
    get_transcript,
    list_memory_facts,
    list_sessions,
    list_topics,
    send_message,
    set_memory_opt_out,
    start_session,
    text_to_speech,
    voice_socket,
)

router = APIRouter()

# AI Conversation Practice
router.add_api_route("/topics", list_topics, methods=["GET"])
router.add_api_route("/topics/validate", check_topic, methods=["GET"])
router.add_api_route("/sessions", start_session, methods=["POST"], status_code=201)
router.add_api_route("/sessions", list_sessions, methods=["GET"])
router.add_api_route("/sessions/{session_id}/messages", send_message, methods=["POST"])
router.add_api_route("/sessions/{session_id}/end", end_session, methods=["POST"])
router.add_api_route("/sessions/{session_id}/transcript", get_transcript, methods=["GET"])  # AIC-US-02

# Voice mode: WebSocket transport straight to this backend (backend/lib/voice_ws.py)
router.add_api_websocket_route("/sessions/{session_id}/voice-ws", voice_socket)
router.add_api_route("/internal/sessions/{session_id}/agent-message", agent_send_message, methods=["POST"])

# cross-session personalization memory
router.add_api_route("/memory", list_memory_facts, methods=["GET"])
router.add_api_route("/memory/{fact_id}", delete_memory_fact, methods=["DELETE"])
router.add_api_route("/memory/opt-out", set_memory_opt_out, methods=["PATCH"])

# TTS playback
router.add_api_route("/tts", text_to_speech, methods=["POST"])
