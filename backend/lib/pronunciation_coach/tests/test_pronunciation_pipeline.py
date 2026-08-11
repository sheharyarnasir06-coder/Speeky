"""Tests for Story 1 (lib/pronunciation_coach/pronunciation_pipeline.py)."""

import pytest

from lib.pronunciation_coach.pronunciation_pipeline import (
    ColorTier,
    PronunciationPipeline,
    PronunciationPipelineConfig,
    WordAttempt,
)


def make_pipeline(fake_scorer, **config_overrides):
    config = PronunciationPipelineConfig(**config_overrides) if config_overrides else None
    return PronunciationPipeline(scorer=fake_scorer, config=config)


def test_green_for_high_confidence_normal_duration(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95)]

    result = pipeline.score_sentence("hello", attempts)

    assert result.words[0].tier == ColorTier.GREEN


def test_red_for_low_confidence(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.3)]

    result = pipeline.score_sentence("hello", attempts)

    assert result.words[0].tier == ColorTier.RED


def test_orange_for_high_confidence_but_bad_timing():
    """Phonemes recognized fine (confidence high) but duration penalty drags the final score down: stress error, not mispronunciation."""
    from lib.pronunciation_coach.tests.conftest import FakeScorer

    pipeline = PronunciationPipeline(scorer=FakeScorer())
    # confidence 0.9 -> raw 90 (>= mispronunciation floor 60)
    # duration 1.5s (> 1.0) -> *0.8 penalty -> final 72 (< green_min 80)
    attempts = [WordAttempt(word="beautiful", start=0.0, end=1.5, confidence=0.9)]

    result = pipeline.score_sentence("beautiful", attempts)

    word = result.words[0]
    assert word.tier == ColorTier.ORANGE
    assert word.raw_confidence_pct == pytest.approx(90.0)
    assert word.final_score == pytest.approx(72.0)


def test_e01_word_omission_is_gray_with_strikethrough(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95), None]

    result = pipeline.score_sentence("hello world", attempts)

    omitted = result.words[1]
    assert omitted.tier == ColorTier.GRAY
    assert omitted.strikethrough is True


def test_e02_stutter_penalizes_fluency_not_color(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    # Final articulation is perfect (confidence 0.95) but took 3 attempts.
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95, repetitions=3)]

    result = pipeline.score_sentence("hello", attempts)

    assert result.words[0].tier == ColorTier.GREEN  # final articulation scored, not the stutter
    assert result.fluency_score < 100.0  # but fluency score is lowered


def test_e02_single_attempt_no_repetition_no_penalty(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95, repetitions=1)]

    result = pipeline.score_sentence("hello", attempts)

    assert result.fluency_score == 100.0


def test_e03_accent_calibration_upgrades_borderline_red_to_green():
    from lib.pronunciation_coach.tests.conftest import FakeScorer

    pipeline = PronunciationPipeline(scorer=FakeScorer())
    # confidence 0.5 -> raw 50: below floor (60) so normally RED, but within
    # the near-floor tolerance band (60-15=45 <= 50) -> accepted as regional variant.
    attempts = [WordAttempt(word="schedule", start=0.0, end=0.3, confidence=0.5)]

    without_calibration = pipeline.score_sentence("schedule", attempts, accent_calibration=False)
    with_calibration = pipeline.score_sentence("schedule", attempts, accent_calibration=True)

    assert without_calibration.words[0].tier == ColorTier.RED
    assert with_calibration.words[0].tier == ColorTier.GREEN
    assert "regional variant" in with_calibration.words[0].note


def test_e04_noise_marks_unscorable_not_mispronounced(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.1, unscorable=True)]

    result = pipeline.score_sentence("hello", attempts)

    assert result.words[0].tier == ColorTier.UNSCORABLE
    assert result.retry_recommended is True


def test_retry_recommended_only_when_red_or_unscorable_present(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95)]

    result = pipeline.score_sentence("hello", attempts)

    assert result.retry_recommended is False


def test_mismatched_attempts_length_raises(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    with pytest.raises(ValueError):
        pipeline.score_sentence("hello world", [WordAttempt(word="hello", start=0.0, end=0.3)])


def test_retry_focuses_on_red_and_gray_words(fake_scorer):
    pipeline = make_pipeline(fake_scorer)
    attempts = [
        WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95),  # green
        None,  # omitted -> gray
        WordAttempt(word="world", start=0.3, end=0.6, confidence=0.2),  # red
    ]

    result = pipeline.score_sentence("hello there world", attempts)
    retry_words = result.red_or_gray_words()

    assert {w.index for w in retry_words} == {1, 2}
