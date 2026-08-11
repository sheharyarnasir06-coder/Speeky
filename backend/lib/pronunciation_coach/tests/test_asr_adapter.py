import pytest
from lib.pronunciation_coach.asr_adapter import word_timings_to_attempts

def test_happy_path_word_alignment():
    # STT output with {"word", "start", "end"}
    stt_output = [
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "world,", "start": 0.6, "end": 1.0},
    ]
    target = "Hello world"
    
    attempts = word_timings_to_attempts(stt_output, target)
    
    assert len(attempts) == 2
    assert attempts[0].word == "Hello"
    assert attempts[0].start == 0.0
    assert attempts[0].end == 0.5
    assert attempts[0].confidence == 0.5
    
    assert attempts[1].word == "world"
    assert attempts[1].start == 0.6
    assert attempts[1].end == 1.0
    assert attempts[1].confidence == 0.5

def test_missing_word_treated_as_omission():
    stt_output = [
        {"word": "Hello", "start": 0.0, "end": 0.5},
    ]
    target = "Hello beautiful world"
    
    attempts = word_timings_to_attempts(stt_output, target)
    
    assert len(attempts) == 3
    assert attempts[0].word == "Hello"
    assert attempts[1] is None  # Omitted
    assert attempts[2] is None  # Omitted

def test_inserted_words_skipped():
    stt_output = [
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "uh", "start": 0.5, "end": 0.7},
        {"word": "world", "start": 0.8, "end": 1.2},
    ]
    target = "Hello world"
    
    attempts = word_timings_to_attempts(stt_output, target)
    
    assert len(attempts) == 2
    assert attempts[0].word == "Hello"
    assert attempts[1].word == "world"
    assert attempts[1].start == 0.8

def test_punctuation_and_case_insensitivity():
    stt_output = [
        {"word": "it's", "start": 0.0, "end": 0.3},
        {"word": "OKAY.", "start": 0.4, "end": 1.0},
    ]
    target = "It's okay"
    
    attempts = word_timings_to_attempts(stt_output, target)
    
    assert len(attempts) == 2
    assert attempts[0].word == "It's"
    assert attempts[1].word == "okay"

def test_empty_target_or_stt():
    assert word_timings_to_attempts([], "Hello") == [None]
    assert word_timings_to_attempts([{"word": "hi", "start": 0, "end": 1}], "") == []

def test_missing_key_raises_value_error():
    stt_output = [
        {"word": "Hello", "start": 0.0} # Missing end
    ]
    with pytest.raises(ValueError):
        word_timings_to_attempts(stt_output, "Hello")
