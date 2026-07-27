"""
Confidence Score calculation and aggregation system.

This module implements the confidence-first scoring philosophy for Speeky,
prioritizing successful communication over strict grammatical perfection.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Configurable weights for confidence score calculation."""
    fluency: float = 50.0
    vocabulary: float = 30.0
    pronunciation: float = 20.0
    
    def __post_init__(self):
        """Validate weights sum to 100%."""
        total = self.fluency + self.vocabulary + self.pronunciation
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"Weights must sum to 100%, got {total}%")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'fluency': self.fluency,
            'vocabulary': self.vocabulary,
            'pronunciation': self.pronunciation
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ScoringWeights':
        """Create from dictionary."""
        return cls(
            fluency=data.get('fluency', 50.0),
            vocabulary=data.get('vocabulary', 30.0),
            pronunciation=data.get('pronunciation', 20.0)
        )


@dataclass
class WeightChangeLog:
    """Audit log for weight configuration changes."""
    timestamp: datetime
    admin_id: str
    previous_weights: ScoringWeights
    new_weights: ScoringWeights
    reason: str = ""


@dataclass
class SessionScore:
    """Individual session score data."""
    timestamp: datetime
    fluency_score: float
    vocabulary_score: float
    pronunciation_score: Optional[float] = None
    is_text_only: bool = False
    is_complete: bool = True
    is_outlier: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'fluency_score': self.fluency_score,
            'vocabulary_score': self.vocabulary_score,
            'pronunciation_score': self.pronunciation_score,
            'is_text_only': self.is_text_only,
            'is_complete': self.is_complete,
            'is_outlier': self.is_outlier
        }


