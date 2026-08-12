"""
Tests for US-152: Code-Switch Personal Word List Store.
Uses InMemoryKvStore so no DB or network needed.
"""

import pytest
from lib.kv_store import InMemoryKvStore
from lib.code_switch.word_list_store import CodeSwitchWordListStore


@pytest.fixture
def store():
    return CodeSwitchWordListStore(store=InMemoryKvStore())


# ── Happy path ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_word_is_logged(store):
    await store.log_word("user1", "jaldi", "quickly", "Please do it jaldi.")
    words = await store.get_list("user1")
    assert len(words) == 1
    assert words[0].word == "jaldi"
    assert words[0].english_equivalent == "quickly"
    assert words[0].frequency == 1
    assert "Please do it jaldi." in words[0].context_sentences


@pytest.mark.asyncio
async def test_frequency_increments_on_repeat(store):
    await store.log_word("user1", "jaldi", "quickly", "Do it jaldi.")
    await store.log_word("user1", "jaldi", "quickly", "Jaldi karo!")
    words = await store.get_list("user1")
    assert words[0].frequency == 2


@pytest.mark.asyncio
async def test_sorted_by_frequency_desc(store):
    """E-02: Most frequent word must appear first."""
    await store.log_word("user1", "jaldi", "quickly", "Sentence 1")
    await store.log_word("user1", "jaldi", "quickly", "Sentence 2")
    await store.log_word("user1", "theek", "okay", "Theek hai.")
    words = await store.get_list("user1")
    assert words[0].word == "jaldi"  # freq=2
    assert words[1].word == "theek"  # freq=1


# ── E-01: Ignore / Remove ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ignore_word_excludes_from_list(store):
    """E-01: Ignored word must not appear in get_list()."""
    await store.log_word("user1", "karachi", "Karachi", "I am from Karachi.")
    found = await store.ignore_word("user1", "karachi")
    assert found is True
    words = await store.get_list("user1")
    assert len(words) == 0  # ignored, excluded by default


@pytest.mark.asyncio
async def test_ignored_word_not_re_logged(store):
    """E-01: Once ignored, subsequent log_word calls are silently skipped."""
    await store.log_word("user1", "karachi", "Karachi", "From Karachi.")
    await store.ignore_word("user1", "karachi")
    await store.log_word("user1", "karachi", "Karachi", "Karachi again.")
    # frequency must still be 1 — not incremented after ignore
    words = await store.get_list("user1", include_ignored=True)
    assert words[0].frequency == 1


@pytest.mark.asyncio
async def test_remove_word_deletes_entirely(store):
    """E-01: Hard-deleted word must be gone even with include_ignored=True."""
    await store.log_word("user1", "jaldi", "quickly", "Jaldi karo.")
    found = await store.remove_word("user1", "jaldi")
    assert found is True
    words = await store.get_list("user1", include_ignored=True)
    assert len(words) == 0


@pytest.mark.asyncio
async def test_ignore_nonexistent_word_returns_false(store):
    found = await store.ignore_word("user1", "nonexistent")
    assert found is False


@pytest.mark.asyncio
async def test_remove_nonexistent_word_returns_false(store):
    found = await store.remove_word("user1", "nonexistent")
    assert found is False


# ── E-03: Empty list ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_list_returns_empty(store):
    """E-03: User who never code-switched gets an empty list."""
    words = await store.get_list("user_never_switched")
    assert words == []


# ── E-04: Multiple context sentences ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_contexts_stored_per_word(store):
    """E-04: Same word in different sentences must show each context."""
    await store.log_word("user1", "jaldi", "quickly", "Do it jaldi.")
    await store.log_word("user1", "jaldi", "fast", "Jaldi finish karo.")  # different meaning
    words = await store.get_list("user1")
    assert len(words[0].context_sentences) == 2


# ── Multi-user isolation ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_words_are_isolated_per_user(store):
    await store.log_word("user1", "jaldi", "quickly", "Sentence.")
    words_user2 = await store.get_list("user2")
    assert words_user2 == []
