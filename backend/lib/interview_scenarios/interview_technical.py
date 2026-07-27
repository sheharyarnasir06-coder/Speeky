"""
Technical Interview Simulation (US-49 / PDF US-024 / INT-US-11).

DEPLOYMENT-FRIENDLY / NO LOCAL DOWNLOAD: this module loads no model of
its own. All dynamic judgment (question generation, role validation,
code-dictation detection, logic/clarity evaluation) is delegated to an
INJECTED ask_llm(prompt: str, context_type: str) -> str callable — the
same shape pipeline.py's ConversationEngine.generate_response() already
uses. Deterministic parts (silence timing, word-count checks) are plain
Python, no LLM, no hardcoded question content.

REAL BLOCKER, same as before: I don't have response.py's source beyond
that one verified method shape. Whether ConversationEngine can accept a
custom system/persona prompt (needed here — "you are a technical
interviewer" isn't just a context_type string) is unknown. ask_llm is
injected so whoever wires this in supplies the real mechanism rather
than this module guessing wrong.

WHAT'S REAL vs. NOT:
  - Silence/short-answer detection: real, deterministic, no LLM needed.
  - Role validation (E-03), code-dictation detection (E-02), question
    generation, answer evaluation: all delegated to ask_llm — actual
    accuracy depends entirely on whatever's wired in, unverified here.
  - Final fluency component of the scorecard (TC-05: "feedback on both
    technical clarity and English fluency") reuses the REAL, ALREADY-
    BUILT ConfidenceGrammarAnalyzer/FluencyAnalyzer (from confidence.py)
    if audio data is supplied — genuine reuse, not another LLM guess,
    since that's exactly what those modules already measure.
"""

