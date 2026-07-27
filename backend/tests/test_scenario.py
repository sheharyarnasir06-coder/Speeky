"""Scenario-Based Learning (services/scenario_service) — SBL-US-01..11.

Pure-logic coverage of the exception classifier, vocabulary coverage, and offline
grader. No DB / no network (LLM forced offline via conftest)."""

from lib import prompts
from services import scenario_service as ss

DOCTOR = prompts.SBL_SCENARIOS["doctors_appointment"]
RESTAURANT = prompts.SBL_SCENARIOS["restaurant_dining"]
SUPPORT = prompts.SBL_SCENARIOS["customer_support"]


# ── Turn classifier ─────────────────────────────────────────────────────────
def test_short_message_is_silence():
    assert ss._classify_turn(RESTAURANT, "ok") == "silence"


def test_empty_message_is_silence():
    assert ss._classify_turn(RESTAURANT, "") == "silence"


def test_normal_message_is_ok():
    assert ss._classify_turn(RESTAURANT, "Could I please see the menu?") == "ok"


def test_long_message_is_rambling():
    text = "I would like to explain my whole situation in detail " * 16  # 160 words
    assert ss._classify_turn(RESTAURANT, text) == "rambling"


def test_aggressive_message_flagged():  # reuses coaching_service's phrase bank
    assert ss._classify_turn(SUPPORT, "This is ridiculous, you are incompetent") == "aggressive"


def test_cursing_flagged_as_aggressive():  # _AGGRESSIVE has no swear words, _PROFANITY does
    assert ss._classify_turn(RESTAURANT, "This is such bullshit, fuck this place") == "aggressive"


def test_emergency_only_for_safety_mode_scenario():  # SBL-US-07 E-01
    assert ss._classify_turn(DOCTOR, "I think I'm having a heart attack") == "emergency"
    # Same phrase in a non-safety-mode scenario is not treated as an emergency break.
    assert ss._classify_turn(RESTAURANT, "I think I'm having a heart attack") != "emergency"


def test_is_medical_emergency_detects_phrases():
    assert ss._is_medical_emergency("I can't breathe")
    assert not ss._is_medical_emergency("I have a small headache")


# ── Vocabulary coverage ─────────────────────────────────────────────────────
def test_vocab_coverage_used_and_missing():  # SBL-US-01 TC-02
    turns = [
        {"role": "assistant", "content": "What would you like to order?"},
        {"role": "user", "content": "Could I see the bill and an appetizer recommendation?"},
    ]
    coverage = ss._vocab_coverage(turns, RESTAURANT["target_vocab"])
    assert "bill" in coverage["used"]
    assert "appetizer" in coverage["used"]
    assert "recommendation" in coverage["used"]
    assert "allergic" in coverage["missing"]


def test_vocab_coverage_all_missing_when_bypassed():  # SBL-US-01 E-02 / TC-04
    turns = [{"role": "user", "content": "I want food please"}]
    coverage = ss._vocab_coverage(turns, RESTAURANT["target_vocab"])
    assert coverage["used"] == []
    assert set(coverage["missing"]) == set(RESTAURANT["target_vocab"])


# ── Offline grader (Groq unavailable) ────────────────────────────────────────
def test_offline_grade_negotiation_needs_engagement():  # SBL-US-03 E-02
    one_turn = [{"role": "user", "content": "Sure, store credit is fine."}]
    grade = ss.offline_grade(SUPPORT, one_turn, vocab_used=[])
    assert grade["met_goal"] is False  # gave up after a single turn

    two_turns = [
        {"role": "user", "content": "I'd really prefer a refund, not store credit."},
        {"role": "user", "content": "The item was defective, I have the receipt."},
    ]
    grade = ss.offline_grade(SUPPORT, two_turns, vocab_used=["refund", "receipt"])
    assert grade["met_goal"] is True


def test_offline_grade_roleplay_always_met_goal():
    grade = ss.offline_grade(RESTAURANT, [{"role": "user", "content": "Hi"}], vocab_used=[])
    assert grade["met_goal"] is True


def test_offline_politeness_penalizes_rudeness():
    rude = [{"role": "user", "content": "Give me water now. Whatever."}]
    polite = [{"role": "user", "content": "Could I please have some water, thank you?"}]
    assert ss._offline_politeness(rude) < ss._offline_politeness(polite)


# ── Richer feedback: tips + weakness-flag mapping ───────────────────────────
def test_offline_grade_always_returns_tips_and_empty_polished_line():
    grade = ss.offline_grade(RESTAURANT, [{"role": "user", "content": "Hi"}], vocab_used=[])
    assert grade["tips"] and isinstance(grade["tips"], list)
    assert grade["suggestion"] == grade["tips"][0]
    # Offline mode never fakes a rewrite — that needs an LLM.
    assert grade["polished_line"] == ""
    assert grade["original_line"] == ""


def test_offline_tips_names_missing_vocab():
    tips = ss._offline_tips(RESTAURANT, turns=[], vocab_used=["bill"], met_goal=True)
    joined = " ".join(tips)
    assert "appetizer" in joined or "allergic" in joined or "recommendation" in joined


def test_offline_tips_flags_low_politeness():
    rude_turns = [{"role": "user", "content": "Give me water now. Whatever."}]
    tips = ss._offline_tips(RESTAURANT, rude_turns, vocab_used=RESTAURANT["target_vocab"], met_goal=True)
    assert any("soften" in t.lower() or "could i" in t.lower() for t in tips)


def test_offline_tips_flags_unmet_negotiation_goal():
    tips = ss._offline_tips(SUPPORT, turns=[], vocab_used=SUPPORT["target_vocab"], met_goal=False)
    assert any("push back" in t.lower() for t in tips)


def test_weakness_flag_map_covers_trackable_classifications():
    assert ss._WEAKNESS_FLAG_MAP["rambling"] == "rambling"
    assert ss._WEAKNESS_FLAG_MAP["aggressive"] == "aggressive_tone"
    assert ss._WEAKNESS_FLAG_MAP["silence"] == "prolonged_silence"
    # "emergency"/"ok" are deliberately not tracked as cross-session weaknesses.
    assert "emergency" not in ss._WEAKNESS_FLAG_MAP
    assert "ok" not in ss._WEAKNESS_FLAG_MAP
