"""Per-room dispatch: parses feature + session id out of the LiveKit room name (minted
by services/live_call_service.py) and builds everything worker.py needs to start an
AgentSession for that specific call. Live Call is scoped to free-flowing chat features
only — conversation / interview_coach / scenario / coaching (roleplay scenarios only) —
deliberately not the assessment/scoring exercises (pronunciation coach, accent
assessment, coaching's draft-and-grade scenarios) where a scripted read-and-score flow
doesn't fit a live back-and-forth call.

Public Speaking is a partial exception, and the distinction is worth stating: the SPEECH is a
monologue and gets no *conversational* agent at all — a live participant would talk over the
speaker and its voice would be transcribed into the audio being scored. The Q&A that follows
genuinely is back-and-forth, so that phase alone gets the talking avatar.
services/live_call_service.py enforces it by refusing to mint a "qa" token until the session
reaches "qa_phase".

The speech phase does get one thing: an "idle" avatar, a silent stand-in for an audience member
to speak to. It is a separate mode, not a loosening of the above — worker.py starts it with no
STT, LLM or TTS whatsoever, so the reasons the Q&A gate exists simply do not apply to it. That
mode is allowed only while the session is still "in_progress" (build_idle_setup below), which is
the exact inverse of the qa_phase window.
"""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi.responses import JSONResponse

from lib import ai_client, llm_client, prompts, relevance
from lib.prisma_client import db
from schemas.coaching_schemas import RoleplayTurnSchema
from schemas.conversation_schemas import SendMessageSchema
from schemas.interview_coach_schemas import AnswerRequest
from schemas.scenario_schemas import ScenarioTurnSchema
from services import coaching_service, conversation_service, interview_coach_service, scenario_service
from utils.feature_errors import SessionNotFoundError

_FEATURES = ("conversation", "interview_coach", "scenario", "coaching")
from schemas.public_speaking_schemas import QAResponseSchema
from schemas.scenario_schemas import ScenarioTurnSchema
from services import (
    coaching_service,
    conversation_service,
    interview_coach_service,
    public_speaking_service,
    scenario_service,
)
from utils.feature_errors import SessionNotFoundError

logger = logging.getLogger("live-call-agent")

_FEATURES = ("conversation", "interview_coach", "scenario", "coaching", "public_speaking")


@dataclass
class LiveCallSetup:
    instructions: str
    opening_line: str
    turn_handler: Callable[[str], Awaitable[str]]
    opening_is_essential: bool = False
    """Whether the caller must hear the opening line for the call to make any sense.

    False for the chat features, where it is a greeting: if the caller is already talking when
    the agent connects, their utterance is the better first turn and the greeting is dropped.
    True for Public Speaking, where the opening line is the *question* — an answer to a question
    that was never asked is not a Q&A, so it is spoken unconditionally and uninterruptibly.
    """


@dataclass
class IdleAvatarSetup:
    """Deliberately not a LiveCallSetup: no turn_handler, no opening_line, nothing to say.

    The absence of those fields is the point — there is no callable here for a later refactor
    to wire an LLM into by accident, which is what would put a talking agent back into the
    speech phase.
    """

    instructions: str


def parse_room_name(room_name: str) -> tuple[str, str, str]:
    """"livecall_{feature}_{session_id}_{nonce}", or
    "livecall_public_speaking_{mode}_{session_id}_{nonce}" (services/live_call_service.py).
    Returns (feature, mode, session_id).

    Matched against the known feature list rather than a blind split — "interview_coach" and
    "public_speaking" contain underscores themselves, so a plain split(_, 2) would cut the
    feature name in the wrong place. Only public_speaking carries a mode segment; everything
    else is conversational by definition, so it reports "qa".

    The trailing "_{nonce}" (a per-mint-attempt random suffix, added so a re-opened Live Call
    always lands in a brand-new LiveKit room and reliably gets a fresh agent dispatch — see
    live_call_service._mint_token) is stripped first and otherwise ignored; the worker has no
    use for it beyond that.
    """
    body = room_name.removeprefix("livecall_").rsplit("_", 1)[0]
    for feature in _FEATURES:
        prefix = f"{feature}_"
        if not body.startswith(prefix):
            continue
        rest = body[len(prefix):]
        if feature == "public_speaking":
            for mode in ("qa", "idle"):
                mode_prefix = f"{mode}_"
                if rest.startswith(mode_prefix):
                    return feature, mode, rest[len(mode_prefix):]
            raise ValueError(f"Public speaking room name carries no mode: {room_name!r}")
        return feature, "qa", rest
    raise ValueError(f"Unrecognized Live Call room name: {room_name!r}")


