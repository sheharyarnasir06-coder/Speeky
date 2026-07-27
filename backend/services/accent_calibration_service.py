"""
Local Accent Calibration Service (ACC-US-11 & ACC-US-09)

Implements South Asian / Pakistani English regional stress & sub-dialect phonetic shift calibration
(Punjabi, Sindhi, Pashto, Balochi, Kashmiri), low-confidence fallback (E-01),
mixed-dialect speaker revert (E-02), sub-dialect dispute routing (E-03), STT failure fallback (US-11 E-01),
Western Improvement drill conflict check (US-11 E-02), and model loading fallback (US-11 E-03).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from lib import kv_store
from lib.prisma_client import db
from lib.recording_engine import RecordingAnalysis
from lib.speech_config import load_speech_config
from lib.text_alignment import WordStatus
from schemas.pronunciation_schemas import WordResultSchema

logger = logging.getLogger(__name__)

VALID_ACCENT_MODELS = {"generic_global", "south_asian_pakistani"}
VALID_SUB_DIALECTS = {"punjabi", "sindhi", "pashto", "balochi", "kashmiri"}
LOW_CONFIDENCE_SUB_DIALECTS = {"balochi", "kashmiri"}

E01_LOW_CONFIDENCE_WARNING = "Limited data for this dialect — using broader regional model for now"
ACCENT_PREF_NS = "user_accent_preference"
SUB_DIALECT_DISPUTE_NS = "sub_dialect_disputes"

# Common South Asian / Pakistani English phonetic shift substitutions (Urdu / Broad influence)
SOUTH_ASIAN_PHONETIC_SHIFTS = {
    "th": ["d", "t", "dh"],
    "w": ["v"],
    "v": ["w"],
    "p": ["ph"],
    "t": ["th", "d"],
    "d": ["dh", "t"],
}

# Sub-dialect specific phonetic shift maps
PUNJABI_PHONETIC_SHIFTS = {
    "sch": ["isch", "sich"],
    "sk": ["isk", "sik"],
    "st": ["ist", "sit"],
    "sp": ["isp", "sip"],
    "th": ["t", "d"],
    "w": ["v"],
    "v": ["w"],
}

SINDHI_PHONETIC_SHIFTS = {
    "d": ["dh", "dd"],
    "t": ["th", "tt"],
    "th": ["d", "t"],
    "w": ["v"],
    "v": ["w"],
}

PASHTO_PHONETIC_SHIFTS = {
    "p": ["f", "ph"],
    "f": ["p"],
    "th": ["t"],
    "w": ["v"],
    "v": ["w"],
}


async def _is_db_connected() -> bool:
    try:
        return db.is_connected()
    except Exception:
        return False


async def get_user_accent_preference(user_id: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Fetch user's accent model preference and sub-dialect preference from database or KV store.
    
    Returns (accent_model_preference, sub_dialect_preference, notice).
    """
    model_pref = "generic_global"
    sub_pref = None

    if await _is_db_connected():
        try:
            user = await db.user.find_unique(where={"id": user_id})
            if user:
                if user.accentModelPreference:
                    model_pref = user.accentModelPreference
                if user.subDialectPreference:
                    sub_pref = user.subDialectPreference
        except Exception:
            pass
    else:
        entry = await kv_store.store.get(ACCENT_PREF_NS, user_id)
        if entry and isinstance(entry, dict):
            model_pref = entry.get("preference", "generic_global")
            sub_pref = entry.get("sub_dialect", None)

    notice = None
    if model_pref == "south_asian_pakistani" and sub_pref:
        if sub_pref in LOW_CONFIDENCE_SUB_DIALECTS:
            notice = E01_LOW_CONFIDENCE_WARNING
        elif sub_pref in VALID_SUB_DIALECTS:
            notice = f"Sub-dialect calibration ({sub_pref}) active [Beta refinement]."

    return model_pref, sub_pref, notice


async def update_user_accent_preference(
    user_id: str, preference: str, sub_dialect: Optional[str] = None
) -> Tuple[str, Optional[str], Optional[str]]:
    """Update user's accent model preference and optional sub-dialect preference."""
    if preference not in VALID_ACCENT_MODELS:
        raise ValueError(f"Invalid accent model preference: {preference}. Must be one of {VALID_ACCENT_MODELS}")

    if sub_dialect and sub_dialect not in VALID_SUB_DIALECTS:
        raise ValueError(f"Invalid sub-dialect preference: {sub_dialect}. Must be one of {VALID_SUB_DIALECTS}")

    saved_sub = sub_dialect if preference == "south_asian_pakistani" else None

    entry = {"user_id": user_id, "preference": preference, "sub_dialect": saved_sub}
    if await kv_store.store.get(ACCENT_PREF_NS, user_id) is None:
        await kv_store.store.create(ACCENT_PREF_NS, user_id, entry)
    else:
        await kv_store.store.update(ACCENT_PREF_NS, user_id, entry)

    if await _is_db_connected():
        try:
            await db.user.update(
                where={"id": user_id},
                data={
                    "accentModelPreference": preference,
                    "subDialectPreference": saved_sub,
                },
            )
        except Exception as e:
            logger.warning(f"DB accent preference update failed: {e}")

    notice = None
    if preference == "south_asian_pakistani" and saved_sub:
        if saved_sub in LOW_CONFIDENCE_SUB_DIALECTS:
            notice = E01_LOW_CONFIDENCE_WARNING
        elif saved_sub in VALID_SUB_DIALECTS:
            notice = f"Sub-dialect calibration ({saved_sub}) active [Beta refinement]."

    return preference, saved_sub, notice


