from fastapi import APIRouter

from services.rewrite_vocab_service import (
    get_vocab_mastery,
    introduce_vocab,
    refresh_vocab_mastery,
)

router = APIRouter()

# Vocabulary Mastery Tracking (US-160 / PSA-US-08)
router.add_api_route("/introduce", introduce_vocab, methods=["POST"])
router.add_api_route("/refresh", refresh_vocab_mastery, methods=["POST"])
router.add_api_route("/", get_vocab_mastery, methods=["GET"])