async def build_idle_setup(session_id: str, user_id: str) -> IdleAvatarSetup:
    """The silent audience avatar shown during the speech itself.

    Re-checks the phase even though live_call_service already did at token-mint time, matching
    what _build_public_speaking_setup does for the Q&A side — the worker trusts the room name,
    so the phase is worth confirming against the database once more here.
    """
    session = await public_speaking_service.get_session(session_id, user_id)
    if session.get("status") != "in_progress":
        raise SessionNotFoundError(
            f"Public speaking session {session_id} is not in the speech phase"
        )
    return IdleAvatarSetup(
        instructions="You are a silent audience member. You never speak.",
    )


async def build_setup(feature: str, session_id: str, user_id: str) -> LiveCallSetup:
    if feature == "conversation":
        return await _build_conversation_setup(session_id, user_id)
    if feature == "interview_coach":
        return await _build_interview_coach_setup(session_id, user_id)
    if feature == "scenario":
        return await _build_scenario_setup(session_id, user_id)
    if feature == "coaching":
        return await _build_coaching_setup(session_id, user_id)
    if feature == "public_speaking":
        return await _build_public_speaking_setup(session_id, user_id)
    raise NotImplementedError(f"Live Call not wired up yet for feature={feature!r}")


async def _build_conversation_setup(session_id: str, user_id: str) -> LiveCallSetup:
    session = await conversation_service._get_session(session_id, user_id)
    instructions = conversation_service._build_system_prompt(session)
    opening_line = await ai_client.generate(
        system_prompt=instructions,
        user_message=(
            "Greet the caller warmly in one short sentence, like you just answered a "
            "phone call, and invite them to start talking about this topic."
        ),
        max_tokens=60,
    )

    async def turn_handler(user_text: str) -> str:
        # Same function a typed or push-to-talk turn already goes through — safety
        # checks, prompt-building, and turn persistence all happen inside it, so a Live
        # Call turn lands in the session's normal history exactly like any other input
        # mode. This is also what makes "End Call" (as opposed to "End Session") a no-op
        # on the backend: nothing extra needs to be flushed, every turn already persisted
        # as it happened.
        req = SendMessageSchema(text=user_text, input_mode="audio")
        result = await conversation_service._send_message(user_id, session_id, req)
        return result["reply"]

    return LiveCallSetup(instructions=instructions, opening_line=opening_line, turn_handler=turn_handler)


async def _build_interview_coach_setup(session_id: str, user_id: str) -> LiveCallSetup:
    session = await interview_coach_service._get_session(session_id, user_id)
    # Interview Coach builds its system prompt fresh per-turn inside _submit_answer's
    # own call chain (_generate_next_question etc, keyed off live round/persona state) —
    # there's no single static session-level prompt the way Conversation has one.
    # `instructions` here is framework bookkeeping only; turn_handler below never reads
    # it, so it doesn't need to (and can't cheaply) mirror that per-turn logic.
    instructions = f"You are conducting {interview_coach_service._persona_description(session)}."
    exchanges = session["exchanges"]
    # _start_session always seeds exchanges[0] with the opening question — the caller
    # either hasn't answered it yet (fresh join) or has (re-joining mid-interview via
    # Live Call after some text turns); either way it's the last thing the AI said,
    # which is the natural thing to speak first on connect.
    opening_line = exchanges[-1]["question"] if exchanges else "Let's begin — tell me about yourself."

    async def turn_handler(user_text: str) -> str:
        req = AnswerRequest(answer_text=user_text)
        result = await interview_coach_service._submit_answer(user_id, session_id, req)
        return result.next_question or "That wraps up this interview — great work today."

    return LiveCallSetup(instructions=instructions, opening_line=opening_line, turn_handler=turn_handler)


