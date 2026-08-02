"""
Pure regional-segmentation math (GAP-05 / US-203). No DB, no I/O — everything
here takes plain data in and returns a decision, directly unit-testable
(backend/tests/test_regional_math.py) without a live database, matching this
repo's pure-logic test convention (see lib/anomaly_math.py, lib/recurrence.py).
"""

from dataclasses import dataclass
from typing import List, Optional

UNKNOWN_REGION = "UNKNOWN"
OTHER_REGIONS = "OTHER"


@dataclass
class RegionRow:
    region_code: str
    value: float
    sample_size: int


@dataclass
class FoldedRegionRow:
    region_code: str
    value: float
    sample_size: int
    is_bucket: bool  # True for the synthetic "Other Regions" row


def fold_low_volume_regions(rows: List[RegionRow], min_sample_size: int) -> List[FoldedRegionRow]:
    """E-01: a region with fewer users than the minimum reporting threshold is
    suppressed as an individual breakdown and rolled into one "Other Regions"
    bucket (a sample-size-weighted average, not a naive mean — a 3-user region
    shouldn't move the bucket as much as a 40-user one). UNKNOWN_REGION is
    never folded here — it's kept as its own labeled row (E-02 handles it
    separately) so it's never silently merged into "Other"."""
    kept: List[FoldedRegionRow] = []
    low_volume = [r for r in rows if r.region_code != UNKNOWN_REGION and r.sample_size < min_sample_size]
    for r in rows:
        if r.region_code == UNKNOWN_REGION or r.sample_size >= min_sample_size:
            kept.append(FoldedRegionRow(r.region_code, r.value, r.sample_size, is_bucket=False))

    if low_volume:
        total_sample = sum(r.sample_size for r in low_volume)
        weighted_value = (
            sum(r.value * r.sample_size for r in low_volume) / total_sample if total_sample else 0.0
        )
        kept.append(FoldedRegionRow(OTHER_REGIONS, round(weighted_value, 4), total_sample, is_bucket=True))

    return kept


def bucket_unknown(region_code: Optional[str]) -> str:
    """E-02: a null/missing region (signup-flow bug, or simply not populated
    yet) buckets under UNKNOWN_REGION rather than being dropped from totals."""
    return region_code if region_code else UNKNOWN_REGION


def detect_spoofing_flag(
    declared_share: float,
    ip_inferred_share: Optional[float],
    threshold: float = 0.25,
) -> Optional[str]:
    """E-03: flags a region whose declared-locale share diverges abnormally
    from its IP-inferred-location share — a caveat, not a hard exclusion, so
    the data is still shown but visibly marked as less reliable.

    No IP-geolocation service is connected in this codebase (checked — same
    gap `reconciliation_service.py` has for payment providers, solved the
    same way): `ip_inferred_share` is None until a real geolocation signal is
    wired in, which this function treats as "insufficient signal" — it never
    fabricates a flag from data that doesn't exist.
    """
    if ip_inferred_share is None:
        return None
    divergence = abs(declared_share - ip_inferred_share)
    if divergence < threshold:
        return None
    return (
        f"Declared-locale share ({declared_share:.0%}) diverges from IP-inferred "
        f"share ({ip_inferred_share:.0%}) by {divergence:.0%} — treat this region's "
        f"figures as a lower-confidence estimate."
    )
