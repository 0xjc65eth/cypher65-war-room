"""
Unit tests for helpers.enrich_account_ranks — P0-5 audit: the pool account
API omits diff/loyalty/combined ranks, but the leaderboard (same poll)
carries REAL values. The helper backfills them (leaderboard authoritative)
so the Wallet panel shows actual ranks instead of '—' or a client-side guess.

Pure — no DB, no Flask, no HTTP.
"""

import pytest

from helpers import enrich_account_ranks


class TestEnrichAccountRanks:
    def test_fills_missing_ranks_from_leaderboard(self):
        acct = {"metadata": {"block_count": 3}}
        le = {
            "diff_rank": 42,
            "loyalty_rank": 7,
            "combined_score": 1234.0,
            "total_blocks": 15,
        }
        out = enrich_account_ranks(acct, le)
        assert out["diff_rank"] == 42
        assert out["loyalty_rank"] == 7
        assert out["combined_score"] == 1234.0
        # block_count kept from account (not clobbered by leaderboard total)
        assert out["metadata"]["block_count"] == 3

    def test_backfills_block_count_when_account_missing(self):
        acct = {"metadata": {}}
        le = {"diff_rank": 1, "total_blocks": 15}
        out = enrich_account_ranks(acct, le)
        assert out["metadata"]["block_count"] == 15
        assert out["diff_rank"] == 1

    def test_never_overrides_existing_account_values(self):
        # Account already has ranks — leaderboard must NOT win.
        acct = {"diff_rank": "CUSTOM", "loyalty_rank": "CUSTOM", "combined_score": 99.0}
        le = {"diff_rank": 1, "loyalty_rank": 2, "combined_score": 3.0, "total_blocks": 999}
        out = enrich_account_ranks(acct, le)
        assert out["diff_rank"] == "CUSTOM"
        assert out["loyalty_rank"] == "CUSTOM"
        assert out["combined_score"] == 99.0

    def test_alt_case_keys_accepted(self):
        # Backend variants (diffRank / loyaltyRank / combinedScore)
        acct = {"metadata": {}}
        le = {"diffRank": "TOP 10%", "loyaltyRank": "ACTIVE", "combinedScore": 500.5}
        out = enrich_account_ranks(acct, le)
        assert out["diff_rank"] == "TOP 10%"
        assert out["loyalty_rank"] == "ACTIVE"
        assert out["combined_score"] == 500.5

    def test_does_not_mutate_input(self):
        acct = {"metadata": {"block_count": 1}}
        snapshot = dict(acct)
        enrich_account_ranks(acct, {"diff_rank": 5, "total_blocks": 9})
        assert acct == snapshot  # pure: original untouched

    def test_none_account_returns_none(self):
        assert enrich_account_ranks(None, {"diff_rank": 1}) is None

    def test_missing_leaderboard_returns_account_unchanged(self):
        acct = {"metadata": {"block_count": 2}}
        assert enrich_account_ranks(acct, None) is acct

    def test_rank_difficulty_alias(self):
        # Block-hunt path uses rankDifficulty
        acct = {"metadata": {}}
        le = {"rankDifficulty": "TOP 25%", "total_blocks": 150}
        out = enrich_account_ranks(acct, le)
        assert out["diff_rank"] == "TOP 25%"