async def _build_scenario_setup(session_id: str, user_id: str) -> LiveCallSetup:
    row = await db.scenariosession.find_unique(where={"id": session_id})
    if not row or row.userId != user_id:
        raise SessionNotFoundError(f"Scenario session {session_id} not found")

    # CM-US-04: meta frozen at start_session (matches send_turn's own rule — an admin
    # edit mid-conversation must not change this session's persona/prompt/rules).
    meta = row.scenarioMeta or await scenario_service.scenario_meta(row.scenarioKey)
    instructions = prompts.build_scenario_roleplay_prompt(meta)
    # turns always ends on an assistant line (start_session seeds turns[0] with the
    # opening; send_turn only ever returns after appending its own reply) — that's
    # exactly what should be spoken first on connect, same reasoning as Interview Coach.
    opening_line = row.turns[-1]["content"] if row.turns else meta.get("opening_fallback", "Let's begin.")

    async def turn_handler(user_text: str) -> str:
        result = await scenario_service.send_turn(session_id, ScenarioTurnSchema(message=user_text), user_id)
        if isinstance(result, JSONResponse):
            return "Sorry, something went wrong there — let's try again."
        return result["reply"]

    return LiveCallSetup(instructions=instructions, opening_line=opening_line, turn_handler=turn_handler)


async def _build_coaching_setup(session_id: str, user_id: str) -> LiveCallSetup:
    row = await db.coachingsession.find_unique(where={"id": session_id})
    if not row or row.userId != user_id:
        raise SessionNotFoundError(f"Coaching session {session_id} not found")

    # Only client_communication/meeting_communication are roleplay=True (interactive,
    # multi-turn) — the other scenarios (email_writing, presentation_prep,
    # general_workplace) are single-submission draft-and-grade, no turns to call into.
    scenario_key = coaching_service.SCENARIO_ENUM_TO_KEY[row.scenario]
    meta = coaching_service.scenario_meta(scenario_key)
    if not meta or not meta["roleplay"]:
        raise SessionNotFoundError(f"Coaching session {session_id} is not an interactive roleplay")

    instructions = prompts.build_workplace_roleplay_prompt(scenario_key, row.promptText)
    # start_session doesn't persist its opening_message into turns (only returns it),
    # so a fresh join regenerates one the same way; a mid-conversation join speaks the
    # last thing the AI said, same reasoning as Scenario/Interview Coach above.
    turns = list(row.turns)
    opening_line = (
        turns[-1]["content"] if turns
        else await coaching_service._roleplay_opening(scenario_key, row.promptText)
    )

    async def turn_handler(user_text: str) -> str:
        result = await coaching_service.roleplay_turn(session_id, RoleplayTurnSchema(message=user_text), user_id)
        if isinstance(result, JSONResponse):
            return "Sorry, something went wrong there — let's try again."
        return result["reply"]

    return LiveCallSetup(instructions=instructions, opening_line=opening_line, turn_handler=turn_handler)


