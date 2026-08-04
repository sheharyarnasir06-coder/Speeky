import re
import unicodedata
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from lib import content_safety

# CM-US-03: min/max target vocabulary words per scenario.
MIN_TARGET_VOCAB = 3
MAX_TARGET_VOCAB = 15

# CM-US-01 E-02: character-based stand-in for a token-limit hard stop (roughly
# ~4 chars/token for English, so 4000 chars ≈ 1000 tokens) — good enough to catch
# a runaway prompt without adding a tokenizer dependency just for a counter.
MAX_SYSTEM_PROMPT_CHARS = 4000

DIFFICULTIES = ("beginner", "intermediate", "advanced")

# CM-US-03 E-03: small curated blocklist for the target-vocabulary field specifically
# (distinct from services.scenario_service._PROFANITY, which classifies a LEARNER's
# live roleplay turns — this one moderates what an ADMIN types into a word list).
_VOCAB_PROFANITY = {
    "fuck", "fucking", "shit", "bullshit", "bitch", "asshole", "bastard",
    "cunt", "dick", "piss", "slut", "whore", "nigger", "faggot",
}

_VOCAB_WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z '-]{0,38}[A-Za-z]$|^[A-Za-z]$")


class StartScenarioSchema(BaseModel):
    scenario_key: str  # built-in SBL_SCENARIOS key, or "custom:<id>"


class ScenarioTurnSchema(BaseModel):
    message: str = Field(default="", max_length=4000)


def _reject_unsafe_content(v: Optional[str]) -> Optional[str]:
    """CM-US-03: hard, non-bypassable guard — runs on every create/update regardless
    of `quality_acknowledged` (that flag only overrides the LLM's soft quality/
    confidence judgment call, never this heuristic floor). See lib/content_safety."""
    if not v:
        return v
    reasons = content_safety.scan(v)
    if reasons:
        raise ValueError("Rejected — " + "; ".join(reasons) + ".")
    return v


def _clean_target_vocab(v: List[str]) -> List[str]:
    """Shared by CustomScenarioSchema and ScenarioPreviewSchema: trim, drop blanks,
    case-insensitive dedupe (keeps first occurrence — CM-US-03 E-02), block
    profanity (E-03), enforce the 3-15 word band (E-01/E-04), and a light
    sanity check in place of full dictionary spellcheck (letters/spaces/hyphens/
    apostrophes only, 2-40 chars) — no spellcheck dictionary is installed in this
    project, so this catches garbage input without adding one."""
    cleaned: List[str] = []
    seen = set()
    for raw in v:
        word = re.sub(r"\s+", " ", raw.strip())
        if not word:
            continue
        # NFKC + casefold so visually-identical variants (full-width chars, curly vs
        # straight apostrophes, stray internal whitespace, case) collide as the same
        # duplicate rather than sneaking past a plain `.lower()` compare.
        key = unicodedata.normalize("NFKC", word).casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(word)

    if len(cleaned) < MIN_TARGET_VOCAB:
        raise ValueError(f"At least {MIN_TARGET_VOCAB} target vocabulary words are required.")
    if len(cleaned) > MAX_TARGET_VOCAB:
        raise ValueError(f"At most {MAX_TARGET_VOCAB} target vocabulary words are allowed.")

    for word in cleaned:
        if word.lower() in _VOCAB_PROFANITY:
            raise ValueError(f'"{word}" isn\'t allowed in the target vocabulary list.')
        if not _VOCAB_WORD_PATTERN.match(word):
            raise ValueError(f'"{word}" doesn\'t look like a valid word or short phrase.')

    return cleaned


class CustomScenarioSchema(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    category: str  # validated against the live Category taxonomy at the service layer
    persona: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=10, max_length=300)  # shown on the learner's pre-scenario screen
    system_prompt: str = Field(min_length=10, max_length=MAX_SYSTEM_PROMPT_CHARS)
    opening_line: Optional[str] = None
    target_vocab: List[str]
    goal_type: str = "roleplay"  # roleplay | negotiation
    difficulty: str = "intermediate"  # beginner | intermediate | advanced
    safety_mode: bool = False  # breaks character on a medical-emergency phrase
    corporate_tone: bool = True
    tested: bool = False  # CM-US-01: admin ran the sandbox preview this editing session
    # CM-US-02: explicit override for a sub-70 quality score / failed readiness check.
    # Never overrides the CM-US-03 content-safety scan below — that's non-negotiable.
    quality_acknowledged: bool = False

    @field_validator("target_vocab")
    @classmethod
    def clean_target_vocab(cls, v: List[str]) -> List[str]:
        return _clean_target_vocab(v)

    @field_validator("goal_type")
    @classmethod
    def valid_goal_type(cls, v: str) -> str:
        if v not in ("roleplay", "negotiation"):
            raise ValueError('goal_type must be "roleplay" or "negotiation"')
        return v

    @field_validator("difficulty")
    @classmethod
    def valid_difficulty(cls, v: str) -> str:
        if v not in DIFFICULTIES:
            raise ValueError(f'difficulty must be one of {", ".join(DIFFICULTIES)}')
        return v

    _validate_title_safety = field_validator("title")(_reject_unsafe_content)
    _validate_persona_safety = field_validator("persona")(_reject_unsafe_content)
    _validate_intent_safety = field_validator("intent")(_reject_unsafe_content)
    _validate_prompt_safety = field_validator("system_prompt")(_reject_unsafe_content)
    _validate_opening_safety = field_validator("opening_line")(_reject_unsafe_content)


class ScenarioPreviewTurnSchema(BaseModel):
    role: str
    content: str


class ScenarioPreviewSchema(BaseModel):
    """SBL-US-06 E-01 sandbox tester: try a scenario's prompt against a persona
    before publishing it, with no DB row and no learner-facing side effects."""

    persona: str = Field(min_length=1, max_length=120)
    system_prompt: str = Field(min_length=10)
    opening_line: Optional[str] = None
    target_vocab: List[str] = Field(default_factory=list)
    goal_type: str = "roleplay"
    safety_mode: bool = False
    corporate_tone: bool = True
    turns: List[ScenarioPreviewTurnSchema] = Field(default_factory=list)
    message: Optional[str] = None  # omit to just fetch the opening line
    # CM-US-14 (US-198): when the sandbox is run against an already-saved scenario,
    # the run is attributed to it so "sandbox success rate" has real data. Absent
    # for a brand-new unsaved draft, which has no row to attribute to yet.
    scenario_id: Optional[str] = None

    # CM-US-03: the preview sandbox feeds persona/system_prompt straight to the LLM
    # immediately (no save gate at all), so the safety scan applies here too.
    _validate_persona_safety = field_validator("persona")(_reject_unsafe_content)
    _validate_prompt_safety = field_validator("system_prompt")(_reject_unsafe_content)
    _validate_opening_safety = field_validator("opening_line")(_reject_unsafe_content)
