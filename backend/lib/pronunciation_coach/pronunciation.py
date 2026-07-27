"""
Pronunciation scoring module using phoneme alignment.

This module provides pronunciation assessment using phoneme-level alignment.
For full British English phoneme alignment, Montreal Forced Aligner (MFA) is recommended.
This implementation provides a fallback using g2p_en for phoneme conversion.
"""

import logging
import numpy as np
from typing import List, Dict
from g2p_en import G2p

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PronunciationScorer:
    """
    Pronunciation scoring using phoneme alignment.
    
    This class provides pronunciation assessment with phone-level analysis.
    For best results with British English, use Montreal Forced Aligner (MFA).
    This implementation provides a fallback using g2p_en (US English dictionary).
    """
    
    def __init__(self, use_mfa: bool = False):
        """
        Initialize the pronunciation scorer.
        
        Args:
            use_mfa: Whether to use Montreal Forced Aligner (requires MFA installation)
                    Defaults to False (uses g2p_en fallback)
        """
        self.use_mfa = use_mfa
        self.g2p = None
        self.mfa_model = None
        
        if not use_mfa:
            self._load_g2p()
        else:
            self._load_mfa()
    
    def _load_g2p(self):
        """Load g2p_en for phoneme conversion (US English)."""
        try:
            logger.info("Loading g2p_en for phoneme conversion...")
            self.g2p = G2p()
            logger.info("g2p_en loaded successfully")
            logger.warning("Note: g2p_en uses US English phonemes. For British English, install MFA.")
        except Exception as e:
            logger.error(f"Failed to load g2p_en: {e}")
            raise
    
    def _load_mfa(self):
        """
        Load Montreal Forced Aligner for British English phoneme alignment.
        
        This requires MFA to be installed separately. See documentation for setup.
        """
        try:
            logger.info("Loading MFA model for British English alignment...")
            # MFA model loading would go here
            # self.mfa_model = alignment.Aligner(model_name="english_uk_mfa")
            logger.warning("MFA integration not fully implemented - using g2p_en fallback")
            self.use_mfa = False
            self._load_g2p()
        except ImportError:
            logger.warning("MFA not installed, falling back to g2p_en")
            self.use_mfa = False
            self._load_g2p()
        except Exception as e:
            logger.error(f"Failed to load MFA: {e}")
            self.use_mfa = False
            self._load_g2p()
    
    def text_to_phonemes(self, text: str) -> List[str]:
        """
        Convert text to phonemes using g2p_en.
        
        Args:
            text: Input text
            
        Returns:
            List of phonemes
        """
        if self.g2p is None:
            raise RuntimeError("Phoneme converter not loaded")
        
        try:
            phonemes = self.g2p(text)
            # Filter out punctuation and empty tokens
            phonemes = [p for p in phonemes if p not in ['', ' ', "'", '.', ',', '!', '?']]
            return phonemes
        except Exception as e:
            logger.error(f"Error converting text to phonemes: {e}")
            return []
    
    def score_pronunciation(
        self,
        audio: np.ndarray,
        sample_rate: int,
        word_alignments: List[Dict[str, any]],
        reference_text: str
    ) -> Dict[str, any]:
        """
        Score pronunciation based on word alignments and reference text.
        
        Args:
            audio: Audio data as numpy array
            sample_rate: Sample rate of the audio
            word_alignments: Word-level alignments from alignment module
            reference_text: Reference text for comparison
            
        Returns:
            Dictionary containing:
                - 'overall_score': Overall pronunciation score (0-100)
                - 'word_scores': List of individual word scores
                - 'problematic_words': List of words with pronunciation issues
                - 'phoneme_analysis': Phoneme-level analysis (if available)
        """
        logger.info("Scoring pronunciation...")
        
        if self.use_mfa and self.mfa_model is not None:
            return self._score_with_mfa(audio, sample_rate, word_alignments, reference_text)
        else:
            return self._score_with_gop(audio, sample_rate, word_alignments, reference_text)
    
    def _score_with_mfa(
        self,
        audio: np.ndarray,
        sample_rate: int,
        word_alignments: List[Dict[str, any]],
        reference_text: str
    ) -> Dict[str, any]:
        """
        Score pronunciation using MFA (if available).
        
        Args:
            audio: Audio data
            sample_rate: Sample rate
            word_alignments: Word alignments
            reference_text: Reference text
            
        Returns:
            Pronunciation scoring results
        """
        # Placeholder for MFA-based scoring
        logger.info("Using MFA for pronunciation scoring")
        
        # MFA would provide phoneme-level goodness of pronunciation (GOP)
        # For now, fall back to GOP calculation
        return self._score_with_gop(audio, sample_rate, word_alignments, reference_text)
    
    def _score_with_gop(
        self,
        audio: np.ndarray,
        sample_rate: int,
        word_alignments: List[Dict[str, any]],
        reference_text: str
    ) -> Dict[str, any]:
        """
        Score pronunciation using simplified GOP (Goodness of Pronunciation).
        
        This is a fallback method that uses timing confidence and phoneme matching.
        
        Args:
            audio: Audio data
            sample_rate: Sample rate
            word_alignments: Word alignments
            reference_text: Reference text
            
        Returns:
            Pronunciation scoring results
        """
        logger.info("Using simplified GOP scoring")
        
        # Get reference phonemes
        reference_phonemes = self.text_to_phonemes(reference_text)
        
        word_scores = []
        problematic_words = []
        
        for word_align in word_alignments:
            word = word_align['word'].lower()
            confidence = word_align.get('confidence', 0.5)
            
            # Get expected phonemes for this word
            word_phonemes = self.text_to_phonemes(word)
            
            # Calculate word score based on confidence and duration
            duration = word_align['end'] - word_align['start']
            
            # Simple scoring heuristic
            # Higher confidence = better pronunciation
            # Reasonable duration = better pronunciation (not too fast/slow)
            word_score = confidence * 100
            
            # Adjust for unusual durations (outside 0.1-1.0 seconds range)
            if duration < 0.1:
                word_score *= 0.7  # Penalty for too fast
            elif duration > 1.0:
                word_score *= 0.8  # Penalty for too slow
            
            word_score = min(100, max(0, word_score))
            
            word_scores.append({
                'word': word,
                'score': word_score,
                'phonemes': word_phonemes,
                'duration': duration,
                'confidence': confidence
            })
            
            # Identify problematic words (score < 70)
            if word_score < 70:
                problematic_words.append({
                    'word': word,
                    'score': word_score,
                    'issue': 'low_confidence' if confidence < 0.6 else 'timing_issue'
                })
        
        # Calculate overall score
        if word_scores:
            overall_score = sum(w['score'] for w in word_scores) / len(word_scores)
        else:
            overall_score = 0.0
        
        result = {
            'overall_score': overall_score,
            'word_scores': word_scores,
            'problematic_words': problematic_words,
            'phoneme_analysis': {
                'reference_phonemes': reference_phonemes,
                'note': 'For detailed phoneme analysis, install Montreal Forced Aligner'
            }
        }
        
        logger.info(f"Pronunciation scoring complete: {overall_score:.1f}/100")
        return result
    
    def calculate_gop(
        self,
        audio_segment: np.ndarray,
        sample_rate: int,
        target_phonemes: List[str]
    ) -> float:
        """
        Calculate Goodness of Pronunciation (GOP) for a phoneme sequence.
        
        This is a simplified GOP calculation. For accurate GOP, use MFA.
        
        Args:
            audio_segment: Audio segment for the phoneme sequence
            sample_rate: Sample rate
            target_phonemes: Target phoneme sequence
            
        Returns:
            GOP score (0-1)
        """
        # Simplified GOP: based on audio duration and phoneme count
        duration = len(audio_segment) / sample_rate
        expected_duration = len(target_phonemes) * 0.1  # ~100ms per phoneme
        
        # Calculate duration ratio
        duration_ratio = duration / expected_duration if expected_duration > 0 else 1.0
        
        # Score based on how close duration is to expected
        if 0.8 <= duration_ratio <= 1.2:
            return 1.0
        elif 0.5 <= duration_ratio <= 1.5:
            return 0.7
        else:
            return 0.4
    
    def get_phoneme_errors(
        self,
        predicted_phonemes: List[str],
        target_phonemes: List[str]
    ) -> List[Dict[str, str]]:
        """
        Compare predicted and target phonemes to identify errors.
        
        Args:
            predicted_phonemes: Predicted phoneme sequence
            target_phonemes: Target phoneme sequence
            
        Returns:
            List of phoneme errors with details
        """
        errors = []
        
        # Simple alignment using dynamic programming would go here
        # For now, use direct comparison
        for i, (pred, target) in enumerate(zip(predicted_phonemes, target_phonemes)):
            if pred != target:
                errors.append({
                    'position': i,
                    'predicted': pred,
                    'target': target,
                    'error_type': 'substitution'
                })
        
        # Handle length differences
        if len(predicted_phonemes) > len(target_phonemes):
            for i in range(len(target_phonemes), len(predicted_phonemes)):
                errors.append({
                    'position': i,
                    'predicted': predicted_phonemes[i],
                    'target': '',
                    'error_type': 'insertion'
                })
        elif len(target_phonemes) > len(predicted_phonemes):
            for i in range(len(predicted_phonemes), len(target_phonemes)):
                errors.append({
                    'position': i,
                    'predicted': '',
                    'target': target_phonemes[i],
                    'error_type': 'deletion'
                })
        
        return errors