class ConfidenceScoreEngine:
    """
    Confidence score calculation and aggregation engine.
    
    Implements the confidence-first philosophy where successful communication
    is prioritized over grammatical perfection.
    """
    
    def __init__(self, initial_weights: Optional[ScoringWeights] = None):
        """
        Initialize the confidence score engine.
        
        Args:
            initial_weights: Initial scoring weights (defaults to 50/30/20)
        """
        self.weights = initial_weights or ScoringWeights()
        self.weight_change_log: List[WeightChangeLog] = []
        self.session_history: List[SessionScore] = []
        self.current_confidence_score: float = 0.0
        
        logger.info(f"Confidence Score Engine initialized with weights: {self.weights.to_dict()}")
    
    def update_weights(self, new_weights: ScoringWeights, admin_id: str, reason: str = ""):
        """
        Update scoring weights with audit logging.
        
        Args:
            new_weights: New weight configuration
            admin_id: ID of admin making the change
            reason: Reason for the change
        """
        # Validate new weights
        try:
            ScoringWeights(**new_weights.to_dict())
        except ValueError as e:
            logger.error(f"Invalid weights: {e}")
            raise
        
        # Log the change
        change_log = WeightChangeLog(
            timestamp=datetime.now(),
            admin_id=admin_id,
            previous_weights=self.weights,
            new_weights=new_weights,
            reason=reason
        )
        self.weight_change_log.append(change_log)
        
        # Apply new weights
        self.weights = new_weights
        logger.info(f"Weights updated by {admin_id}: {self.weights.to_dict()}")
    
    def calculate_session_confidence(self, session_score: SessionScore) -> float:
        """
        Calculate confidence score for a single session.
        
        Args:
            session_score: Session score data
            
        Returns:
            Calculated confidence score (0-100)
        """
        if not session_score.is_complete:
            logger.warning("Attempting to calculate confidence for incomplete session")
            return 0.0
        
        if session_score.is_outlier:
            logger.info("Skipping outlier session in confidence calculation")
            return 0.0
        
        # Adjust weights for text-only sessions
        if session_score.is_text_only or session_score.pronunciation_score is None:
            # Normalize fluency and vocabulary to 100%
            total_weight = self.weights.fluency + self.weights.vocabulary
            fluency_weight = (self.weights.fluency / total_weight) * 100
            vocab_weight = (self.weights.vocabulary / total_weight) * 100
            
            confidence = (
                (session_score.fluency_score * fluency_weight / 100) +
                (session_score.vocabulary_score * vocab_weight / 100)
            )
        else:
            # Standard calculation with all three metrics
            confidence = (
                (session_score.fluency_score * self.weights.fluency / 100) +
                (session_score.vocabulary_score * self.weights.vocabulary / 100) +
                (session_score.pronunciation_score * self.weights.pronunciation / 100)
            )
        
        return round(confidence, 2)
    
    def detect_outlier(self, session_score: SessionScore, variance_threshold: float = 50.0) -> bool:
        """
        Detect if a session score is an statistical outlier.
        
        Args:
            session_score: Session score to check
            variance_threshold: Percentage variance threshold for outlier detection
            
        Returns:
            True if session is an outlier
        """
        if len(self.session_history) < 3:
            return False  # Need baseline data
        
        # Calculate average of recent complete sessions
        recent_scores = [
            s for s in self.session_history[-10:] 
            if s.is_complete and not s.is_outlier
        ]
        
        if not recent_scores:
            return False
        
        avg_fluency = sum(s.fluency_score for s in recent_scores) / len(recent_scores)
        avg_vocab = sum(s.vocabulary_score for s in recent_scores) / len(recent_scores)
        
        # Check if current session deviates significantly
        fluency_variance = abs(session_score.fluency_score - avg_fluency) / avg_fluency * 100 if avg_fluency else 0.0
        vocab_variance = abs(session_score.vocabulary_score - avg_vocab) / avg_vocab * 100 if avg_vocab else 0.0
        
        is_outlier = (fluency_variance > variance_threshold or vocab_variance > variance_threshold)
        
        if is_outlier:
            logger.warning(f"Outlier detected: fluency variance {fluency_variance:.1f}%, vocab variance {vocab_variance:.1f}%")
        
        return is_outlier
    
    def add_session_score(self, session_score: SessionScore):
        """
        Add a session score and update aggregate confidence score.
        
        Args:
            session_score: Session score data to add
        """
        # Detect and flag outliers
        session_score.is_outlier = self.detect_outlier(session_score)
        
        # Add to history
        self.session_history.append(session_score)
        
        # Recalculate aggregate confidence score
        self._recalculate_aggregate_confidence()
        
        logger.info(f"Session score added. New confidence score: {self.current_confidence_score}")
    
    def _recalculate_aggregate_confidence(self):
        """
        Recalculate the aggregate confidence score from session history.
        
        Uses weighted average with logarithmic cap to prevent infinite growth.
        """
        complete_sessions = [
            s for s in self.session_history 
            if s.is_complete and not s.is_outlier
        ]
        
        if not complete_sessions:
            self.current_confidence_score = 0.0
            return
        
        # Calculate weighted average of session confidence scores
        session_confidences = [
            self.calculate_session_confidence(s) 
            for s in complete_sessions
        ]
        
        # Apply logarithmic cap for long-term users
        if len(session_confidences) > 100:
            # Use logarithmic scaling to prevent score inflation
            import math
            scaling_factor = math.log(100) / math.log(len(session_confidences))
            avg_confidence = sum(session_confidences) / len(session_confidences)
            self.current_confidence_score = min(100.0, avg_confidence * scaling_factor)
        else:
            self.current_confidence_score = sum(session_confidences) / len(session_confidences)
        
        self.current_confidence_score = round(self.current_confidence_score, 2)
    
    def get_confidence_score(self) -> float:
        """Get current aggregate confidence score."""
        return self.current_confidence_score
    
    def get_confidence_breakdown(self) -> Dict:
        """
        Get plain-language breakdown of confidence score.
        
        Returns:
            Dictionary with score components and explanation
        """
        recent_sessions = self.session_history[-10:] if self.session_history else []
        
        if not recent_sessions:
            return {
                'current_score': 0.0,
                'explanation': 'Complete the Initial Communication Assessment to establish your baseline confidence score.',
                'components': {
                    'fluency': {'weight': self.weights.fluency, 'recent_average': 0},
                    'vocabulary': {'weight': self.weights.vocabulary, 'recent_average': 0},
                    'pronunciation': {'weight': self.weights.pronunciation, 'recent_average': 0}
                }
            }
        
        complete_recent = [s for s in recent_sessions if s.is_complete and not s.is_outlier]
        
        avg_fluency = sum(s.fluency_score for s in complete_recent) / len(complete_recent) if complete_recent else 0
        avg_vocab = sum(s.vocabulary_score for s in complete_recent) / len(complete_recent) if complete_recent else 0
        pron_scores = [s.pronunciation_score for s in complete_recent if s.pronunciation_score is not None]
        avg_pron = sum(pron_scores) / len(pron_scores) if pron_scores else None
        
        # Generate explanation
        if self.current_confidence_score >= 80:
            level = "high"
        elif self.current_confidence_score >= 60:
            level = "moderate"
        else:
            level = "developing"
        
        explanation = (
            f"Your confidence score reflects your {level} ability to communicate effectively. "
            f"Based on your recent sessions, you're performing {'strongly' if level == 'high' else 'well' if level == 'moderate' else 'and building foundational skills'}. "
            f"Keep practicing to improve your fluency and vocabulary usage."
        )
        
        return {
            'current_score': self.current_confidence_score,
            'explanation': explanation,
            'components': {
                'fluency': {
                    'weight': self.weights.fluency,
                    'recent_average': round(avg_fluency, 1),
                    'description': 'Flow and naturalness of speech'
                },
                'vocabulary': {
                    'weight': self.weights.vocabulary,
                    'recent_average': round(avg_vocab, 1),
                    'description': 'Word choice and variety'
                },
                'pronunciation': {
                    'weight': self.weights.pronunciation,
                    'recent_average': round(avg_pron, 1) if avg_pron is not None else None,
                    'description': 'Clarity and accuracy of pronunciation'
                }
            }
        }
    
    def get_weight_history(self) -> List[Dict]:
        """Get audit log of weight changes."""
        return [
            {
                'timestamp': log.timestamp.isoformat(),
                'admin_id': log.admin_id,
                'previous_weights': log.previous_weights.to_dict(),
                'new_weights': log.new_weights.to_dict(),
                'reason': log.reason
            }
            for log in self.weight_change_log
        ]
    
    def export_config(self) -> Dict:
        """Export current configuration for backup/analysis."""
        return {
            'current_weights': self.weights.to_dict(),
            'current_confidence_score': self.current_confidence_score,
            'session_count': len(self.session_history),
            'weight_change_count': len(self.weight_change_log),
            'weight_history': self.get_weight_history()
        }
    
    def import_config(self, config: Dict):
        """Import configuration from backup."""
        if 'current_weights' in config:
            self.weights = ScoringWeights.from_dict(config['current_weights'])
        
        if 'weight_history' in config:
            self.weight_change_log = [
                WeightChangeLog(
                    timestamp=datetime.fromisoformat(log['timestamp']),
                    admin_id=log['admin_id'],
                    previous_weights=ScoringWeights.from_dict(log['previous_weights']),
                    new_weights=ScoringWeights.from_dict(log['new_weights']),
                    reason=log.get('reason', '')
                )
                for log in config['weight_history']
            ]

        logger.info("Configuration imported successfully")


