"""
Base-currency normalization (GAP-05 / US-203 E-04). No live FX-rate provider
is connected anywhere in this codebase — `STUB_FX_RATES` is a small set of
illustrative rates, clearly flagged, standing in for a real provider (e.g.
exchangerate-api.io, Stripe FX, openexchangerates.org) until one is wired in.
The normalization math itself and `COUNTRY_CURRENCY_MAP` are real.
"""

from typing import Dict, Optional

BASE_CURRENCY = "USD"

# ISO 4217 -> units of USD per 1 unit of that currency. STUB DATA — replace with
# a real FX-rate API response. Refreshed (still from this same stub) by
# lib/scheduler.py's currency_rate_refresh_job so CurrencyRate rows exist to
# query, but the underlying numbers are illustrative, not live.
STUB_FX_RATES: Dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "PKR": 0.0036,
    "INR": 0.012,
    "CAD": 0.73,
    "AUD": 0.65,
    "JPY": 0.0067,
    "AED": 0.27,
    "SGD": 0.74,
}

# Small illustrative country -> currency map for the regions this stub covers.
# Real implementation should come from a proper i18n/billing locale table.
COUNTRY_CURRENCY_MAP: Dict[str, str] = {
    "US": "USD",
    "GB": "GBP",
    "DE": "EUR",
    "FR": "EUR",
    "PK": "PKR",
    "IN": "INR",
    "CA": "CAD",
    "AU": "AUD",
    "JP": "JPY",
    "AE": "AED",
    "SG": "SGD",
}


def currency_for_country(country_code: Optional[str]) -> str:
    if not country_code:
        return BASE_CURRENCY
    return COUNTRY_CURRENCY_MAP.get(country_code.upper(), BASE_CURRENCY)


def normalize_to_base_currency(amount: float, currency_code: str, rates: Optional[Dict[str, float]] = None) -> float:
    """E-04: converts `amount` (in `currency_code`) into BASE_CURRENCY so
    cross-region revenue comparisons never mix units. Falls back to treating
    an unknown currency as already-base rather than raising — a bad/missing
    rate shouldn't take down the whole comparison chart, it should just not
    distort it (1:1 is the least-wrong default for an unrecognized code)."""
    rates = rates if rates is not None else STUB_FX_RATES
    rate = rates.get(currency_code.upper(), 1.0)
    return round(amount * rate, 2)