def check_drill_conflict(drill_type: Optional[str], accent_preference: str) -> Optional[str]:
    """E-02: Check if user attempts a strict Western Accent Improvement drill while Local Calibration is ON."""
    if accent_preference == "south_asian_pakistani" and drill_type in ("western_improvement", "strict_western"):
        return "Conflicting model usage detected. Please temporarily disable Local Accent Calibration for this Western Accent Improvement drill."
    return None


def calibrate_word_results(
    word_results: List[WordResultSchema],
    accent_preference: str,
    sub_dialect_preference: Optional[str] = None,
    drill_type: Optional[str] = None,
) -> Tuple[List[WordResultSchema], Optional[str], str]:
    """Calibrate word results for South Asian / Pakistani English regional stress and sub-dialect shifts (ACC-US-11 / ACC-US-09).
    
    Returns (calibrated_word_results, warning_message, model_used).
    """
    config = load_speech_config()

    # US-11 E-02 Conflict check
    conflict_msg = check_drill_conflict(drill_type, accent_preference)
    if conflict_msg:
        return word_results, conflict_msg, accent_preference

    # US-11 E-03 Model loading failure fallback check
    if accent_preference == "south_asian_pakistani" and not config.local_accent_model_available:
        warning = "Local acoustic model failed to load due to network latency. Defaulting to Generic Global model."
        return word_results, warning, "generic_global"

    if accent_preference != "south_asian_pakistani":
        return word_results, None, "generic_global"

    # ACC-US-09 E-01 Low-confidence sub-dialect fallback check
    warning_msg = None
    effective_sub_dialect = sub_dialect_preference
    if sub_dialect_preference in LOW_CONFIDENCE_SUB_DIALECTS:
        warning_msg = E01_LOW_CONFIDENCE_WARNING
        effective_sub_dialect = None  # Fallback to broad south_asian_pakistani model

    # Select appropriate shift map
    if effective_sub_dialect == "punjabi":
        sub_shifts = PUNJABI_PHONETIC_SHIFTS
    elif effective_sub_dialect == "sindhi":
        sub_shifts = SINDHI_PHONETIC_SHIFTS
    elif effective_sub_dialect == "pashto":
        sub_shifts = PASHTO_PHONETIC_SHIFTS
    else:
        sub_shifts = SOUTH_ASIAN_PHONETIC_SHIFTS

    calibrated: List[WordResultSchema] = []
    for w in word_results:
        w_copy = w.model_copy()
        
        # 1. Accept regional stress shifts
        if w_copy.status == WordStatus.STRESS_ERROR.value:
            w_copy.status = WordStatus.CORRECT.value

        # 2. Accept regional / sub-dialect phonetic shift substitutions
        elif w_copy.status == WordStatus.MISPRONOUNCED.value:
            target_lower = w_copy.word.lower()
            if any(shift_key in target_lower for shift_key in sub_shifts):
                if w_copy.confidence is not None and w_copy.confidence >= 0.35:
                    w_copy.status = WordStatus.CORRECT.value

        calibrated.append(w_copy)

    model_used = f"south_asian_pakistani:{effective_sub_dialect}" if effective_sub_dialect else "south_asian_pakistani"
    
    if effective_sub_dialect and not warning_msg:
        warning_msg = f"Sub-dialect calibration ({effective_sub_dialect}) active [Beta refinement]."

    return calibrated, warning_msg, model_used


def handle_stt_breakdown_fallback(analysis: RecordingAnalysis) -> Tuple[bool, Optional[str], float]:
    """US-11 E-01: Detect extreme dialect distortion breaking STT transcriber and fall back to phonetic clarity scoring.
    
    Returns (has_breakdown, warning_message, phonetic_clarity_score).
    """
    if not analysis.transcript or len(analysis.words) == 0:
        pitch_sd = 10.0
        if analysis.prosody and len(analysis.prosody.pitch_hz) > 5:
            import numpy as np
            voiced = [f for f in analysis.prosody.pitch_hz if f > 0]
            if len(voiced) > 5:
                pitch_sd = float(np.std(voiced))

        phonetic_clarity = round(max(30.0, min(85.0, 100.0 - pitch_sd * 2.0)), 2)
        warning = "Extreme dialect distortion detected breaking STT transcriber. Falling back to phonetic clarity scoring. Please try speaking a bit slower."
        return True, warning, phonetic_clarity

    return False, None, 0.0


async def submit_sub_dialect_dispute(user_id: str, dispute_reason: Optional[str] = None) -> Dict[str, str]:
    """ACC-US-09 E-03: Route sub-dialect misclassification complaint to dispute mechanism.
    
    Reverts sub-dialect tolerance to broad 'south_asian_pakistani' model while retaining all prior score history.
    """
    await update_user_accent_preference(user_id, preference="south_asian_pakistani", sub_dialect=None)
    dispute_id = f"dsp_{uuid.uuid4().hex}"
    entry = {
        "user_id": user_id,
        "dispute_id": dispute_id,
        "reason": dispute_reason or "sub_dialect_misclassification",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "resolved_reverted_to_broad_model",
    }
    await kv_store.store.create(SUB_DIALECT_DISPUTE_NS, dispute_id, entry)

    return {
        "dispute_id": dispute_id,
        "status": "resolved",
        "message": "Sub-dialect dispute logged and resolved. Reverted to broad regional model ('south_asian_pakistani') tolerance while retaining all prior score history.",
        "accent_model_preference": "south_asian_pakistani",
        "sub_dialect_preference": None,
    }
