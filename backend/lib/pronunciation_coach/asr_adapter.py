"""
ASR Adapter: Faster-Whisper → WordAttempt

Converts the raw word_timings list produced by the real STT pipeline
(backend/voice_agent/agent.py → transcribe_audio()) into the
List[Optional[WordAttempt]] that pronunciation_pipeline.py's
score_sentence() / score_sentence_for_user() expects.

STT output format (Faster-Whisper, word_timestamps=True):
    [
        {"word": str, "start": float, "end": float},
        ...
    ]

Faster-Whisper does NOT output per-word confidence — it provides
segment-level avg_logprob but NOT per-word confidence scores.
The adapter defaults confidence to 0.5 (WordAttempt's own default),
which keeps classification conservative (borderline-RED range) and
ensures no data is fabricated.

Alignment strategy:
  - Strip punctuation from both the STT words and target words before
    comparing (Whisper frequently returns words with trailing commas,
    periods, etc.).
  - Case-insensitive match.
  - A greedy left-to-right scan: for each target word, look ahead in
    the remaining STT words for the first match (allows skipping
    over deletions/insertions without crashing).
  - Target words with no matching STT word → None (omission, E-01
    gray tier in the pipeline).
  - This is intentionally simple — the pipeline already handles the
    hard cases (omissions, noise, repetitions) itself.
"""

import re
from typing import Dict, List, Optional

from lib.pronunciation_coach.pronunciation_pipeline import WordAttempt

# Default confidence when Faster-Whisper does not supply per-word scores.
# 0.5 is WordAttempt's own field default; using it explicitly makes the
# adapter's intent visible in code.
_DEFAULT_CONFIDENCE: float = 0.5

# How many STT tokens ahead to scan for a target-word match before
# declaring the word omitted.  A small window avoids false matches on
# common words while still tolerating a few Whisper insertion tokens.
_LOOKAHEAD: int = 4


def _normalize(word: str) -> str:
    """Strip punctuation and lowercase for comparison."""
    return re.sub(r"[^\w']", "", word).lower()


def word_timings_to_attempts(
    word_timings: List[Dict],
    target_sentence: str,
    default_confidence: float = _DEFAULT_CONFIDENCE,
) -> List[Optional[WordAttempt]]:
    """
    Align Faster-Whisper word_timings against a target sentence and
    return one Optional[WordAttempt] per target word.

    Args:
        word_timings:
            Raw list from voice_agent/agent.py transcribe_audio():
            [{"word": str, "start": float, "end": float}, ...]
            Each entry must have "word", "start", "end".  A missing
            "confidence" key is silently replaced by default_confidence.
        target_sentence:
            The sentence the learner was asked to read aloud.
        default_confidence:
            Fallback confidence when the STT engine does not supply
            per-word scores (always the case for Faster-Whisper).

    Returns:
        A list with exactly one entry per whitespace-token in
        target_sentence.  Entry is None when no STT word could be
        matched (E-01 omission) or a WordAttempt otherwise.

    Raises:
        ValueError: if any entry in word_timings is missing "word",
            "start", or "end".
    """
    target_words = target_sentence.split()
    if not target_words:
        return []

    # Validate & normalise the STT word list once up front.
    normalised_stt: List[Dict] = []
    for i, wt in enumerate(word_timings):
        for key in ("word", "start", "end"):
            if key not in wt:
                raise ValueError(
                    f"word_timings[{i}] is missing required key '{key}': {wt!r}"
                )
        normalised_stt.append(
            {
                "word": wt["word"],
                "norm": _normalize(wt["word"]),
                "start": float(wt["start"]),
                "end": float(wt["end"]),
                "confidence": float(wt.get("confidence", default_confidence)),
            }
        )

    attempts: List[Optional[WordAttempt]] = []
    stt_cursor = 0  # next unconsumed STT token index

    for target_word in target_words:
        norm_target = _normalize(target_word)

        # Scan ahead from the current cursor position.
        match_idx: Optional[int] = None
        for j in range(stt_cursor, min(stt_cursor + _LOOKAHEAD, len(normalised_stt))):
            if normalised_stt[j]["norm"] == norm_target:
                match_idx = j
                break

        if match_idx is not None:
            tok = normalised_stt[match_idx]
            attempts.append(
                WordAttempt(
                    word=target_word,   # use the canonical target spelling
                    start=tok["start"],
                    end=tok["end"],
                    confidence=tok["confidence"],
                )
            )
            stt_cursor = match_idx + 1  # consume up to and including the match
        else:
            # No STT token matched this target word → omission (E-01).
            attempts.append(None)

    return attempts
