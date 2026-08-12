"""
Tests for wiring lib/accent_assessment/ into pronunciation_pipeline.py:
AccentPronunciationConfigRegistry, PronunciationPipeline.resolve_config_for_user(),
score_sentence_for_user(), and score_sentence()'s config_override parameter.
"""

from lib.accent_assessment.target_accent_selection import TargetAccentSelectionService
from lib.kv_store import InMemoryKvStore
from lib.pronunciation_coach.pronunciation_pipeline import (
    DEFAULT_ACCENT_PRONUNCIATION_CONFIGS,
    AccentPronunciationConfigRegistry,
    ColorTier,
    PronunciationPipeline,
    PronunciationPipelineConfig,
    WordAttempt,
)


# --- AccentPronunciationConfigRegistry: no hardcoding -----------------------

def test_default_registry_has_at_least_two_accent_configs():
    registry = AccentPronunciationConfigRegistry()
    assert len(registry.configs) >= 2
    assert "general_american" in registry.configs
    assert "british_rp" in registry.configs


def test_registry_get_falls_back_to_default_for_unknown_or_none_accent():
    registry = AccentPronunciationConfigRegistry()
    assert registry.get("klingon") is registry.default_config
    assert registry.get(None) is registry.default_config


def test_registry_is_fully_overridable_not_a_fixed_if_else():
    custom_config = PronunciationPipelineConfig(green_min_score=50.0)
    registry = AccentPronunciationConfigRegistry(
        configs={"my_custom_accent": custom_config},
        default_config=custom_config,
    )
    assert registry.get("my_custom_accent").green_min_score == 50.0
    assert "general_american" not in registry.configs  # proves defaults aren't baked in


def test_general_american_and_british_rp_have_different_tolerant_pairs():
    ga = DEFAULT_ACCENT_PRONUNCIATION_CONFIGS["general_american"]
    rp = DEFAULT_ACCENT_PRONUNCIATION_CONFIGS["british_rp"]
    assert ga.regional_variant_tolerant_pairs != rp.regional_variant_tolerant_pairs
    assert frozenset({"T", "D"}) in ga.regional_variant_tolerant_pairs
    assert frozenset({"T", "D"}) not in rp.regional_variant_tolerant_pairs  # flapped-T isn't RP-standard


# --- resolve_config_for_user -------------------------------------------------

async def test_resolve_config_without_registry_returns_self_config(fake_scorer):
    config = PronunciationPipelineConfig(green_min_score=99.0)
    pipeline = PronunciationPipeline(scorer=fake_scorer, config=config)

    resolved = await pipeline.resolve_config_for_user("user1")

    assert resolved is config


async def test_resolve_config_with_no_preference_falls_back_to_self_config(fake_scorer):
    config = PronunciationPipelineConfig(green_min_score=99.0)
    service = TargetAccentSelectionService(store=InMemoryKvStore())
    pipeline = PronunciationPipeline(
        scorer=fake_scorer,
        config=config,
        accent_registry=AccentPronunciationConfigRegistry(),
        accent_selection_service=service,
    )

    resolved = await pipeline.resolve_config_for_user("user_with_no_selection")

    assert resolved is config


async def test_resolve_config_uses_users_selected_accent(fake_scorer):
    service = TargetAccentSelectionService(store=InMemoryKvStore())
    await service.select_target_accent("user1", "british_rp")

    registry = AccentPronunciationConfigRegistry()
    pipeline = PronunciationPipeline(
        scorer=fake_scorer,
        accent_registry=registry,
        accent_selection_service=service,
    )

    resolved = await pipeline.resolve_config_for_user("user1")

    assert resolved is registry.configs["british_rp"]


# --- score_sentence_for_user: end-to-end -------------------------------------