class ConfidenceGrammarAnalyzer:
    """
    Confidence-vs-grammar scoring and feedback (BAS-US-11 / PDF US-21, US-053).

    Reuses FluencyAnalyzer output (speech_rate, pause_count,
    mean_pause_duration, filled_pauses) and GrammarCorrector output
    (error_density, and optionally error_tags — see analyze() docstring).
    Does not re-derive any audio/text signal itself.

    This is a separate, per-turn feedback analyzer from ConfidenceScoreEngine
    above: ConfidenceScoreEngine tracks the aggregate top-line Confidence
    Score across sessions (fluency/vocabulary/pronunciation weighting,
    BAS-US-10), while this class scores a single turn's delivery vs. grammar
    to decide what feedback tier to show (BAS-US-11's "confidence over
    grammar" philosophy). Grammar deliberately does NOT feed into
    ConfidenceScoreEngine's weights per BAS-US-11's acceptance criteria
    ("primary displayed metric must be Confidence Score, not a grammar
    accuracy %").
    """

    # --- Classification thresholds -----------------------------------
    # NOT specified anywhere in the PDF spec (US-053 gives no numeric
    # cutoffs). These are placeholder judgment calls needed to turn a
    # continuous 0-100 score into the label/tier BAS-US-11 requires.
    # TODO: replace with values from whoever owns scoring calibration,
    # or make these configurable (e.g. via a settings/config module)
    # instead of class constants, once one exists.
    UNINTELLIGIBLE_GRAMMAR_THRESHOLD = 20.0
    GRAMMAR_THRESHOLD_DEFAULT = 60.0
    GRAMMAR_THRESHOLD_HIGH_STAKES = 75.0

    # --- E-03: Repeat Grammatical Offender ----------------------------
    # PDF wording: "The user makes the exact same tense error 10 times in
    # a session." Read as >=10 occurrences of the SAME error tag.
    REPEAT_OFFENDER_THRESHOLD = 10

    # Maps a grammar error tag (as produced by whatever tags
    # GrammarCorrector/spaCy analysis attaches to a correction) to the
    # actionable tip surfaced once the threshold is hit. NOT specified
    # in the PDF beyond the single worked example ("Review Past Tense
    # Verbs") — this list is a best-effort starting set and should be
    # extended/confirmed once GrammarCorrector actually emits tags.
    # TODO(E-03 dependency): grammar.py's correct_text() currently only
    # returns error_density (a float), not per-error tags. Until
    # grammar.py is extended to emit something like
    # spacy_analysis['error_tags'] = ['past_tense', ...], callers must
    # pass tags in explicitly via the current_error_tags argument below.
    ERROR_TAG_TIPS = {
        "past_tense": "Review Past Tense Verbs",
        "subject_verb_agreement": "Review Subject-Verb Agreement",
        "article_usage": "Review Article Usage (a/an/the)",
        "preposition": "Review Preposition Choice",
        "plural_form": "Review Plural Noun Forms",
    }

    def analyze(
        self,
        fluency_details: Dict[str, Any],
        grammar_result: Dict[str, Any],
        is_high_stakes_context: bool = False,
        error_history: Optional[List[str]] = None,
        current_error_tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Score confidence vs. grammar and produce BAS-US-11 feedback.

        Args:
            fluency_details: Output of FluencyAnalyzer.analyze_fluency()
                (pipeline.py's result['fluency_details']).
            grammar_result: Output of GrammarCorrector.correct_text()
                (pipeline.py's result['grammar_errors'] source).
            is_high_stakes_context: True for formal/professional practice
                contexts, tightening the grammar threshold (E-02).
            error_history: Optional list of error tags accumulated so far
                THIS session (e.g. ["past_tense", "past_tense", ...]).
                Caller (pipeline.py) is responsible for persisting this
                list across turns — no DB/session layer exists in this
                module set, so it must be passed in and the updated list
                returned each call (see 'error_history' in the result).
            current_error_tags: Error tag(s) detected in THIS turn's
                correction, if the caller has them (e.g. from an
                upstream tagging step). Appended to error_history before
                repeat-offender detection runs. Safe to omit if no
                tagging is available yet.

        Returns:
            Dict with confidence_score, grammar_score, primary_metric
            (always "confidence_score" per BAS-US-11 acceptance criteria),
            grammar_tier, needs_clarification, feedback_hint,
            repeat_offender_tip (None unless E-03 threshold is hit this
            call), and error_history (updated, for the caller to persist).
        """
        confidence_score = self._calculate_confidence_score(fluency_details or {})
        error_density = (grammar_result or {}).get("error_density", 0.0)
        grammar_score = round(100.0 * (1.0 - min(1.0, max(0.0, error_density))), 1)

        grammar_threshold = (
            self.GRAMMAR_THRESHOLD_HIGH_STAKES
            if is_high_stakes_context
            else self.GRAMMAR_THRESHOLD_DEFAULT
        )

        if grammar_score < self.UNINTELLIGIBLE_GRAMMAR_THRESHOLD:
            # E-01: Unintelligible Grammar — break from confidence-first
            # model entirely and ask for clarification.
            grammar_tier = "unintelligible"
            needs_clarification = True
            feedback_hint = "I didn't quite understand that. Are you trying to say...?"
        else:
            needs_clarification = False
            grammar_tier = "minor_polish" if grammar_score >= grammar_threshold else "needs_attention"
            feedback_hint = self._build_feedback_hint(grammar_tier, is_high_stakes_context)

        # E-03: Repeat Grammatical Offender. Runs regardless of tier —
        # even a "minor_polish" session should surface the tip once the
        # same tag has repeated enough, per the PDF's exception handling.
        updated_history = list(error_history) if error_history else []
        if current_error_tags:
            updated_history.extend(current_error_tags)

        repeat_offender_tip = self._detect_repeat_offender(updated_history)

        result = {
            "confidence_score": confidence_score,
            "grammar_score": grammar_score,
            "primary_metric": "confidence_score",
            "grammar_tier": grammar_tier,
            "needs_clarification": needs_clarification,
            "feedback_hint": feedback_hint,
            "repeat_offender_tip": repeat_offender_tip,
            "error_history": updated_history,
        }

        logger.info(
            "Confidence/grammar: confidence=%.1f grammar=%.1f tier=%s repeat_tip=%s",
            confidence_score,
            grammar_score,
            grammar_tier,
            repeat_offender_tip,
        )
        return result

    def _detect_repeat_offender(self, error_history: List[str]) -> Optional[str]:
        """
        E-03: Repeat Grammatical Offender.

        If any single error tag has occurred REPEAT_OFFENDER_THRESHOLD or
        more times in error_history, return one actionable tip for it.
        Importantly, this NEVER touches confidence_score or grammar_score
        — per the PDF resolution, the tip is logged in the feedback
        summary "without tanking the overarching Confidence Score."

        Only the single most frequent qualifying tag is surfaced per call
        (the PDF's example is singular: "a specific actionable tip"), not
        one tip per offending tag, to avoid overwhelming the learner.

        Args:
            error_history: All error tags seen so far this session,
                including the current turn's tags if any.

        Returns:
            An actionable tip string, or None if no tag has hit the
            repeat threshold yet.
        """
        if not error_history:
            return None

        counts = Counter(error_history)
        tag, count = counts.most_common(1)[0]

        if count < self.REPEAT_OFFENDER_THRESHOLD:
            return None

        tip = self.ERROR_TAG_TIPS.get(tag)
        if tip is None:
            # Unknown tag — still surface something rather than silently
            # dropping a qualifying repeat offender.
            tip = f"Review {tag.replace('_', ' ').title()}"

        return tip

    def _calculate_confidence_score(self, fluency_details: Dict[str, Any]) -> float:
        """
        Derive confidence_score (0-100) from audio delivery signals only.

        Reuses the exact point bands FluencyAnalyzer._calculate_overall_score
        already uses for speech_rate (40 pts), pause frequency (20 pts), and
        filled_pauses (20 pts) — no new weights invented. FluencyAnalyzer's
        4th component, lexical_diversity (20 pts), is excluded here per the
        BAS-US-11 design decision: confidence must come from delivery signals,
        not vocabulary/text richness. The remaining 80-point raw total is
        rescaled to 0-100.
        """
        if not fluency_details:
            return 0.0

        raw = 0.0

        # Speech rate (40 pts) — identical bands to fluency.py.
        speech_rate = fluency_details.get("speech_rate", 0.0)
        if 2.0 <= speech_rate <= 4.0:
            raw += 40.0
        elif 1.5 <= speech_rate <= 5.0:
            raw += 30.0
        elif speech_rate > 0:
            raw += 20.0

        # Pause frequency (20 pts) — identical bands to fluency.py.
        pause_count = fluency_details.get("pause_count", 0)
        if pause_count == 0:
            raw += 20.0
        elif pause_count <= 2:
            raw += 15.0
        elif pause_count <= 5:
            raw += 10.0
        else:
            raw += 5.0

        # Filled pauses (20 pts) — identical bands to fluency.py.
        filled_pauses = fluency_details.get("filled_pauses", 0)
        if filled_pauses == 0:
            raw += 20.0
        elif filled_pauses <= 1:
            raw += 15.0
        elif filled_pauses <= 3:
            raw += 10.0
        else:
            raw += 5.0

        # Rescale from /80 (three components) to /100.
        return round(min(100.0, max(0.0, raw / 80.0 * 100.0)), 1)

    def _build_feedback_hint(self, grammar_tier: str, is_high_stakes_context: bool) -> str:
        """Build the confidence-first feedback sentence."""
        if grammar_tier == "minor_polish":
            return "Your message came through clearly. Grammar is solid too — keep it up."

        hint = "Your message came through clearly, with a few grammar points as minor polish."
        if is_high_stakes_context:
            hint += " In professional writing, tighten these up before sending."
        return hint
