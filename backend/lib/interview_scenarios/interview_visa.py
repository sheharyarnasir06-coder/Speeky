"""
Interview Coach - Visa Interview Simulation (US-51 / PDF US-045 / INT-US-13).

Same design principle as interview_technical.py: no local model, no
hardcoded question banks. Deterministic parts (timing, word count) are
plain Python. Persona-driven questions, contradiction detection, and
vague-answer judgment are delegated to an injected ask_llm callable.

REAL BLOCKER, unresolved (see interview_technical.py's docstring for the
full explanation): ask_llm's real wiring into ConversationEngine is
unknown/unverified here.

Brevity scoring (heavily emphasized by this story's acceptance criteria)
is computed DETERMINISTICALLY from word count and elapsed time — not an
LLM guess — since that part genuinely doesn't need judgment.
"""

import logging
from typing import Callable, Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VisaInterviewSession:
    """State machine for one Visa Interview session."""

    def __init__(
        self,
        ask_llm: Optional[Callable[[str, str], str]] = None,
        rambling_seconds_threshold: float = 180.0,
        nervous_silence_threshold_seconds: float = 10.0,
        context_type: str = "visa",
    ):
        """
        Args:
            ask_llm: callable(prompt, context_type) -> str.
            rambling_seconds_threshold: E-01's spec example is "a 3-minute
                answer" — 180s is that exact number, not a guess.
            nervous_silence_threshold_seconds: E-04's spec number,
                ">10 seconds" — exact, not a guess.
            context_type: NOTE — "visa" is NOT one of pipeline.py's four
                documented context_type values (hr, technical, functional,
                general). This is a new value this module introduces;
                flagging it as an assumption that needs confirming with
                whoever owns context_type's real meaning downstream.
        """
        self.ask_llm = ask_llm
        self.rambling_seconds_threshold = rambling_seconds_threshold
        self.nervous_silence_threshold_seconds = nervous_silence_threshold_seconds
        self.context_type = context_type

        self.visa_type: Optional[str] = None
        self.transcript: List[Dict[str, str]] = []
        self.stated_facts: List[str] = []  # accumulated for E-02 contradiction checking
        self._silence_repeat_count = 0

        if self.ask_llm is None:
            logger.warning(
                "No ask_llm provided — this module cannot generate questions/"
                "evaluate answers until wired in."
            )

    def start_session(self, visa_type: str) -> Dict[str, any]:
        """Happy Path steps 1-2, plus E-05 (unrecognized visa category)."""
        if self.ask_llm is None:
            return {"question": None, "fallback_used": False, "llm_unavailable": True}

        self.visa_type = visa_type

        recognition_check = self._ask_llm_safe(
            f"Is '{visa_type}' a real, recognized visa category or subclass "
            "(e.g. F1 Student, B1/B2 Tourist, H1B Work)? Answer YES or NO on "
            "the first line."
        )

        if recognition_check and recognition_check.strip().upper().startswith("NO"):
            # E-05: fall back to a general question bank, generated (not hardcoded).
            question = self._ask_for_question(
                "The user's visa category was not recognized. Ask a general "
                "'intent to travel / immigration' opening question suitable "
                "for any visa interview, in a strict consular-officer persona."
            )
            return {"question": question, "fallback_used": True, "llm_unavailable": question is None}

        question = self._ask_for_question(
            f"Adopt the persona of a strict, formal, fast-paced consular "
            f"officer interviewing a {visa_type} visa applicant. Ask one "
            "targeted opening question about their intent, finances, or ties "
            "to their home country. Ask ONLY the question."
        )
        return {"question": question, "fallback_used": False, "llm_unavailable": question is None}

    def submit_answer(
        self,
        answer_text: str,
        elapsed_seconds: float = 0.0,
        silence_duration_seconds: float = 0.0,
    ) -> Dict[str, any]:
        """
        Happy Path steps 3-4, plus E-01/E-02/E-03/E-04.

        Returns:
            Dict with:
                - message: AI's next line
                - exception_triggered: None, "rambling", "contradiction",
                  "vague_home_ties", or "nervous_silence"
                - brevity_penalty: bool (E-01's scorecard penalty flag)
                - llm_unavailable: bool
        """
        if self.ask_llm is None:
            return {
                "message": None,
                "exception_triggered": None,
                "brevity_penalty": False,
                "llm_unavailable": True,
            }

        # E-04: deterministic, no LLM needed.
        if silence_duration_seconds > self.nervous_silence_threshold_seconds:
            self._silence_repeat_count += 1
            if self._silence_repeat_count == 1:
                last_question = self._last_ai_message()
                return {
                    "message": last_question,
                    "exception_triggered": "nervous_silence",
                    "brevity_penalty": False,
                    "llm_unavailable": False,
                }
            return {
                "message": None,
                "exception_triggered": "nervous_silence",
                "brevity_penalty": False,
                "llm_unavailable": False,
            }
        self._silence_repeat_count = 0

        # E-01: deterministic time check, no LLM needed for the trigger itself.
        if elapsed_seconds > self.rambling_seconds_threshold:
            self.transcript.append({"role": "user", "text": answer_text})
            return {
                "message": "Thank you, but please just state your answer directly.",
                "exception_triggered": "rambling",
                "brevity_penalty": True,
                "llm_unavailable": False,
            }

        self.transcript.append({"role": "user", "text": answer_text})
        self.stated_facts.append(answer_text)

        # E-02: contradiction detection needs semantic understanding across
        # turns — genuinely an LLM task, not deterministic.
        if len(self.stated_facts) >= 2:
            contradiction_check = self._ask_llm_safe(
                "Review these statements from a visa interview for internal "
                f"contradictions: {self.stated_facts}. If there IS a "
                "contradiction, respond with a sharp follow-up question "
                "challenging it, starting with 'CONTRADICTION:'. If none, "
                "respond with only 'NONE'."
            )
            if contradiction_check and contradiction_check.strip().upper() != "NONE":
                self.transcript.append({"role": "ai", "text": contradiction_check})
                return {
                    "message": contradiction_check,
                    "exception_triggered": "contradiction",
                    "brevity_penalty": False,
                    "llm_unavailable": False,
                }

        # E-03: vague home-country-ties judgment call.
        vague_check = self._ask_llm_safe(
            f"Is this visa applicant's answer vague/ambiguous about their "
            f"intent to return to their home country? Answer: \"{answer_text}\"\n"
            "Answer YES or NO on the first line."
        )
        if vague_check and vague_check.strip().upper().startswith("YES"):
            return {
                "message": None,
                "exception_triggered": "vague_home_ties",
                "brevity_penalty": False,
                "llm_unavailable": False,
            }

        message = self._ask_for_question(
            f"Applicant answered: \"{answer_text}\". As the strict consular "
            "officer persona, ask the next rapid-fire question."
        )
        return {
            "message": message,
            "exception_triggered": None,
            "brevity_penalty": False,
            "llm_unavailable": message is None,
        }

    def end_session(self, total_elapsed_seconds: float, total_word_count: int) -> Dict[str, any]:
        """
        Final scorecard, "heavily weighted on brevity, clarity, and
        consistency of facts" per acceptance criteria.

        brevity_score is DETERMINISTIC (words per second of answer time) —
        not an LLM guess. Calibration (the 1.0 wps baseline, the 40.0
        penalty multiplier) is NOT spec-defined, a judgment call, fully
        overridable by whoever calibrates this for real.
        """
        brevity_score = None
        if total_elapsed_seconds > 0:
            words_per_second = total_word_count / total_elapsed_seconds
            brevity_score = round(max(0.0, min(100.0, 100.0 - (words_per_second - 1.0) * 40.0)), 1)

        qualitative_feedback = self._ask_llm_safe(
            "Based on this visa interview transcript, give feedback on "
            f"clarity and consistency of facts:\n{self.transcript}"
        )

        return {
            "brevity_score": brevity_score,
            "qualitative_feedback": qualitative_feedback,
            "llm_unavailable": qualitative_feedback is None,
        }

    def _ask_for_question(self, instruction: str) -> Optional[str]:
        response = self._ask_llm_safe(instruction)
        if response:
            self.transcript.append({"role": "ai", "text": response})
        return response

    def _last_ai_message(self) -> Optional[str]:
        for entry in reversed(self.transcript):
            if entry["role"] == "ai":
                return entry["text"]
        return None

    def _ask_llm_safe(self, prompt: str) -> Optional[str]:
        try:
            return self.ask_llm(prompt, self.context_type)
        except Exception as e:
            logger.error("ask_llm call failed: %s", e)
            return None
