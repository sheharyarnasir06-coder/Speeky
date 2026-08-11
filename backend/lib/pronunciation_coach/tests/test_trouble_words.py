"""Tests for Story 4 (lib/pronunciation_coach/trouble_words.py)."""

from lib.pronunciation_coach.pronunciation_pipeline import ColorTier
from lib.pronunciation_coach.trouble_words import TroubleWordsBank, TroubleWordsConfig


def test_word_needs_two_distinct_sessions_not_one_sessions_retries():
    bank = TroubleWordsBank()

    # Two RED results in the SAME session (retries) must not qualify alone.
    bank.record_word_result("u1", "session-1", "vegetable", ColorTier.RED)
    bank.record_word_result("u1", "session-1", "vegetable", ColorTier.RED)

    assert bank.get_active_bank("u1") == []

    # A second, distinct session pushes it over the threshold.
    bank.record_word_result("u1", "session-2", "vegetable", ColorTier.RED)

    active = bank.get_active_bank("u1")
    assert len(active) == 1
    assert active[0].display_word == "vegetable"


def test_trouble_words_viewable_independent_of_session():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "vegetable", ColorTier.RED)
    bank.record_word_result("u1", "s2", "vegetable", ColorTier.RED)

    # No "current session" object needed to view the bank.
    assert len(bank.get_active_bank("u1")) == 1
    assert len(bank.get_archive("u1")) == 1


def test_mastery_after_three_separate_correct_sessions():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "vegetable", ColorTier.RED)
    bank.record_word_result("u1", "s2", "vegetable", ColorTier.RED)
    assert bank.get_active_bank("u1")[0].status == "active"

    bank.record_word_result("u1", "s3", "vegetable", ColorTier.GREEN)
    bank.record_word_result("u1", "s4", "vegetable", ColorTier.GREEN)
    assert bank.get_active_bank("u1")[0].status == "active"  # only 2/3 correct sessions so far

    bank.record_word_result("u1", "s5", "vegetable", ColorTier.GREEN)
    assert bank.get_active_bank("u1") == []  # mastered -> retired from active rotation
    archived = bank.get_archive("u1")
    assert archived[0].status == "mastered"


def test_mastery_requires_separate_sessions_not_same_session_repeats():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "vegetable", ColorTier.RED)
    bank.record_word_result("u1", "s2", "vegetable", ColorTier.RED)

    # Three GREEN reads all within the same session count as ONE session.
    bank.record_word_result("u1", "s3", "vegetable", ColorTier.GREEN)
    bank.record_word_result("u1", "s3", "vegetable", ColorTier.GREEN)
    bank.record_word_result("u1", "s3", "vegetable", ColorTier.GREEN)

    assert bank.get_active_bank("u1")[0].status == "active"  # not mastered yet


def test_e01_mastered_word_regression_resets_counter_and_reactivates():
    bank = TroubleWordsBank()
    for s in ("s1", "s2", "s3", "s4", "s5"):
        tier = ColorTier.RED if s in ("s1", "s2") else ColorTier.GREEN
        bank.record_word_result("u1", s, "vegetable", tier)
    assert bank.get_archive("u1")[0].status == "mastered"

    bank.record_word_result("u1", "s6", "vegetable", ColorTier.RED)

    entry = bank.get_archive("u1")[0]
    assert entry.status == "active"
    assert len(entry.correct_sessions) == 0


def test_e02_active_rotation_capped_full_archive_preserved():
    config = TroubleWordsConfig(active_rotation_cap=2)
    bank = TroubleWordsBank(config=config)

    for i in range(5):
        word = f"word{i}"
        bank.record_word_result("u1", f"s{i}-a", word, ColorTier.RED)
        bank.record_word_result("u1", f"s{i}-b", word, ColorTier.RED)

    assert len(bank.get_active_bank("u1")) == 2
    assert len(bank.get_archive("u1")) == 5


def test_e03_noise_and_service_glitch_causes_excluded_from_bank():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "vegetable", ColorTier.RED, cause="noise")
    bank.record_word_result("u1", "s2", "vegetable", ColorTier.RED, cause="service_glitch")

    assert bank.get_active_bank("u1") == []
    assert bank.get_archive("u1") == []


def test_e04_related_word_forms_grouped_by_pattern_key():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "specific", ColorTier.RED)
    bank.record_word_result("u1", "s2", "specifically", ColorTier.RED)

    active = bank.get_active_bank("u1")
    assert len(active) == 1  # grouped as one trouble entry, not duplicated
    assert active[0].related_words == {"specific", "specifically"}


def test_e04_explicit_phoneme_pattern_key_overrides_heuristic():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "rural", ColorTier.RED, phoneme_pattern_key="R-L-CLUSTER")
    bank.record_word_result("u1", "s2", "literally", ColorTier.RED, phoneme_pattern_key="R-L-CLUSTER")

    active = bank.get_active_bank("u1")
    assert len(active) == 1
    assert active[0].related_words == {"rural", "literally"}


def test_e05_manual_dismissal_removes_from_active_but_reenters_on_new_failure():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "vegetable", ColorTier.RED)
    bank.record_word_result("u1", "s2", "vegetable", ColorTier.RED)
    key = bank.get_active_bank("u1")[0].pattern_key

    bank.dismiss_word("u1", key)
    assert bank.get_active_bank("u1") == []
    assert len(bank.get_dismissal_log("u1")) == 1

    # Fails again later -> re-enters normally.
    bank.record_word_result("u1", "s3", "vegetable", ColorTier.RED)
    active = bank.get_active_bank("u1")
    assert len(active) == 1
    assert active[0].manually_dismissed is False


def test_green_result_for_untracked_word_is_noop():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "hello", ColorTier.GREEN)

    assert bank.get_active_bank("u1") == []
    assert bank.get_archive("u1") == []


def test_get_next_review_word_picks_least_recently_updated():
    bank = TroubleWordsBank()
    bank.record_word_result("u1", "s1", "alpha", ColorTier.RED)
    bank.record_word_result("u1", "s2", "alpha", ColorTier.RED)
    bank.record_word_result("u1", "s3", "beta", ColorTier.RED)
    bank.record_word_result("u1", "s4", "beta", ColorTier.RED)

    next_word = bank.get_next_review_word("u1")
    assert next_word is not None
    assert next_word.display_word == "alpha"  # updated first, so least-recently-updated
