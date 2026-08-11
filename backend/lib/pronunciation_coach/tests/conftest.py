"""
Shared test fixtures for the pronunciation pipeline test suite.

FakeScorer intentionally mirrors PronunciationScorer._score_with_gop's
exact formula (lib/pronunciation_coach/pronunciation.py) so tests exercise realistic
scoring math without requiring g2p_en's NLTK data downloads (which this
machine doesn't have - see the "how to run" instructions). It is a
test-only stand-in injected via PronunciationPipeline(scorer=...); the
real pronunciation.py file is never modified or bypassed in production
use.
"""

import pytest


class FakeScorer:
    def score_pronunciation(self, audio, sample_rate, word_alignments, reference_text):
        word_scores = []
        for wa in word_alignments:
            confidence = wa.get("confidence", 0.5)
            duration = wa["end"] - wa["start"]
            score = confidence * 100
            if duration < 0.1:
                score *= 0.7
            elif duration > 1.0:
                score *= 0.8
            score = min(100, max(0, score))
            word_scores.append(
                {
                    "word": wa["word"],
                    "score": score,
                    "phonemes": [],
                    "duration": duration,
                    "confidence": confidence,
                }
            )
        overall = sum(w["score"] for w in word_scores) / len(word_scores) if word_scores else 0.0
        return {
            "overall_score": overall,
            "word_scores": word_scores,
            "problematic_words": [],
            "phoneme_analysis": {"reference_phonemes": [], "note": "fake scorer for tests"},
        }

    def get_phoneme_errors(self, predicted_phonemes, target_phonemes):
        errors = []
        for i, (pred, target) in enumerate(zip(predicted_phonemes, target_phonemes)):
            if pred != target:
                errors.append({"position": i, "predicted": pred, "target": target, "error_type": "substitution"})
        if len(predicted_phonemes) > len(target_phonemes):
            for i in range(len(target_phonemes), len(predicted_phonemes)):
                errors.append({"position": i, "predicted": predicted_phonemes[i], "target": "", "error_type": "insertion"})
        elif len(target_phonemes) > len(predicted_phonemes):
            for i in range(len(predicted_phonemes), len(target_phonemes)):
                errors.append({"position": i, "predicted": "", "target": target_phonemes[i], "error_type": "deletion"})
        return errors


@pytest.fixture
def fake_scorer():
    return FakeScorer()