async def _answers_the_question(question: str, answer: str) -> bool:
    """Whether `answer` is on the subject `question` asked — not whether it is a *good* answer.

    relevance.evaluate_substance cannot do this: it is a deterministic offline check for whether
    there is any substance at all, so a fluent reply on the wrong topic passes it cleanly. Topic
    drift needs the model.

    Fails open on every error, and when no LLM is configured. Being wrongly told "that doesn't
    answer my question" and asked again is worse than an off-topic answer reaching the scorer,
    which evaluates relevance properly anyway.
    """
    if not llm_client.is_configured():
        return True
    try:
        verdict = await ai_client.generate(
            system_prompt=(
                "You judge whether a spoken answer is about the subject the question asked "
                "about. Ignore quality, length, hesitation and delivery — a rambling or weak "
                "answer on the right subject still counts. Answer with exactly one word: YES if "
                "it addresses the question's subject, NO if it is about something else."
            ),
            user_message=f"Question: {question}\n\nAnswer: {answer}",
            max_tokens=5,
            temperature=0.0,
        )
        return not verdict.strip().upper().startswith("NO")
    except Exception:
        logger.exception("Q&A topicality check failed; treating the answer as on-topic")
        return True


async def _build_public_speaking_setup(session_id: str, user_id: str) -> LiveCallSetup:
    """Q&A only — see the module docstring for why the speech itself gets no agent.

    The question was already generated and persisted when the speech was submitted (submit_turn
    flips the row to "qa_phase" and stores aiQuestion), so the avatar speaks that rather than
    inventing a new one. Two reasons that matters: the user has already seen it on the results
    screen, and it was generated against the full transcript, which the agent does not carry.
    """
    session = await public_speaking_service.get_session(session_id, user_id)
    if session.get("status") != "qa_phase":
        raise SessionNotFoundError(
            f"Public speaking session {session_id} is not in the Q&A phase"
        )

    speech_type = str(session.get("speech_type") or "business_pitch")
    config = public_speaking_service.SPEECH_TYPES.get(
        speech_type, public_speaking_service.SPEECH_TYPES["business_pitch"]
    )
    label = config.get("label", "a speech")

    instructions = (
        f"You are an audience member who has just listened to {label}. "
        "Ask your question, listen to the answer, and respond briefly and naturally — one or two "
        "sentences. Stay in character as a listener, not a coach: do not grade the answer, score "
        "it, or list what they should have done. The written feedback covers that."
    )

    opening_line = session.get("ai_question") or "Thanks for that — what would you say is your main takeaway?"

    # A caller who answers a different question than the one asked gets it put to them again
    # rather than scored and shown the door. Capped, because an audience member that will not
    # move on is its own kind of broken — and submit_qa_response is what ends the session, so
    # someone who never satisfies the gate must still be able to finish.
    max_reasks = 2
    reasks_used = 0

    async def turn_handler(user_text: str) -> str:
        nonlocal reasks_used

        # Two different failures, both worth a re-ask before anything is persisted: nothing of
        # substance said at all (the deterministic gate the typed path also scores against), and
        # a fluent answer to a different question (which that gate passes — it does not read for
        # topic). Being asked again is worth more to a speaker than a relevance score of 0 they
        # read about afterwards.
        if reasks_used < max_reasks:
            no_substance = relevance.evaluate_substance(user_text, opening_line).rejected
            if no_substance or not await _answers_the_question(opening_line, user_text):
                reasks_used += 1
                return f"That doesn't answer what I asked. Let me put it to you again: {opening_line}"

        # submit_qa_response scores the answer AND completes the session — Public Speaking's Q&A
        # is a single exchange by design. So this handler runs at most once per call, and what
        # it returns is a sign-off rather than a follow-up question.
        try:
            await public_speaking_service.submit_qa_response(
                session_id, user_id, QAResponseSchema(text_content=user_text)
            )
        except Exception:
            # The user has already spoken; failing the call now would lose their answer with no
            # way to retry. Persisting is best-effort, closing gracefully is not.
            return "Thanks — that's all from me. Hang up and your written feedback will be there."
        # Says what actually happens next: the call is over and ending it is what reveals the
        # scored feedback. The old wording pointed at a screen the caller was not looking at —
        # the results are behind this call, not beside it.
        return "Thank you, that answers it. Hang up whenever you're ready and I'll show you your feedback."

    return LiveCallSetup(
        instructions=instructions,
        opening_line=opening_line,
        turn_handler=turn_handler,
        # The opening line here is the question itself.
        opening_is_essential=True,
    )