import logging
import time
from typing import Callable, Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TechnicalInterviewSession:
    """
    State machine for one Technical Interview session. Delegates all
    dynamic content to an injected ask_llm callable; handles silence/
    short-answer detection deterministically.
    """

    def __init__(
        self,
        ask_llm: Optional[Callable[[str, str], str]] = None,
        silence_threshold_seconds: float = 30.0,
        short_answer_word_threshold: int = 15,
        confidence_analyzer=None,
        context_type: str = "technical",
    ):
        """
        Args:
            ask_llm: callable(prompt, context_type) -> str, the same
                shape as ConversationEngine.generate_response(). Required
                for start_session()/submit_answer() to produce real
                content — without it, this module fails closed (see
                llm_unavailable in returned dicts).
            silence_threshold_seconds: E-01's ">30 seconds" from the spec
                — the only spec-given number here, not a guess.
            short_answer_word_threshold: E-04's "one-sentence answer" has
                no exact word count in the spec — this is a judgment
                call, fully overridable.
            confidence_analyzer: optional ConfidenceGrammarAnalyzer
                instance (confidence.py) reused for the fluency component
                of the final scorecard (TC-05), if audio data is
                available at end_session(). Real reuse, not invented.
            context_type: passed to ask_llm — pipeline.py already
                supports "technical" as one of its four documented
                context_type values, reused as-is here, not invented.
        """
        self.ask_llm = ask_llm
        self.silence_threshold_seconds = silence_threshold_seconds
        self.short_answer_word_threshold = short_answer_word_threshold
        self.confidence_analyzer = confidence_analyzer
        self.context_type = context_type

        self.role: Optional[str] = None
        self.transcript: List[Dict[str, str]] = []  # [{"role": "ai"/"user", "text": ...}]

        if self.ask_llm is None:
            logger.warning(
                "No ask_llm provided — this module cannot generate questions/"
                "evaluate answers until the project's real ConversationEngine "
                "access point is wired in."
            )

    def start_session(self, target_role: str) -> Dict[str, any]:
        """
        Happy Path steps 1-2. Validates the role is technical (E-03)
        before generating the first question.

        Returns:
            Dict with:
                - question: str or None
                - redirect_to_hr: bool (E-03)
                - llm_unavailable: bool
        """
        if self.ask_llm is None:
            return {"question": None, "redirect_to_hr": False, "llm_unavailable": True}

        self.role = target_role

        validation_prompt = (
            f"A user entered '{target_role}' as their target role for a TECHNICAL "
            "job interview practice session. Is this a genuinely technical role "
            "(e.g. Software Engineer, Data Analyst, DevOps)? Answer with only "
            "YES or NO on the first line."
        )
        try:
            validation = self.ask_llm(validation_prompt, self.context_type)
        except Exception as e:
            logger.error("ask_llm failed during role validation: %s", e)
            return {"question": None, "redirect_to_hr": False, "llm_unavailable": True}

        if validation and validation.strip().upper().startswith("NO"):
            # E-03: non-technical role -> redirect, no question generated.
            return {"question": None, "redirect_to_hr": True, "llm_unavailable": False}

        question = self._ask_for_question(
            f"Start a mock technical interview for a {target_role} candidate. "
            "Ask one relevant opening technical question (algorithm, systems "
            "design, or role-specific). Ask ONLY the question, nothing else."
        )
        return {"question": question, "redirect_to_hr": False, "llm_unavailable": question is None}

    def submit_answer(
        self,
        answer_text: str,
        silence_duration_seconds: float = 0.0,
    ) -> Dict[str, any]:
        """
        Happy Path steps 3-4, plus E-01/E-02/E-04.

        Returns:
            Dict with:
                - message: the AI's next line (prompt, follow-up
                  question, or redirect instruction)
                - exception_triggered: None, "prolonged_silence",
                  "code_dictation", or "short_answer"
                - llm_unavailable: bool
        """
        if self.ask_llm is None:
            return {"message": None, "exception_triggered": None, "llm_unavailable": True}

        # E-01: deterministic, no LLM needed.
        if silence_duration_seconds > self.silence_threshold_seconds:
            return {
                "message": "It's okay to take your time. Can you talk me through your thought process?",
                "exception_triggered": "prolonged_silence",
                "llm_unavailable": False,
            }

        word_count = len(answer_text.split())

        # E-02: code-dictation detection delegated to ask_llm (judgment
        # call, not a hardcoded keyword list).
        code_check = self._ask_llm_safe(
            f"Is this interview answer the user literally dictating raw code "
            f"syntax character-by-character, rather than explaining logic in "
            f"words? Answer: \"{answer_text}\"\nAnswer YES or NO on the first line."
        )
        if code_check and code_check.strip().upper().startswith("YES"):
            self.transcript.append({"role": "user", "text": answer_text})
            return {
                "message": "Let's focus on explaining the architecture and logic rather than dictating exact syntax.",
                "exception_triggered": "code_dictation",
                "llm_unavailable": False,
            }

        self.transcript.append({"role": "user", "text": answer_text})

        # E-04: deterministic word-count guard, threshold is the guess, not the check itself.
        if word_count <= self.short_answer_word_threshold:
            message = self._ask_for_question(
                "The candidate's answer was very short for a complex technical "
                f"question: \"{answer_text}\". Ask them to expand specifically on "
                "their architecture choices and trade-offs."
            )
            return {"message": message, "exception_triggered": "short_answer", "llm_unavailable": message is None}

        message = self._ask_for_question(
            f"Candidate answered: \"{answer_text}\". Ask a natural follow-up "
            "question, simulating real interview pacing (not a static list)."
        )
        return {"message": message, "exception_triggered": None, "llm_unavailable": message is None}

    def end_session(
        self,
        audio: Optional[any] = None,
        sample_rate: Optional[int] = None,
        word_timings: Optional[List[Dict[str, any]]] = None,
        full_transcript_text: Optional[str] = None,
    ) -> Dict[str, any]:
        """
        Final scorecard (TC-05: technical clarity AND English fluency).

        Args:
            audio, sample_rate, word_timings, full_transcript_text: if
                provided and confidence_analyzer was injected, produces a
                REAL fluency component via FluencyAnalyzer/GrammarCorrector
                (reused, not another LLM guess). If omitted, fluency_component
                is None — not faked.
        """
        technical_feedback = self._ask_llm_safe(
            "Based on this technical interview transcript, evaluate the "
            f"candidate's logic, clarity, and communication:\n{self.transcript}\n"
            "Give a short scorecard summary."
        )

        fluency_component = None
        if self.confidence_analyzer is not None and audio is not None and full_transcript_text is not None:
            fluency_component = self.confidence_analyzer.analyze_from_audio(
                audio, sample_rate, word_timings or [], full_transcript_text
            )

        return {
            "technical_feedback": technical_feedback,
            "fluency_component": fluency_component,
            "llm_unavailable": technical_feedback is None,
        }

    def _ask_for_question(self, instruction: str) -> Optional[str]:
        response = self._ask_llm_safe(instruction)
        if response:
            self.transcript.append({"role": "ai", "text": response})
        return response

    def _ask_llm_safe(self, prompt: str) -> Optional[str]:
        try:
            return self.ask_llm(prompt, self.context_type)
        except Exception as e:
            logger.error("ask_llm call failed: %s", e)
            return None
