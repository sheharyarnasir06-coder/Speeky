"""
Accent Assessment Shared Profile & Scoring Pipeline.

Provides shared dataclasses, score calculations, and profile history management
for Accent Assessment user stories (ACC-US-04, ACC-US-05).

Ensures all accent baselines and drills share a unified data structure,
and that historical baseline trend data is preserved without silent overwrites.
"""

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NAMESPACE = "accent_profile_pipeline"


@dataclass
class ScoredMetric:
    """Individual scored metric within an accent assessment or drill."""

    metric_name: str
    score: float
    details: Optional[Dict[str, Any]] = None
    audio_clip_id: Optional[str] = None


@dataclass
class AccentAssessmentResult:
    """Complete result of an accent baseline assessment or drill."""

    assessment_id: str
    user_id: str
    timestamp: datetime
    metrics: Dict[str, ScoredMetric]  # Map of metric_name -> ScoredMetric
    overall_score: float
    target_accent_id: str = "general_american"
    assessment_type: str = "baseline"  # "baseline", "scheduled_rebaseline", "manual_refresh", "brand_new_baseline", "drill"
    audio_clip_id: Optional[str] = None
    is_audio_available: bool = True
    is_historical: bool = False
    notice: Optional[str] = None

    def get_metric(self, metric_name: str) -> Optional[ScoredMetric]:
        if metric_name == "overall":
            return ScoredMetric(
                metric_name="overall",
                score=self.overall_score,
                audio_clip_id=self.audio_clip_id,
            )
        return self.metrics.get(metric_name)


@dataclass
class AccentProfile:
    """User accent profile containing complete timestamped baseline history."""

    user_id: str
    target_accent_id: str
    created_at: datetime
    last_assessment_at: datetime
    baselines_history: List[AccentAssessmentResult] = field(default_factory=list)
    drills_history: List[AccentAssessmentResult] = field(default_factory=list)
    dismiss_count: int = 0
    last_dismissed_at: Optional[datetime] = None
    is_reset_baseline: bool = False

    @property
    def current_baseline(self) -> Optional[AccentAssessmentResult]:
        if not self.baselines_history:
            return None
        return self.baselines_history[-1]


def calculate_overall_accent_score(metrics: Dict[str, ScoredMetric]) -> float:
    """Calculate aggregate overall accent score from metric sub-scores."""
    if not metrics:
        return 0.0
    scores = [m.score for m in metrics.values()]
    return round(sum(scores) / len(scores), 2)


def _metric_to_dict(m: ScoredMetric) -> Dict[str, Any]:
    return asdict(m)


def _metric_from_dict(d: Dict[str, Any]) -> ScoredMetric:
    return ScoredMetric(
        metric_name=d["metric_name"],
        score=float(d["score"]),
        details=d.get("details"),
        audio_clip_id=d.get("audio_clip_id"),
    )


def _assessment_to_dict(res: AccentAssessmentResult) -> Dict[str, Any]:
    return {
        "assessment_id": res.assessment_id,
        "user_id": res.user_id,
        "timestamp": res.timestamp,
        "metrics": {k: _metric_to_dict(v) for k, v in res.metrics.items()},
        "overall_score": res.overall_score,
        "target_accent_id": res.target_accent_id,
        "assessment_type": res.assessment_type,
        "audio_clip_id": res.audio_clip_id,
        "is_audio_available": res.is_audio_available,
        "is_historical": res.is_historical,
        "notice": res.notice,
    }


def _assessment_from_dict(d: Dict[str, Any]) -> AccentAssessmentResult:
    metrics = {k: _metric_from_dict(v) for k, v in d.get("metrics", {}).items()}
    return AccentAssessmentResult(
        assessment_id=d["assessment_id"],
        user_id=d["user_id"],
        timestamp=d["timestamp"],
        metrics=metrics,
        overall_score=float(d["overall_score"]),
        target_accent_id=d.get("target_accent_id", "general_american"),
        assessment_type=d.get("assessment_type", "baseline"),
        audio_clip_id=d.get("audio_clip_id"),
        is_audio_available=d.get("is_audio_available", True),
        is_historical=d.get("is_historical", False),
        notice=d.get("notice"),
    )


def _profile_to_dict(profile: AccentProfile) -> Dict[str, Any]:
    return {
        "user_id": profile.user_id,
        "target_accent_id": profile.target_accent_id,
        "created_at": profile.created_at,
        "last_assessment_at": profile.last_assessment_at,
        "baselines_history": [_assessment_to_dict(b) for b in profile.baselines_history],
        "drills_history": [_assessment_to_dict(d) for d in profile.drills_history],
        "dismiss_count": profile.dismiss_count,
        "last_dismissed_at": profile.last_dismissed_at,
        "is_reset_baseline": profile.is_reset_baseline,
    }


def _profile_from_dict(d: Dict[str, Any]) -> AccentProfile:
    return AccentProfile(
        user_id=d["user_id"],
        target_accent_id=d.get("target_accent_id", "general_american"),
        created_at=d["created_at"],
        last_assessment_at=d["last_assessment_at"],
        baselines_history=[_assessment_from_dict(b) for b in d.get("baselines_history", [])],
        drills_history=[_assessment_from_dict(dr) for dr in d.get("drills_history", [])],
        dismiss_count=d.get("dismiss_count", 0),
        last_dismissed_at=d.get("last_dismissed_at"),
        is_reset_baseline=d.get("is_reset_baseline", False),
    )


class AccentProfilePipelineService:
    """
    Manages persistence and pipeline operations for Accent Profiles using lib/kv_store.py.
    """

    def __init__(self, store: Optional[Any] = None):
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            from lib import kv_store

            self._store = kv_store.store
        return self._store

    async def get_profile(self, user_id: str) -> Optional[AccentProfile]:
        """Fetch user accent profile from store."""
        raw = await self.store.get(NAMESPACE, user_id)
        if raw is None:
            return None
        return _profile_from_dict(raw)

    async def save_profile(self, profile: AccentProfile) -> AccentProfile:
        """Save or update user accent profile in store."""
        data = _profile_to_dict(profile)
        existing = await self.store.get(NAMESPACE, profile.user_id)
        if existing is None:
            await self.store.create(NAMESPACE, profile.user_id, data)
        else:
            await self.store.update(NAMESPACE, profile.user_id, data)
        return profile

    async def create_initial_baseline(
        self,
        user_id: str,
        metric_scores: Dict[str, float],
        target_accent_id: str = "general_american",
        timestamp: Optional[datetime] = None,
        audio_clip_id: Optional[str] = None,
    ) -> AccentProfile:
        """Create a new profile with Day 1 initial baseline."""
        now = timestamp or datetime.now(timezone.utc)
        metrics = {
            name: ScoredMetric(metric_name=name, score=score, audio_clip_id=audio_clip_id)
            for name, score in metric_scores.items()
        }
        overall = calculate_overall_accent_score(metrics)
        assessment = AccentAssessmentResult(
            assessment_id=f"assess_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            timestamp=now,
            metrics=metrics,
            overall_score=overall,
            target_accent_id=target_accent_id,
            assessment_type="baseline",
            audio_clip_id=audio_clip_id,
        )

        profile = AccentProfile(
            user_id=user_id,
            target_accent_id=target_accent_id,
            created_at=now,
            last_assessment_at=now,
            baselines_history=[assessment],
        )
        return await self.save_profile(profile)
