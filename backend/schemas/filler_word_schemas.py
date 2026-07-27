"""
Filler Word Tracking & Visualization Schemas (PSC-US-08)
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class FillerWordMarkerSchema(BaseModel):
    """Timeline / waveform marker indicating when a filler word was used."""
    word: str = Field(description="The filler word or phrase detected")
    start_time: Optional[float] = Field(None, description="Start timestamp in seconds")
    end_time: Optional[float] = Field(None, description="End timestamp in seconds")
    position: int = Field(description="Word or character index position in transcript")
    confidence: float = Field(default=1.0, description="Acoustic or NLP detection confidence (0.0 - 1.0)")
    category: str = Field(default="filler", description="Marker type indicator")


class FillerWordFrequencySchema(BaseModel):
    """Specific filler word frequency breakdown."""
    word: str = Field(description="Filler word or phrase name")
    count: int = Field(ge=0, description="Number of occurrences")


class FillerWordAnalysisSchema(BaseModel):
    """Complete response payload for GET /sessions/{session_id}/filler-words."""
    session_id: str
    speech_type: Optional[str] = None
    total_filler_count: int = Field(ge=0, description="Total filler words detected")
    flawless_delivery: bool = Field(default=False, description="E-03: Flag indicating zero filler words used")
    badge: Optional[str] = Field(None, description="Badge indicator for flawless delivery ('Flawless Delivery')")
    filler_frequencies: Dict[str, int] = Field(default_factory=dict, description="Frequency breakdown dictionary e.g. {'um': 12, 'like': 5}")
    filler_counts: List[FillerWordFrequencySchema] = Field(default_factory=list, description="Frequency list for UI charts")
    timeline_markers: List[FillerWordMarkerSchema] = Field(default_factory=list, description="Timeline/waveform markers with timestamps")
    actionable_tip: str = Field(description="Actionable advice about using silence/pausing instead of filler words")
    analysis_summary: str = Field(description="Human-readable summary of filler word performance")