async def test_score_sentence_for_user_applies_accent_specific_tolerance(fake_scorer):
    """
    British RP tolerates ER/AH (non-rhotic reduction) as a regional
    variant; General American does not. Same word, same audio signal,
    different target accent -> different tier.
    """
    service = TargetAccentSelectionService(store=InMemoryKvStore())
    registry = AccentPronunciationConfigRegistry()

    # Low confidence (50 -> below the 60 floor -> RED) but within the
    # confidence-tolerance band, AND a phoneme substitution that's only
    # tolerated under british_rp.
    attempts = [
        WordAttempt(
            word="car",
            start=0.0,
            end=0.3,
            confidence=0.5,
            predicted_phonemes=["K", "AH"],
            target_phonemes=["K", "ER"],
        )
    ]

    await service.select_target_accent("user_ga", "general_american")
    pipeline_ga = PronunciationPipeline(scorer=fake_scorer, accent_registry=registry, accent_selection_service=service)
    result_ga = await pipeline_ga.score_sentence_for_user("user_ga", "car", attempts, accent_calibration=True)

    await service.select_target_accent("user_rp", "british_rp")
    pipeline_rp = PronunciationPipeline(scorer=fake_scorer, accent_registry=registry, accent_selection_service=service)
    result_rp = await pipeline_rp.score_sentence_for_user("user_rp", "car", attempts, accent_calibration=True)

    assert result_ga.words[0].tier == ColorTier.RED  # ER/AH not tolerated under General American
    assert result_rp.words[0].tier == ColorTier.GREEN  # tolerated under British RP


async def test_score_sentence_for_user_does_not_mutate_pipeline_config(fake_scorer):
    """A shared pipeline instance must stay safe across concurrent users - config_override never mutates self.config."""
    service = TargetAccentSelectionService(store=InMemoryKvStore())
    await service.select_target_accent("user1", "neutral_international")

    original_config = PronunciationPipelineConfig()
    pipeline = PronunciationPipeline(
        scorer=fake_scorer,
        config=original_config,
        accent_registry=AccentPronunciationConfigRegistry(),
        accent_selection_service=service,
    )

    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.95)]
    await pipeline.score_sentence_for_user("user1", "hello", attempts)

    assert pipeline.config is original_config  # untouched


# --- score_sentence's config_override: works standalone ----------------------

def test_config_override_changes_classification_for_that_call_only(fake_scorer):
    pipeline = PronunciationPipeline(scorer=fake_scorer)  # default config: green_min_score=80
    attempts = [WordAttempt(word="hello", start=0.0, end=0.3, confidence=0.85)]  # final score 85

    strict_config = PronunciationPipelineConfig(green_min_score=99.0)
    result_overridden = pipeline.score_sentence("hello", attempts, config_override=strict_config)
    result_default = pipeline.score_sentence("hello", attempts)

    assert result_overridden.words[0].tier != ColorTier.GREEN  # 85 < 99 under the stricter override
    assert result_default.words[0].tier == ColorTier.GREEN  # unaffected on the next call
    assert pipeline.config.green_min_score == 80.0  # self.config itself was never touched


# --- Phoneme-based regional-variant path (previously dead code) ------------

def test_phoneme_pair_tolerated_upgrades_to_green(fake_scorer):
    config = PronunciationPipelineConfig(
        regional_variant_tolerant_pairs=frozenset({frozenset({"AA", "AO"})})
    )
    pipeline = PronunciationPipeline(scorer=fake_scorer, config=config)
    attempts = [
        WordAttempt(
            word="caught",
            start=0.0,
            end=0.3,
            confidence=0.3,  # low enough to be RED without accent calibration
            predicted_phonemes=["K", "AO", "T"],
            target_phonemes=["K", "AA", "T"],
        )
    ]

    result = pipeline.score_sentence("caught", attempts, accent_calibration=True)

    assert result.words[0].tier == ColorTier.GREEN
    assert "regional variant" in result.words[0].note


def test_phoneme_pair_not_tolerated_stays_red(fake_scorer):
    config = PronunciationPipelineConfig(regional_variant_tolerant_pairs=frozenset())  # nothing tolerated
    pipeline = PronunciationPipeline(scorer=fake_scorer, config=config)
    attempts = [
        WordAttempt(
            word="caught",
            start=0.0,
            end=0.3,
            confidence=0.3,
            predicted_phonemes=["K", "AO", "T"],
            target_phonemes=["K", "AA", "T"],
        )
    ]

    result = pipeline.score_sentence("caught", attempts, accent_calibration=True)

    assert result.words[0].tier == ColorTier.RED
