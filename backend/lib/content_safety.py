"""
CM-US-03: heuristic guard against prompt injection / persona-hijack / PII-solicitation
content in ADMIN-authored scenario fields (system_prompt, persona, intent, opening_line,
title). These fields become a live LLM system prompt served to every learner in that
scenario, so this is a real trust boundary — not just input hygiene.

Regex-based, not LLM-based: runs synchronously in the Pydantic validator (before the row
ever reaches the DB), so it can't be skipped by a slow/misconfigured LLM and can't be
argued around by clever phrasing in the request body. The LLM evaluation in
content_scoring_service is a second, softer layer on top (judgment calls); this layer is
the hard "never allowed" floor.
"""

import re
import unicodedata
from typing import List

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) instructions",
    r"disregard (all |any |the )?(previous|prior|above|earlier|your) instructions",
    r"forget (all |any |the )?(previous|prior|above|earlier|your) instructions",
    r"(reveal|show|print|output|repeat) (your |the )?(system prompt|instructions|prompt)",
    r"you are now (?!role.?playing|acting|pretending)[a-z0-9 ]{0,20}\b(dan|jailbreak)\b",
    r"\bdan\b.{0,15}(unfiltered|unrestricted|uncensored|no restrictions|jailbreak)",
    r"(unfiltered|unrestricted|uncensored|no restrictions|jailbreak).{0,15}\bdan\b",
    r"act as an? (unfiltered|unrestricted|uncensored) ai",
    r"\b(unfiltered|unrestricted|uncensored)\s+ai\b",
    r"\bai\b.{0,15}\bwith no (restrictions|rules|limitations|filters)\b",
    r"\bno (restrictions|rules|limitations)\b.{0,20}\b(ai|assistant|model|bot)\b",
    r"(bypass|ignore|disable) (content |safety )?(policy|filter|guardrails?|restrictions?)",
    r"pretend you have no (rules|restrictions|limitations|guidelines)",
    r"\bjailbreak\b",
    r"no longer bound by",
    r"developer mode",
    r"you have no (ethical|moral) (guidelines|constraints)",
]

_PII_SOLICIT_PATTERNS = [
    r"ask (the |a )?(user|learner|customer|caller) (for|to (provide|share|enter)) (their |his |her )?"
    r"(password|ssn|social security|credit card|card number|cvv|otp|one.time password|pin code|bank account)",
    r"(collect|obtain|request) (their |the user'?s? )?(password|credit card|ssn|social security|bank details)",
]

_HARMFUL_PATTERNS = [
    r"(encourage|instruct|tell) (the )?(user|learner) to (harm|hurt|kill) (himself|herself|themselves|others)",
    r"(instructions?|guide|steps?) (for|on) (making|building|synthesizing) (a )?(bomb|explosive|weapon|illegal drug)",
    r"how to (make|build) (a )?(bomb|explosive|weapon)",
]

_ALL_PATTERNS = (
    [(p, "looks like a prompt-injection / jailbreak attempt") for p in _INJECTION_PATTERNS]
    + [(p, "asks the AI to solicit sensitive personal/financial data from learners") for p in _PII_SOLICIT_PATTERNS]
    + [(p, "contains harmful/dangerous instructions") for p in _HARMFUL_PATTERNS]
)
_COMPILED = [(re.compile(p, re.IGNORECASE), reason) for p, reason in _ALL_PATTERNS]


def _normalize(text: str) -> str:
    # NFKC folds full-width/lookalike unicode into ASCII equivalents, and collapsing
    # whitespace/zero-width chars defeats the simplest "space it out to dodge regex"
    # or "hide behind a zero-width joiner" bypass attempts.
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[​‌‍⁠﻿]", "", text)  # zero-width chars
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def scan(text: str) -> List[str]:
    """Returns a list of human-readable violation reasons; empty if clean."""
    if not text:
        return []
    normalized = _normalize(text)
    reasons = []
    for pattern, reason in _COMPILED:
        if pattern.search(normalized) and reason not in reasons:
            reasons.append(reason)
    return reasons
