"""Tests for Story 2 (lib/pronunciation_coach/accessibility_profile.py)."""

from lib.pronunciation_coach.accessibility_profile import (
    ACCESSIBILITY_PROFILE_LABEL,
    STANDARD_PROFILE_LABEL,
    TRIGGER_CAUSE_DISFLUENCY,
    TRIGGER_CAUSE_PHONEME_MISPRONUNCIATION,
    AccessibilityProfile,
    AccessibilityProfileStore,
    score_with_accessibility,
    should_trigger_frustration_loop,
)
from lib.pronunciation_coach.pronunciation_pipeline import ColorTier, PronunciationPipeline, WordAttempt


def test_opt_in_and_opt_out_any_time():
    store = AccessibilityProfileStore()
    assert store.get("u1").opted_in is False

    store.set_opt_in("u1", True, disclosed_condition="stutter")
    assert store.get("u1").opted_in is True
    assert store.get("u1").disclosed_condition == "stutter"

    # Opt-out available any time, not just onboarding.
    store.set_opt_in("u1", False)
    assert store.get("u1").opted_in is False


def test_stutter_repetition_exempted_from_fluency_when_opted_in(fake_scorer):
    pipeline = PronunciationPipeline(scorer=fake_scorer)
    profile_in = AccessibilityProfile(user_id="u1", opted_in=True, disclosed_condition="stutter")
    profile_out = AccessibilityProfile(user_id="u2", opted_in=False)

    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95, repetitions=3)]

    with_profile = score_with_accessibility(pipeline, "hello", attempts, profile_in)
    without_profile = score_with_accessibility(pipeline, "hello", attempts, profile_out)

    assert with_profile.fluency_score == 100.0  # exempted
    assert without_profile.fluency_score < 100.0  # standard penalty applies (E-03 unchanged)


def test_genuine_phoneme_error_still_flagged_when_accessibility_active(fake_scorer):
    """Acceptance criteria: must still accurately flag genuine phoneme-level errors."""
    pipeline = PronunciationPipeline(scorer=fake_scorer)
    profile = AccessibilityProfile(user_id="u1", opted_in=True, disclosed_condition="stutter")

    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.2, repetitions=1)]

    result = score_with_accessibility(pipeline, "hello", attempts, profile)

    assert result.words[0].tier == ColorTier.RED


def test_feedback_language_does_not_imply_error_for_exempted_word(fake_scorer):
    pipeline = PronunciationPipeline(scorer=fake_scorer)
    profile = AccessibilityProfile(user_id="u1", opted_in=True, disclosed_condition="stutter")
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95, repetitions=3)]

    result = score_with_accessibility(pipeline, "hello", attempts, profile)

    note = result.words[0].note.lower()
    assert "not scored as an error" in note
    for blaming_word in ("mispronounced", "mistake", "wrong", "incorrect"):
        assert blaming_word not in note


def test_e04_session_labeling_distinguishes_profiles(fake_scorer):
    pipeline = PronunciationPipeline(scorer=fake_scorer)
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95)]

    accessibility_result = score_with_accessibility(
        pipeline, "hello", attempts, AccessibilityProfile(user_id="u1", opted_in=True)
    )
    standard_result = score_with_accessibility(
        pipeline, "hello", attempts, AccessibilityProfile(user_id="u2", opted_in=False)
    )

    assert accessibility_result.scoring_profile == ACCESSIBILITY_PROFILE_LABEL
    assert standard_result.scoring_profile == STANDARD_PROFILE_LABEL


def test_e01_undisclosed_pattern_nudge_shown_only_once():
    store = AccessibilityProfileStore()

    first = store.maybe_surface_nudge("u1", undisclosed_pattern_detected=True)
    second = store.maybe_surface_nudge("u1", undisclosed_pattern_detected=True)

    assert first is not None
    assert second is None  # not repeated even though pattern persists


def test_e01_no_nudge_without_pattern_or_already_opted_in():
    store = AccessibilityProfileStore()
    assert store.maybe_surface_nudge("u1", undisclosed_pattern_detected=False) is None

    store.set_opt_in("u2", True)
    assert store.maybe_surface_nudge("u2", undisclosed_pattern_detected=True) is None


def test_e02_frustration_loop_disabled_for_disfluency_when_opted_in():
    profile = AccessibilityProfile(user_id="u1", opted_in=True, disclosed_condition="stutter")

    assert should_trigger_frustration_loop(profile, TRIGGER_CAUSE_DISFLUENCY, consecutive_failures=10) is False
    assert should_trigger_frustration_loop(profile, TRIGGER_CAUSE_PHONEME_MISPRONUNCIATION, consecutive_failures=5) is True


def test_e02_frustration_loop_unaffected_when_not_opted_in():
    profile = AccessibilityProfile(user_id="u1", opted_in=False)

    assert should_trigger_frustration_loop(profile, TRIGGER_CAUSE_DISFLUENCY, consecutive_failures=5) is True
