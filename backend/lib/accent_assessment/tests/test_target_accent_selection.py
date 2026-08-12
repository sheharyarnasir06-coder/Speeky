"""Tests for ACC-US-03 (lib/accent_assessment/target_accent_selection.py).

Uses lib.kv_store.InMemoryKvStore (the same in-memory stand-in the rest of
this backend's KvEntry-backed services swap in for tests) injected
directly into TargetAccentSelectionService, so no DB connection is needed.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.kv_store import InMemoryKvStore
from lib.accent_assessment.target_accent_selection import (
    DEFAULT_TARGET_ACCENT_ID,
    TargetAccentOption,
    TargetAccentRegistry,
    TargetAccentSelectionService,
    describe_combined_guidance,
    describe_scoring_shift,
)


def make_service(**kwargs) -> TargetAccentSelectionService:
    return TargetAccentSelectionService(store=InMemoryKvStore(), **kwargs)


# --- Registry: no hardcoding ------------------------------------------------

def test_default_registry_supports_at_least_two_options():
    registry = TargetAccentRegistry()
    assert len(registry.list_options()) >= 2
    assert registry.is_supported("general_american")
    assert registry.is_supported("british_rp")


def test_registry_is_fully_overridable_not_a_fixed_enum():
    custom = TargetAccentRegistry(
        options={
            "singapore_english": TargetAccentOption(
                id="singapore_english", label="Singapore English", description="test"
            ),
        },
        closest_fallback={},
        default_id="singapore_english",
    )
    assert custom.is_supported("singapore_english")
    assert not custom.is_supported("general_american")  # proves defaults aren't baked in


def test_registry_rejects_empty_options_or_bad_default():
    with pytest.raises(ValueError):
        TargetAccentRegistry(options={})
    with pytest.raises(ValueError):
        TargetAccentRegistry(default_id="not_a_real_id")


def test_closest_supported_known_unsupported_maps_to_configured_fallback():
    registry = TargetAccentRegistry()
    resolved = registry.closest_supported("australian_english")
    assert resolved.id == "british_rp"


def test_closest_supported_totally_unknown_falls_back_to_default():
    registry = TargetAccentRegistry()
    resolved = registry.closest_supported("klingon")
    assert resolved.id == DEFAULT_TARGET_ACCENT_ID


def test_closest_fallback_mapping_itself_is_overridable():
    registry = TargetAccentRegistry(closest_fallback={"australian_english": "neutral_international"})
    resolved = registry.closest_supported("australian_english")
    assert resolved.id == "neutral_international"


# --- Happy path: first selection, then a switch -----------------------------

async def test_first_selection_has_no_previous_accent_and_is_not_flagged():
    service = make_service()
    result = await service.select_target_accent("user1", "general_american")

    assert result.accent.id == "general_american"
    assert result.was_unsupported_request is False
    assert result.history_entry.previous_accent_id is None
    assert result.history_entry.note is None  # nothing to "changed from" yet
    assert result.is_mid_history_switch is False

    pref = await service.get_preference("user1")
    assert pref.current_accent_id == "general_american"
    assert len(pref.history) == 1


async def test_switch_never_overwrites_prior_history_entries():
    service = make_service()
    await service.select_target_accent("user1", "general_american")
    result = await service.select_target_accent("user1", "british_rp")

    assert result.accent.id == "british_rp"
    assert result.history_entry.previous_accent_id == "general_american"
    assert result.history_entry.note == f"Target accent changed on {datetime.now(timezone.utc).date().isoformat()}"

    history = await service.get_history("user1")
    assert len(history) == 2  # first entry preserved, not overwritten
    assert history[0].accent_id == "general_american"
    assert history[1].accent_id == "british_rp"

    pref = await service.get_preference("user1")
    assert pref.current_accent_id == "british_rp"  # current state only reflects the latest


# --- E-01: mid-history switch flag ------------------------------------------

async def test_e01_switch_after_threshold_is_flagged_mid_history():
    service = make_service(mid_history_threshold_days=90)
    long_ago = datetime.now(timezone.utc) - timedelta(days=200)

    await service.select_target_accent("user1", "general_american", tracking_started_at=long_ago)
    result = await service.select_target_accent("user1", "british_rp", tracking_started_at=long_ago)

    assert result.is_mid_history_switch is True
    assert "changed on" in result.history_entry.note


async def test_e01_switch_before_threshold_is_not_flagged():
    service = make_service(mid_history_threshold_days=90)
    recently = datetime.now(timezone.utc) - timedelta(days=10)

    await service.select_target_accent("user1", "general_american", tracking_started_at=recently)
    result = await service.select_target_accent("user1", "british_rp", tracking_started_at=recently)

    assert result.is_mid_history_switch is False
    assert result.history_entry.note is not None  # still always logged/annotated


async def test_e01_threshold_is_overridable_not_a_magic_number():
    service = make_service(mid_history_threshold_days=10)
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=15)

    await service.select_target_accent("user1", "general_american", tracking_started_at=ten_days_ago)
    result = await service.select_target_accent("user1", "british_rp", tracking_started_at=ten_days_ago)

    assert result.is_mid_history_switch is True  # would be False under the 90-day default


async def test_e01_without_tracking_started_at_never_flagged():
    service = make_service()
    await service.select_target_accent("user1", "general_american")
    result = await service.select_target_accent("user1", "british_rp")

    assert result.is_mid_history_switch is False


# --- E-02: combined guidance with Local Calibration -------------------------

def test_e02_combined_guidance_mentions_both_settings_independently():
    registry = TargetAccentRegistry()
    accent = registry.get("british_rp")

    guidance_on = describe_combined_guidance(accent, local_calibration_active=True)
    guidance_off = describe_combined_guidance(accent, local_calibration_active=False)

    assert "British RP" in guidance_on
    assert "on" in guidance_on
    assert "off" in guidance_off
    assert guidance_on != guidance_off


# --- E-03: unsupported target requested -------------------------------------

async def test_e03_unsupported_request_falls_back_and_says_coming_soon():
    service = make_service()
    result = await service.select_target_accent("user1", "australian_english")

    assert result.was_unsupported_request is True
    assert result.accent.id == "british_rp"  # configured closest fallback, never the raw request
    assert "coming soon" in result.fallback_message.lower()

    pref = await service.get_preference("user1")
    assert pref.current_accent_id == "british_rp"  # never silently applies the unsupported id
    assert pref.history[0].accent_id == "british_rp"


async def test_e03_never_silently_applies_unsupported_id():
    service = make_service()
    result = await service.select_target_accent("user1", "klingon")

    assert result.accent.id != "klingon"
    assert result.was_unsupported_request is True
    assert result.fallback_message is not None


# --- Confirmation message (happy-path step 2) -------------------------------

def test_confirmation_message_reflects_the_selected_accent():
    registry = TargetAccentRegistry()
    message = describe_scoring_shift(registry.get("general_american"))
    assert "General American" in message
