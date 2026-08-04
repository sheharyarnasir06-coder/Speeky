"""
praat-parselmouth wrapper — pitch (F0) and intensity contours, a simplified syllable-
nuclei count (rhythm proxy, modeled after the de Jong & Wempe Praat script), and the
multi-voice heuristic.

Nothing else in this repo does acoustic/phonetic analysis, so this is the one new
dependency introduced for the Accent Assessment dimensions (stress/rhythm/intonation/
clarity) that word-alignment alone can't produce. Multi-voice detection here is an
explicit best-effort heuristic (large pitch discontinuities between voiced runs), not
real speaker diarization — see lib/speech_config.py's MULTI_VOICE_* thresholds.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import parselmouth

from lib.speech_config import SpeechConfig


@dataclass
class ProsodyData:
    pitch_times: np.ndarray
    pitch_hz: np.ndarray  # 0.0 at unvoiced frames -- RAW Praat output, octave-jump-prone
    # Same shape/zeros as pitch_hz, but each voiced frame folded to within an octave of
    # the recording's median pitch (see _fold_to_octave). Consumers that care about a
    # single speaker's actual pitch *contour* (e.g. detect_multiple_voices' run-to-run
    # comparison) should read this, not pitch_hz -- raw pitch_hz still exists for
    # consumers measuring genuine variance/flatness (recording_engine's synthetic-pitch
    # check, accent_calibration_service's breakdown fallback), where octave-folding would
    # artificially shrink the very variance they're measuring.
    pitch_hz_corrected: np.ndarray
    intensity_times: np.ndarray
    intensity_db: np.ndarray
    mean_pitch_hz: float
    pitch_range_semitones: float
    syllable_nuclei_times: List[float]  # seconds — Accent Assessment's rhythm dimension
    speech_duration_s: float

    @property
    def syllable_count(self) -> int:
        return len(self.syllable_nuclei_times)


def _fold_to_octave(values: np.ndarray, reference: float) -> np.ndarray:
    """Halve/double each value until within ~6 semitones (factor ~1.41) of `reference`.
    Corrects Praat's octave-jump artifact (halving/doubling F0 on creaky sentence-final
    voicing) -- `values` must be all-positive; `reference` must be > 0."""
    corrected = values.astype(np.float64).copy()
    hi, lo = reference * 1.41, reference / 1.41
    for _ in range(4):  # covers up to 4 octaves of error
        corrected = np.where(corrected > hi, corrected / 2.0, corrected)
        corrected = np.where(corrected < lo, corrected * 2.0, corrected)
    return corrected


def analyze(waveform: np.ndarray, sample_rate: int) -> ProsodyData:
    sound = parselmouth.Sound(waveform.astype(np.float64), sampling_frequency=sample_rate)
    pitch = sound.to_pitch()
    intensity = sound.to_intensity()

    pitch_hz = pitch.selected_array["frequency"]
    pitch_times = pitch.xs()
    intensity_db = intensity.values[0]
    intensity_times = intensity.xs()

    voiced_mask = pitch_hz > 0
    voiced = pitch_hz[voiced_mask]
    mean_pitch = float(np.mean(voiced)) if voiced.size else 0.0
    pitch_hz_corrected = pitch_hz.copy()
    if voiced.size >= 2 and mean_pitch > 0:
        # Octave-correct before measuring spread. Praat's pitch tracker octave-jumps
        # (halving/doubling F0) on creaky sentence-final voicing, which used to blow the
        # 5-95 percentile range up to ~30 st on a plainly-read sample — saturating the
        # downstream tone score. Fold each voiced frame to within a semitone-octave of the
        # MEDIAN (robust to those jumps), then measure the 5-95 percentile spread.
        median_pitch = float(np.median(voiced))
        if median_pitch > 0:
            corrected = _fold_to_octave(voiced, median_pitch)
            pitch_hz_corrected[voiced_mask] = corrected
            semitones = 12.0 * np.log2(corrected / median_pitch)
        else:
            semitones = 12.0 * np.log2(voiced / mean_pitch)
        pitch_range = float(np.percentile(semitones, 95) - np.percentile(semitones, 5))
    else:
        pitch_range = 0.0

    syllable_nuclei_times = _find_syllable_nuclei(intensity_db, intensity_times, pitch_hz, pitch_times)

    return ProsodyData(
        pitch_times=pitch_times,
        pitch_hz=pitch_hz,
        pitch_hz_corrected=pitch_hz_corrected,
        intensity_times=intensity_times,
        intensity_db=intensity_db,
        mean_pitch_hz=mean_pitch,
        pitch_range_semitones=pitch_range,
        syllable_nuclei_times=syllable_nuclei_times,
        speech_duration_s=len(waveform) / sample_rate,
    )


def _find_syllable_nuclei(
    intensity_db: np.ndarray,
    intensity_times: np.ndarray,
    pitch_hz: np.ndarray,
    pitch_times: np.ndarray,
    min_dip_db: float = 2.0,
    min_peak_above_floor_db: float = 2.0,
) -> List[float]:
    """Simplified syllable-nuclei proxy: intensity local maxima, at least min_dip_db
    above the surrounding floor, that land on a voiced pitch frame. Not a full phonetic
    syllabifier — good enough as a rhythm signal (inter-syllable timing), which is all
    the Accent Assessment rhythm dimension needs. Returns nuclei timestamps (seconds),
    not just a count, so rhythm scoring can measure timing regularity."""
    if intensity_db.size < 3:
        return []

    floor = float(np.percentile(intensity_db, 10))
    peak_indices = []
    for i in range(1, len(intensity_db) - 1):
        if intensity_db[i] > intensity_db[i - 1] and intensity_db[i] >= intensity_db[i + 1]:
            if intensity_db[i] - floor >= min_peak_above_floor_db:
                peak_indices.append(i)

    nuclei_times: List[float] = []
    last_peak_time: Optional[float] = None
    for i in peak_indices:
        t = intensity_times[i]
        idx = min(np.searchsorted(pitch_times, t), len(pitch_hz) - 1)
        is_voiced = pitch_hz[idx] > 0 or (idx > 0 and pitch_hz[idx - 1] > 0)
        if not is_voiced:
            continue
        if last_peak_time is not None and (intensity_db[i] - floor) < min_dip_db:
            continue
        nuclei_times.append(float(t))
        last_peak_time = t
    return nuclei_times


def word_stress_peak_position(prosody: ProsodyData, word_start: float, word_end: float) -> Optional[float]:
    """Fractional position (0.0-1.0) of the intensity peak within [word_start, word_end].
    None if no intensity frames fall in that span (e.g. a skipped word)."""
    mask = (prosody.intensity_times >= word_start) & (prosody.intensity_times <= word_end)
    if not np.any(mask):
        return None
    duration = word_end - word_start
    if duration <= 0:
        return None
    times_in_word = prosody.intensity_times[mask]
    intensity_in_word = prosody.intensity_db[mask]
    peak_idx = int(np.argmax(intensity_in_word))
    return float((times_in_word[peak_idx] - word_start) / duration)


def _voiced_runs(pitch_hz: np.ndarray) -> List[Tuple[int, int]]:
    runs = []
    in_run = False
    start = 0
    for i, v in enumerate(pitch_hz):
        voiced = v > 0
        if voiced and not in_run:
            start, in_run = i, True
        elif not voiced and in_run:
            runs.append((start, i))
            in_run = False
    if in_run:
        runs.append((start, len(pitch_hz)))
    return runs


def detect_multiple_voices(prosody: ProsodyData, config: SpeechConfig) -> bool:
    """Best-effort heuristic flag: large pitch jumps between consecutive voiced runs,
    only evaluated once there are enough runs to be meaningful. NOT real diarization.

    Runs shorter than multi_voice_min_run_seconds are dropped first -- Praat's pitch
    tracker occasionally produces a 1-2 frame octave-jump artifact (a spurious ~570Hz
    blip lasting 20ms) even on clean single-speaker audio, and a jump in/out of that
    blip alone easily exceeds the semitone threshold. Confirmed against a real single-
    speaker recording (tests/test_recording_engine.py's fixture-based coverage can't
    catch this class of bug -- it only showed up running the real model against real
    audio) that was otherwise a false positive before this filter.

    Reads pitch_hz_corrected (octave-folded to the recording's median), not raw
    pitch_hz -- a longer-lived octave-jump blip (a whole creaky-voiced run, not just the
    1-2 frame case the min-run-seconds filter above already catches) still reads as a
    ~1-octave jump on raw pitch and combines with genuine phrase-boundary pitch
    variation to clear the semitone threshold on real single-speaker audio. Trade-off:
    folding is anchored to the whole recording's median, so a genuine second speaker
    within ~6-11 semitones of the dominant speaker (plausible, short of a full octave)
    could now go undetected where it wouldn't have before -- accepted, since a false
    rejection of a real single speaker is the more costly failure here.
    """
    runs = _voiced_runs(prosody.pitch_hz_corrected)
    significant_runs = [
        (start, end)
        for start, end in runs
        if (prosody.pitch_times[end - 1] - prosody.pitch_times[start]) >= config.multi_voice_min_run_seconds
    ]
    if len(significant_runs) < config.multi_voice_min_voiced_segments:
        return False

    medians = []
    for start, end in significant_runs:
        voiced_vals = prosody.pitch_hz_corrected[start:end]
        voiced_vals = voiced_vals[voiced_vals > 0]
        if voiced_vals.size:
            medians.append(float(np.median(voiced_vals)))

    for a, b in zip(medians, medians[1:]):
        if a <= 0 or b <= 0:
            continue
        jump_semitones = abs(12.0 * np.log2(b / a))
        if jump_semitones >= config.multi_voice_pitch_jump_semitones:
            return True
    return False


def rhythm_coefficient_of_variation(nuclei_times: List[float]) -> Optional[float]:
    """Coefficient of variation (std/mean) of inter-syllable intervals — lower means
    more rhythmically regular speech. None if there aren't enough syllable nuclei to
    measure (short/sparse reading). Accent Assessment maps this through a config-driven
    scoring curve in services/accent_assessment_service.py — this stays a raw metric."""
    intervals = [b - a for a, b in zip(nuclei_times, nuclei_times[1:])]
    if len(intervals) < 2:
        return None
    mean = float(np.mean(intervals))
    if mean <= 0:
        return None
    return float(np.std(intervals)) / mean
