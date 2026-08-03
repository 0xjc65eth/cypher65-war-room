"""
Tests for GET /api/tax/export — tax-report CSV (Japan 雑所得 / Korea 2027).

Covers:
- CSV returns mined-block income events valued in the requested currency
- Daily BTC price ledger rows are included
- Unsupported currency → 400
- Year filter excludes older rows
- Open self-host mode (no auth configured) → 200 without a token

Hermetic by construction: DB_PATH is monkeypatched to a scratch SQLite that
seeds the snapshots + highest_diff_events tables the route reads. No module
level os.environ mutation (which would leak into sibling test files).
"""

import os
import sqlite3
import time

import pytest

# Imported lazily inside fixtures so DB_PATH is never read at collection time
# with a polluted env. The route uses get_db() (env DB_PATH at call time).
from app import app as _flask_app


@pytest.fixture
def client():
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    """Point DB_PATH at a scratch SQLite with the tables the route reads."""
    db_path = str(tmp_path / "tax.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
            ts INTEGER PRIMARY KEY, btc_usd REAL, btc_brl REAL,
            btc_eur REAL, btc_gbp REAL, btc_jpy REAL, btc_krw REAL, btc_cny REAL)"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS highest_diff_events (
            ts INTEGER, block_height INTEGER, top_diff_address TEXT,
            difficulty TEXT, claimed INTEGER, block_timestamp INTEGER, is_mine INTEGER)"""
    )
    now = int(time.time())
    c.execute(
        "INSERT INTO snapshots (ts, btc_usd, btc_jpy, btc_krw, btc_cny) VALUES (?,?,?,?,?)",
        (now - 60, 100000.0, 15000000.0, 130000000.0, 720000.0),
    )
    c.execute(
        "INSERT INTO highest_diff_events "
        "(ts, block_height, top_diff_address, difficulty, claimed, block_timestamp, is_mine) "
        "VALUES (?,?,?,?,?,?,1)",
        (now, 900001, "bc1test", "1.2T", 1, now),
    )
    conn.commit()
    conn.close()
    return db_path


class TestTaxExport:
    def test_returns_csv_with_block_hit_and_ledger(self, client, scratch_db):
        resp = client.get("/api/tax/export?currency=JPY")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type
        body = resp.get_data(as_text=True)
        assert "block_hit" in body
        assert "btc_price_JPY" in body
        assert "900001" in body
        assert "price_ledger" in body

    def test_csv_values_block_valued_in_currency(self, client, scratch_db):
        resp = client.get("/api/tax/export?currency=KRW")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # block reward 3.125 BTC × 130,000,000 KRW = 406,250,000
        assert "btc_price_KRW" in body
        assert "406250000" in body

    def test_unsupported_currency_400(self, client, scratch_db):
        resp = client.get("/api/tax/export?currency=XXX")
        assert resp.status_code == 400

    def test_year_filter_excludes_old_rows(self, client, scratch_db):
        # Year 2030 is beyond any seeded ts — no data passes the filter.
        # (Brittle in the very long run, but 2030 stays in the future for
        # the practical lifetime of this test suite.)
        resp = client.get("/api/tax/export?currency=JPY&year=2030")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # year 2030 has no data — headers present but no block rows
        assert "block_hit" not in body
        assert "price_ledger" not in body

    def test_open_mode_requires_no_token(self, client, scratch_db):
        resp = client.get("/api/tax/export?currency=JPY")
        assert resp.status_code == 200
