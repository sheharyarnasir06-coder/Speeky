"""
Target-text <-> transcript word alignment, and lexical stress lookup.

Alignment reuses difflib.SequenceMatcher — the same stdlib tool lib/grammar_checker.py
already uses for its correction-chip diff — rather than a new fuzzy-matching dependency.
Stress lookup uses `pronouncing` (a thin CMU Pronouncing Dictionary wrapper, no model
download) to get the expected primary-stress syllable position for a word, which
lib/prosody_engine.word_stress_peak_position() is compared against to flag stress errors.
"""

import difflib
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import pronouncing


class WordStatus(str, Enum):
    CORRECT = "correct"
    MISPRONOUNCED = "mispronounced"
    STRESS_ERROR = "stress_error"
    SKIPPED = "skipped"


def normalize(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


# Below this length a one-character difference usually IS a different word — and those
# short minimal pairs (ship/sheep, bit/beat, cat/cut) are exactly what pronunciation
# practice is meant to catch, so short words must still match exactly.
MIN_LENGTH_FOR_NEAR_MATCH = 5

# An affix turns a word into a different one ("comfortable" -> "uncomfortable",
# "happy" -> "unhappy") while keeping similarity very high, so containment plus this
# many extra characters is treated as a different word, never a near-miss.
MIN_AFFIX_LENGTH_DELTA = 2


def similarity(target_word: str, spoken_word: str) -> float:
    """0..1 closeness of two normalized words (difflib, same tool the aligner uses)."""
    return difflib.SequenceMatcher(None, normalize(target_word), normalize(spoken_word)).ratio()


def is_near_match(target_word: str, spoken_word: str, min_ratio: float) -> bool:
    """True when the transcript word is a near-miss spelling of the target rather than a
    genuinely different word.

    Speech-to-text routinely returns approximate spellings for accented but perfectly
    intelligible speech ("comfortable" -> "comftable"). Scoring those as mispronounced
    made the coach demand near-native articulation before it would credit a word. A
    similarity floor accepts the near-miss while still rejecting a substituted word —
    "nice" heard as "beautiful" scores far below any sane floor and stays mispronounced.
    """
    target, spoken = normalize(target_word), normalize(spoken_word)
    if not target or not spoken:
        return False
    if target == spoken:
        return True
    if len(target) < MIN_LENGTH_FOR_NEAR_MATCH:
        return False
    # Affixation (un-, mis-, -ness) reads as highly similar but means something else.
    if (target in spoken or spoken in target) and abs(len(target) - len(spoken)) >= MIN_AFFIX_LENGTH_DELTA:
        return False
    return similarity(target, spoken) >= min_ratio


@dataclass
class AlignedWord:
    target_word: str
    target_index: int
    transcript_word: Optional[str]  # None => skipped (present in target, absent in transcript)
    transcript_index: Optional[int]


def align_words(target_text: str, transcript_words: List[str]) -> List[AlignedWord]:
    """Align every target word to its best-matching transcribed word (if any).

    Deletions (target word with no transcript counterpart) become skipped words.
    Insertions (transcribed words with no target counterpart -- filler, stutter repeats,
    background/second-voice speech) are dropped rather than attached to any target word;
    lib/recording_engine.py's disfluency detection looks at raw insertions separately.
    """
    target_words = target_text.split()
    norm_target = [normalize(w) for w in target_words]
    norm_transcript = [normalize(w) for w in transcript_words]

    matcher = difflib.SequenceMatcher(a=norm_target, b=norm_transcript, autojunk=False)
    aligned: List[AlignedWord] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                ti, tj = i1 + offset, j1 + offset
                aligned.append(AlignedWord(target_words[ti], ti, transcript_words[tj], tj))
        elif tag == "replace":
            pair_count = min(i2 - i1, j2 - j1)
            for offset in range(pair_count):
                ti, tj = i1 + offset, j1 + offset
                aligned.append(AlignedWord(target_words[ti], ti, transcript_words[tj], tj))
            for ti in range(i1 + pair_count, i2):
                aligned.append(AlignedWord(target_words[ti], ti, None, None))
        elif tag == "delete":
            for ti in range(i1, i2):
                aligned.append(AlignedWord(target_words[ti], ti, None, None))
        # "insert": extra transcribed words with no target counterpart -- ignored here

    aligned.sort(key=lambda a: a.target_index)
    return aligned


@dataclass
class PassageCoverage:
    matched_word_count: int
    total_target_words: int
    coverage_ratio: float
    trailing_coverage_ratio: float  # coverage within the passage's final N% (config-driven)


def compute_passage_coverage(aligned_words: List[AlignedWord], trailing_window_fraction: float) -> PassageCoverage:
    """trailing_coverage_ratio specifically catches "stopped reading mid-passage" --
    a reader who covers the first 60% and then stops can still have a deceptively
    reasonable overall coverage_ratio, but their trailing window will be near zero.
    """
    total = len(aligned_words)
    matched = sum(1 for a in aligned_words if a.transcript_word is not None)
    coverage_ratio = (matched / total) if total else 0.0

    trailing_start = int(total * (1 - trailing_window_fraction))
    trailing_words = aligned_words[trailing_start:]
    trailing_matched = sum(1 for a in trailing_words if a.transcript_word is not None)
    trailing_ratio = (trailing_matched / len(trailing_words)) if trailing_words else 1.0

    return PassageCoverage(
        matched_word_count=matched,
        total_target_words=total,
        coverage_ratio=coverage_ratio,
        trailing_coverage_ratio=trailing_ratio,
    )


def expected_stress_position(word: str) -> Optional[float]:
    """Fractional position (0.0 = start of word, 1.0 = end) of the CENTER of the word's
    primary-stressed syllable, from the CMU dictionary, assuming syllables divide the
    word's duration roughly equally. None for out-of-dictionary words (names, foreign
    borrowings) or single-syllable words -- callers skip the stress-error check then.

    Deliberately the center of the syllable's estimated slot, not the syllable-index
    boundary itself (e.g. primary_index / (count - 1), which collapses to an
    unrealistic 0.0/1.0 point at the very edge of the word for any 2-syllable word).
    Verified against real recorded audio: an edge-anchored position was flagging
    correctly-stressed real words as stress errors just because the intensity peak
    wasn't sitting on the literal first or last frame of the word's ASR timestamp.
    """
    clean = normalize(word)
    if not clean:
        return None
    phones_list = pronouncing.phones_for_word(clean)
    if not phones_list:
        return None

    stress_pattern = pronouncing.stresses(phones_list[0])  # e.g. "010"
    syllable_count = len(stress_pattern)
    if "1" not in stress_pattern or syllable_count <= 1:
        return None

    primary_index = stress_pattern.index("1")
    return (primary_index + 0.5) / syllable_count


def syllable_count(word: str) -> Optional[int]:
    """Syllable count from the CMU dictionary (number of stress-marked phones). None
    for out-of-dictionary words -- callers treat that as "unknown", not zero."""
    clean = normalize(word)
    if not clean:
        return None
    phones_list = pronouncing.phones_for_word(clean)
    if not phones_list:
        return None
    return len(pronouncing.stresses(phones_list[0]))
