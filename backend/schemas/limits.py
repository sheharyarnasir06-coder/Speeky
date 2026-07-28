"""Shared input-size limits for user text that reaches an LLM.

Why this exists: the provider bills and rate-limits by token, and the per-minute budget
is shared by every user of the deployment. An uncapped field let a single request ask
for tens of thousands of tokens — measured: a 198k-character payload requested 45,582
tokens against a 6,000 TPM limit. The provider rejected it with HTTP 413, but the
request still burned latency, and repeated attempts would starve every other learner.

Capping at the schema boundary means Pydantic rejects oversized input with a clean 400
before any handler, DB read, or provider call happens.

Values are deliberately generous for the product's actual shape (a spoken answer, an
email draft, a short script) while staying far below any single-request token budget.
"""

# ~2k characters ≈ 500 tokens: a long interview answer or email draft still fits.
MAX_UTTERANCE_CHARS = 2_000

# Longer-form drafts (presentation notes, multi-paragraph coaching submissions).
MAX_SUBMISSION_CHARS = 8_000

# Short single-line fields (subject lines, topics, context hints).
MAX_SHORT_TEXT_CHARS = 300
