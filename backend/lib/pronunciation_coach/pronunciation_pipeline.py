"""
Shared word-level pronunciation-scoring pipeline (Story 1 core).

This is the SINGLE scoring pipeline shared by all four Pronunciation Coach
user stories (word-level highlighting, accessibility safeguard, outage
fallback, trouble-words bank). It wraps the existing, unmodified
PronunciationScorer (lib/pronunciation_coach/pronunciation.py) and adds the word-level
color-tier classification, exception handling (omission / stutter /
accent calibration / noise), and configuration that PronunciationScorer
itself does not provide.

Story 2 (accessibility_profile.py), Story 3 (pronunciation_reliability.py)
and Story 4 (trouble_words.py) all consume PronunciationPipeline's output
(SentenceScoreResult / WordScoreResult) rather than re-implementing any
scoring logic, so pronunciation logic is never forked per story.

Design note on inputs: WordAligner (the old speeky/alignment.py module (pre-restructure standalone location)
that produced timestamped word alignments from raw audio) was NOT part of
what was restored for this feature. `score_sentence()` therefore expects
its `attempts` argument already aligned 1:1 with `target_words` (one
attempt, or None for an omitted word, per target-sentence position) -
exactly the "word_alignments" shape PronunciationScorer's own docstring
already assumes. Any upstream ASR/alignment step is out of scope here.

Accent-aware scoring (wired to lib/accent_assessment/): a user's selected
target accent (accent_assessment.TargetAccentSelectionService) changes
WHICH PronunciationPipelineConfig is used for a given scoring call, via
AccentPronunciationConfigRegistry below. This module imports FROM
accent_assessment (lazily, same pattern as the `scorer` property) -
accent_assessment has no reverse dependency on this package.
score_sentence() itself stays fully synchronous and defaults to
self.config exactly as before; accent resolution is an explicit,
separate async step (resolve_config_for_user / score_sentence_for_user)
so every existing synchronous caller/test is unaffected.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence, Set

logger = logging.getLogger(__name__)


class ColorTier(str, Enum):
    """UI highlight tiers for a scored word (Story 1)."""

    GREEN = "green"          # correctly pronounced
    ORANGE = "orange"        # minor stress/timing error, phonemes essentially right
    RED = "red"              # complete mispronunciation
    GRAY = "gray"            # omitted entirely (E-01)
    UNSCORABLE = "unscorable"  # interrupted by noise/outage, not judged (E-04)


@dataclass(frozen=True)
class PronunciationPipelineConfig:
    """
    Named, overridable thresholds for color-tier classification.

    All defaults below are UNCALIBRATED placeholders - nobody has supplied
    real calibration data (a labeled corpus of green/orange/red judgments)
    for this project yet. They are deliberately named and constructor-
    injectable so a calibration pass can replace them without touching
    pipeline logic. Do not treat these numbers as validated.
    """

    # Final word_score (0-100, post duration-penalty) at/above which a
    # word is GREEN. UNCALIBRATED.
    green_min_score: float = 80.0

    # Underlying phoneme-confidence percentage (word_scores[i]['confidence']
    # * 100, BEFORE the duration penalty PronunciationScorer applies) below
    # which the word is treated as a genuine mispronunciation (RED) no
    # matter what the timing looks like. At/above this, a low final score
    # is attributed to stress/timing only (ORANGE), since the underlying
    # phoneme match was fine. UNCALIBRATED.
    mispronunciation_confidence_floor: float = 60.0

    # Phoneme substitution pairs treated as acceptable regional variation
    # when the "Local Accent" toggle is on (E-03). Keys/values are CMU
    # ARPAbet phonemes (matching g2p_en's output alphabet in
    # pronunciation.py). This is a placeholder starter list, not a
    # linguist-reviewed table - UNCALIBRATED, flagged for review.
    regional_variant_tolerant_pairs: frozenset = field(
        default_factory=lambda: frozenset(
            {
                frozenset({"AA", "AO"}),  # cot/caught-type merger
                frozenset({"T", "D"}),    # flapped/soft T in many dialects
                frozenset({"IH", "IY"}),  # relaxed final vowel
            }
        )
    )

    # Per-repetition fluency penalty applied for stuttered words (E-02),
    # in points off the 0-100 sentence fluency_score. UNCALIBRATED.
    per_repetition_fluency_penalty: float = 8.0

    # Repetition count (attempts before the final, successful one) at or
    # above which a word counts as "stuttered" for fluency-penalty
    # purposes. A single retry isn't penalized; 2+ retries is. UNCALIBRATED.
    stutter_repetition_threshold: int = 2

    # E-03 accent calibration tolerance band: how far below
    # mispronunciation_confidence_floor a word's raw confidence may fall
    # and still be considered for regional-variant acceptance (see
    # _is_regional_variant). UNCALIBRATED.
    regional_variant_confidence_tolerance: float = 15.0


# --- Per-target-accent config, wired to lib/accent_assessment/ -------------
# Defaults below are UNCALIBRATED starter values (same disclaimer as
# PronunciationPipelineConfig itself) - a real calibration pass, per
# accent, would replace these without touching any lookup logic.

# General American: keeps the flapped-T / cot-caught-merger tolerance
# that was PronunciationPipelineConfig's original default set - those are
# characteristically General-American phenomena.
_GENERAL_AMERICAN_CONFIG = PronunciationPipelineConfig()

# British RP: non-rhotic (final/pre-consonant /r/ often reduced towards a
# schwa-like AH) and a broader trap-bath vowel split (AE/AA) are the
# British-specific tolerances; the American flapped-T pair does NOT
# carry over - a flapped T is not standard in RP.
_BRITISH_RP_CONFIG = PronunciationPipelineConfig(
    regional_variant_tolerant_pairs=frozenset(
        {
            frozenset({"ER", "AH"}),  # non-rhotic reduction
            frozenset({"AE", "AA"}),  # trap-bath split
            frozenset({"IH", "IY"}),  # relaxed final vowel (shared w/ GA default)
        }
    ),
)

# Neutral International: deliberately the widest tolerance band, since
# its whole premise is "no single national norm enforced" - union of the
# other two accents' pairs, plus a larger confidence-tolerance band.
_NEUTRAL_INTERNATIONAL_CONFIG = PronunciationPipelineConfig(
    regional_variant_tolerant_pairs=frozenset(
        _GENERAL_AMERICAN_CONFIG.regional_variant_tolerant_pairs
        | _BRITISH_RP_CONFIG.regional_variant_tolerant_pairs
    ),
    regional_variant_confidence_tolerance=25.0,
)

DEFAULT_ACCENT_PRONUNCIATION_CONFIGS: Dict[str, PronunciationPipelineConfig] = {
    "general_american": _GENERAL_AMERICAN_CONFIG,
    "british_rp": _BRITISH_RP_CONFIG,
    "neutral_international": _NEUTRAL_INTERNATIONAL_CONFIG,
}


@dataclass
class AccentPronunciationConfigRegistry:
    """
    Injectable/overridable per-target-accent scoring config - same
    registry pattern as accent_assessment.TargetAccentRegistry (a plain
    dict, not a fixed if/else or enum). Maps a target_accent_id (as
    selected via accent_assessment.TargetAccentSelectionService) to the
    PronunciationPipelineConfig that should be used for that accent.

    Deliberately keyed by plain accent_id strings rather than importing
    accent_assessment.TargetAccentOption, so this file has no import-time
    dependency on that package - keeps the dependency one-directional
    (pronunciation_coach -> accent_assessment, never the reverse).
    """

    configs: Dict[str, PronunciationPipelineConfig] = field(
        default_factory=lambda: dict(DEFAULT_ACCENT_PRONUNCIATION_CONFIGS)
    )
    default_config: PronunciationPipelineConfig = field(default_factory=PronunciationPipelineConfig)

    def get(self, accent_id: Optional[str]) -> PronunciationPipelineConfig:
        """Unknown/None accent_id falls back to default_config - never raises."""
        if accent_id is None:
            return self.default_config
        return self.configs.get(accent_id, self.default_config)


class ScorerLike(Protocol):
    """Structural type for whatever PronunciationScorer-shaped object is injected."""

    def score_pronunciation(self, audio, sample_rate, word_alignments, reference_text) -> Dict:
        ...

    def get_phoneme_errors(self, predicted_phonemes: List[str], target_phonemes: List[str]) -> List[Dict[str, str]]:
        ...


@dataclass
class WordAttempt:
    """One transcribed/aligned attempt for a single target-sentence word position."""

    word: str
    start: float
    end: float
    confidence: float = 0.5
    repetitions: int = 1          # E-02: attempts made before this final articulation
    unscorable: bool = False      # E-04: interrupted by background noise etc.
    # Optional: only populated if an upstream ASR/alignment step supplies
    # them (none is built yet - see module docstring). When both are
    # present, _is_regional_variant() does real phoneme-pair comparison
    # via self.scorer.get_phoneme_errors() against
    # config.regional_variant_tolerant_pairs instead of the confidence-
    # band fallback heuristic.
    predicted_phonemes: Optional[List[str]] = None
    target_phonemes: Optional[List[str]] = None


@dataclass
class WordScoreResult:
    index: int
    target_word: str
    tier: ColorTier
    strikethrough: bool = False
    final_score: Optional[float] = None
    raw_confidence_pct: Optional[float] = None
    note: str = ""


@dataclass
class SentenceScoreResult:
    target_sentence: str
    words: List[WordScoreResult]
    fluency_score: float
    scoring_profile: str = "standard"  # "standard" | "accessibility" (Story 2 E-04)
    retry_recommended: bool = False

    def red_or_gray_words(self) -> List[WordScoreResult]:
        """Words a 'Retry' action (Story 1 happy path) should focus on."""
        return [w for w in self.words if w.tier in (ColorTier.RED, ColorTier.GRAY)]


class PronunciationPipeline:
    """
    The shared pronunciation-scoring pipeline.

    Wraps an injected PronunciationScorer-shaped object (defaults to
    lib.pronunciation_coach.pronunciation.PronunciationScorer, built lazily so callers that
    don't need real g2p_en scoring - e.g. tests - can inject a stub).

    Accent-aware scoring (accent_registry/accent_selection_service) is
    entirely optional and lazily constructed, same as `scorer` - existing
    callers that never pass these, and never call resolve_config_for_user/
    score_sentence_for_user, get byte-identical behavior to before this
    feature existed.
    """

    def __init__(
        self,
        scorer: Optional[ScorerLike] = None,
        config: Optional[PronunciationPipelineConfig] = None,
        accent_registry: Optional[AccentPronunciationConfigRegistry] = None,
        accent_selection_service: Optional[Any] = None,
    ):
        self._scorer = scorer
        self.config = config or PronunciationPipelineConfig()
        self.accent_registry = accent_registry
        self._accent_selection_service = accent_selection_service

    @property
    def scorer(self) -> ScorerLike:
        if self._scorer is None:
            from lib.pronunciation_coach.pronunciation import PronunciationScorer

            self._scorer = PronunciationScorer()
        return self._scorer

    @property
    def accent_selection_service(self) -> Any:
        """
        Lazily-built accent_assessment.TargetAccentSelectionService -
        same lazy-import pattern as `scorer`, so constructing a
        PronunciationPipeline never requires a DB connection unless
        resolve_config_for_user()/score_sentence_for_user() is actually
        called.
        """
        if self._accent_selection_service is None:
            from lib.accent_assessment.target_accent_selection import TargetAccentSelectionService

            self._accent_selection_service = TargetAccentSelectionService()
        return self._accent_selection_service

    async def resolve_config_for_user(self, user_id: str) -> PronunciationPipelineConfig:
        """
        Look up `user_id`'s selected target accent (accent_assessment) and
        resolve the accent-specific PronunciationPipelineConfig via
        self.accent_registry. Falls back to self.config (this pipeline's
        own default) if no accent_registry was injected, or if the user
        has no target-accent selection on record yet - never raises for
        an unset preference.

        Async because accent_assessment's persistence (lib/kv_store.py)
        is async-only; score_sentence() itself stays synchronous (see
        module docstring) - this is a separate, explicit step callers opt
        into.
        """
        if self.accent_registry is None:
            return self.config
        preference = await self.accent_selection_service.get_preference(user_id)
        if preference is None:
            return self.config
        return self.accent_registry.get(preference.current_accent_id)

    async def score_sentence_for_user(
        self,
        user_id: str,
        target_sentence: str,
        attempts: Sequence[Optional[WordAttempt]],
        accent_calibration: bool = False,
        accessibility_exempt_indices: Optional[Set[int]] = None,
    ) -> SentenceScoreResult:
        """
        Accent-aware convenience wrapper: resolves `user_id`'s target-
        accent config, then scores against it via config_override -
        without mutating self.config, so a single shared PronunciationPipeline
        instance stays safe to reuse across concurrent requests for
        different users.
        """
        effective_config = await self.resolve_config_for_user(user_id)
        return self.score_sentence(
            target_sentence,
            attempts,
            accent_calibration=accent_calibration,
            accessibility_exempt_indices=accessibility_exempt_indices,
            config_override=effective_config,
        )

    def score_sentence(
        self,
        target_sentence: str,
        attempts: Sequence[Optional[WordAttempt]],
        accent_calibration: bool = False,
        accessibility_exempt_indices: Optional[Set[int]] = None,
        config_override: Optional[PronunciationPipelineConfig] = None,
    ) -> SentenceScoreResult:
        """
        Score one read-aloud attempt of `target_sentence` and classify each
        target word into a ColorTier.

        Args:
            target_sentence: The sentence the user was asked to read.
            attempts: One entry per word in target_sentence.split(), in
                order. `None` means the word was never attempted (E-01
                omission). An entry with `unscorable=True` means it was
                interrupted by noise/outage (E-04).
            accent_calibration: "Local Accent" toggle state (E-03).
            accessibility_exempt_indices: Word indices whose repetitions
                should NOT count against fluency_score because Story 2's
                accessibility profile is active and attributes that
                disfluency to the user's disclosed condition rather than
                a correctable error. Passed in by accessibility_profile.py
                - this module has no notion of accessibility itself.
            config_override: use this PronunciationPipelineConfig instead
                of self.config for this call only (self.config is never
                mutated). This is how accent-specific scoring is applied
                per call without needing a separate pipeline instance per
                accent - see score_sentence_for_user(). Defaults to None,
                i.e. self.config, exactly as before this parameter existed.

        Returns:
            SentenceScoreResult with one WordScoreResult per target word.
        """
        cfg = config_override or self.config
        target_words = target_sentence.split()
        if len(attempts) != len(target_words):
            raise ValueError(
                f"attempts must have one entry per target word "
                f"({len(target_words)} words, got {len(attempts)} attempts)"
            )
        accessibility_exempt_indices = accessibility_exempt_indices or set()

        word_alignments = [
            {"word": a.word, "start": a.start, "end": a.end, "confidence": a.confidence}
            for a in attempts
            if a is not None and not a.unscorable
        ]
        scored_by_word = {}
        if word_alignments:
            raw = self.scorer.score_pronunciation(
                audio=None, sample_rate=16000, word_alignments=word_alignments, reference_text=target_sentence
            )
            # Map back positionally: PronunciationScorer preserves input order.
            scorable_indices = [i for i, a in enumerate(attempts) if a is not None and not a.unscorable]
            for pos, word_score in zip(scorable_indices, raw["word_scores"]):
                scored_by_word[pos] = word_score

        results: List[WordScoreResult] = []
        penalized_fluency = 100.0
        for i, (target_word, attempt) in enumerate(zip(target_words, attempts)):
            if attempt is None:
                results.append(
                    WordScoreResult(
                        index=i,
                        target_word=target_word,
                        tier=ColorTier.GRAY,
                        strikethrough=True,
                        note="omitted: word was not attempted",
                    )
                )
                continue

            if attempt.unscorable:
                results.append(
                    WordScoreResult(
                        index=i,
                        target_word=target_word,
                        tier=ColorTier.UNSCORABLE,
                        note="unscorable: interrupted by background noise",
                    )
                )
                continue

            word_score = scored_by_word[i]
            final_score = word_score["score"]
            raw_confidence_pct = word_score["confidence"] * 100

            tier, note = self._classify_tier(
                final_score,
                raw_confidence_pct,
                accent_calibration,
                cfg,
                predicted_phonemes=attempt.predicted_phonemes,
                target_phonemes=attempt.target_phonemes,
            )

            results.append(
                WordScoreResult(
                    index=i,
                    target_word=target_word,
                    tier=tier,
                    final_score=final_score,
                    raw_confidence_pct=raw_confidence_pct,
                    note=note,
                )
            )

            if (
                attempt.repetitions >= cfg.stutter_repetition_threshold
                and i not in accessibility_exempt_indices
            ):
                penalized_fluency -= cfg.per_repetition_fluency_penalty

        fluency_score = max(0.0, min(100.0, penalized_fluency))
        retry_recommended = any(w.tier in (ColorTier.RED, ColorTier.UNSCORABLE) for w in results)

        logger.info(
            "Scored sentence %r: %d words, fluency=%.1f, retry_recommended=%s",
            target_sentence, len(results), fluency_score, retry_recommended,
        )

        return SentenceScoreResult(
            target_sentence=target_sentence,
            words=results,
            fluency_score=fluency_score,
            retry_recommended=retry_recommended,
        )

    def _classify_tier(
        self,
        final_score: float,
        raw_confidence_pct: float,
        accent_calibration: bool,
        config: PronunciationPipelineConfig,
        predicted_phonemes: Optional[List[str]] = None,
        target_phonemes: Optional[List[str]] = None,
    ) -> "tuple[ColorTier, str]":
        if final_score >= config.green_min_score:
            return ColorTier.GREEN, ""

        if raw_confidence_pct >= config.mispronunciation_confidence_floor:
            # Phonemes were essentially recognized; the low final score is
            # a timing/duration artifact, i.e. a stress error, not a
            # mispronunciation.
            return ColorTier.ORANGE, "minor stress/timing deviation"

        if accent_calibration and self._is_regional_variant(
            raw_confidence_pct, config, predicted_phonemes, target_phonemes
        ):
            return ColorTier.GREEN, "accepted regional variant (Local Accent)"

        return ColorTier.RED, "mispronounced"

    def _is_regional_variant(
        self,
        raw_confidence_pct: float,
        config: PronunciationPipelineConfig,
        predicted_phonemes: Optional[List[str]] = None,
        target_phonemes: Optional[List[str]] = None,
    ) -> bool:
        """
        E-03 accent calibration heuristic. `config` is whichever
        PronunciationPipelineConfig is active for this call (self.config,
        or an accent-specific one via score_sentence's config_override) -
        so config.regional_variant_tolerant_pairs and
        config.regional_variant_confidence_tolerance both vary per target
        accent when accent-aware scoring is in use.

        Real path (when both predicted_phonemes and target_phonemes are
        supplied on the WordAttempt - not true for any caller yet, see
        WordAttempt's docstring): every substitution-type mismatch from
        self.scorer.get_phoneme_errors() must be in
        config.regional_variant_tolerant_pairs to count as an accepted
        regional variant, rather than a genuine mispronunciation. This is
        the first thing in this pipeline that actually reads
        regional_variant_tolerant_pairs - previously that field was
        declared but unused.

        Fallback (phoneme data unavailable - true today for every
        existing caller): the original conservative stand-in - only treat
        a RED word as an accepted regional variant when its confidence is
        close to (not far below) the mispronunciation floor, i.e.
        plausibly a systematic regional-consonant-stress difference
        rather than an outright wrong phoneme. Tolerance band is
        config.regional_variant_confidence_tolerance. Both paths are
        UNCALIBRATED.
        """
        if predicted_phonemes is not None and target_phonemes is not None:
            errors = self.scorer.get_phoneme_errors(predicted_phonemes, target_phonemes)
            substitution_pairs = [
                frozenset({e["predicted"], e["target"]})
                for e in errors
                if e.get("error_type") == "substitution" and e.get("predicted") and e.get("target")
            ]
            if substitution_pairs:
                return all(pair in config.regional_variant_tolerant_pairs for pair in substitution_pairs)
            # No substitution-type mismatches found (only insertions/
            # deletions, or no mismatches at all) - phoneme data didn't
            # give a clean substitution signal to check against the
            # tolerant-pairs table, so fall through to the confidence-band
            # heuristic below rather than guessing.

        return raw_confidence_pct >= (
            config.mispronunciation_confidence_floor - config.regional_variant_confidence_tolerance
        )
