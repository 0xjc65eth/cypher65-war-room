"""
CYPHER65 // AI Operator — unit tests
=====================================
Covers services/ai_operator.py (12% → target ≥80%):
  - build_system_prompt: empty snapshot, full snapshot, fleet, alerts
  - _build_messages
  - _fmt_hashrate / _fmt_diff / _fmt_age edge cases
  - stream_response: no API key, HTTP error, timeout, connection error,
    success stream with text + tool calls (suggest_action), malformed lines
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from services import ai_operator
from services.ai_operator import (
    build_system_prompt,
    _build_messages,
    _fmt_hashrate,
    _fmt_diff,
    _fmt_age,
    stream_response,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. build_system_prompt
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildSystemPrompt:
    def test_empty_snapshot(self):
        prompt = build_system_prompt({})
        assert "CYPHER65 AI Operator" in prompt
        assert "N/A" in prompt  # worker name/id fallback
        assert "CAPABILITIES" in prompt
        assert "CONSTRAINTS" in prompt

    def test_full_snapshot_populates_sections(self):
        snap = {
            "worker": {
                "name": "w1",
                "id": "dev-1",
                "hashrate": 15e12,
                "bestDifficulty": "2.5P",
                "lastSubmission": "999",
            },
            "pool": {"hashrate": 300e12, "workers": 12, "lastBlock": "900000"},
            "network": {"difficulty": "120T", "height": 900000},
            "btc_price": {"usd": 63125},
            "proximity": {
                "pct_of_network_cur": 0.000123,
                "expected_time_human": "3 days",
                "chance_per_share_label": "1 in 4,567",
            },
            "account": {"total_diff": "5P"},
            "axe_fleet": [
                {
                    "name": "a1",
                    "status": "ONLINE",
                    "temperature": 65,
                    "hashrate": 3.5e12,
                },
                {"name": "a2", "status": "OFFLINE"},
            ],
            "alerts_recent": [
                {"severity": "CRIT", "message": "worker offline"},
            ],
        }
        prompt = build_system_prompt(snap)
        assert "Worker hashrate" in prompt
        assert "Best difficulty" in prompt
        assert "Last share" in prompt
        assert "Fleet: 1/2 devices online" in prompt
        assert "a1: ONLINE" in prompt
        assert "65°C" in prompt
        assert "a2: OFFLINE" in prompt
        assert "Active alerts: 1" in prompt
        assert "[CRIT] worker offline" in prompt
        assert "Historical best-share / target ratio" in prompt
        assert "Model mean block interval (not a countdown)" in prompt

    def test_empty_axe_fleet_no_fleet_line(self):
        prompt = build_system_prompt({"axe_fleet": []})
        assert "Fleet:" not in prompt

    def test_proximity_none_values_skipped(self):
        prompt = build_system_prompt(
            {
                "proximity": {
                    "pct_of_network_cur": None,
                    "expected_time_human": None,
                    "chance_per_share_label": None,
                },
            }
        )
        assert "Historical best-share / target ratio" not in prompt
        assert "Model mean block interval" not in prompt


# ═══════════════════════════════════════════════════════════════════════════
# 2. _build_messages
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildMessages:
    def test_message_structure(self):
        msgs = _build_messages("qual a dificuldade?", {"worker": {}})
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert "AI Operator" in msgs[0]["content"]
        assert msgs[1] == {"role": "user", "content": "qual a dificuldade?"}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Formatters
# ═══════════════════════════════════════════════════════════════════════════


class TestFormatters:
    def test_fmt_hashrate_none(self):
        assert _fmt_hashrate(None) == "—"
        assert _fmt_hashrate(0) == "—"

    def test_fmt_hashrate_units(self):
        assert _fmt_hashrate(1) == "1.00 H/s"
        assert _fmt_hashrate(1500) == "1.50 kH/s"
        assert _fmt_hashrate(15e12) == "15.00 TH/s"
        assert _fmt_hashrate(700e18) == "700.00 EH/s"

    def test_fmt_diff_none_and_zero(self):
        assert _fmt_diff(None) == "—"
        assert _fmt_diff(0) == "—"  # falsy → em-dash (no data)
        assert _fmt_diff("0.0") == "0"  # truthy string that parses to zero

    def test_fmt_diff_units(self):
        assert _fmt_diff(500) == "500.00"
        assert _fmt_diff(2500) == "2.50 K"
        assert _fmt_diff(120e12) == "120.00 T"
        assert _fmt_diff(-2500) == "2.50 K"  # abs() handling

    def test_fmt_diff_suffixed_strings(self):
        # Pool API returns bestDifficulty as a suffixed string — must not crash
        assert _fmt_diff("2.5P") == "2.50 P"
        assert _fmt_diff("123T") == "123.00 T"
        assert _fmt_diff("500G") == "500.00 G"

    def test_fmt_age_none(self):
        assert _fmt_age(None) == "—"

    def test_fmt_age_ranges(self, monkeypatch):
        import time as _t

        monkeypatch.setattr(ai_operator.time, "time", lambda: 1000)
        assert _fmt_age(999) == "1s"
        assert _fmt_age(940) == "1m"
        assert _fmt_age(100) == "15m"
        assert _fmt_age(-100) == "18m"
        assert _fmt_age(-3600) == "1h"
        assert _fmt_age(-100000) == "1d"


# ═══════════════════════════════════════════════════════════════════════════
# 4. stream_response — no key / error paths
# ═══════════════════════════════════════════════════════════════════════════


class TestStreamNoKey:
    def test_no_api_key_yields_error_then_done(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "")
        out = list(stream_response("oi", {}))
        assert json.loads(out[0])["type"] == "error"
        assert json.loads(out[-1])["type"] == "done"


class TestStreamHttpError:
    def test_non_ok_response(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = "boom"
        with patch.object(ai_operator.requests, "post", return_value=mock_resp) as m:
            out = list(stream_response("oi", {}))
        assert json.loads(out[0])["type"] == "error"
        assert "HTTP 500" in json.loads(out[0])["message"]
        assert json.loads(out[-1])["type"] == "done"

    def test_timeout(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        with patch.object(
            ai_operator.requests,
            "post",
            side_effect=ai_operator.requests.exceptions.Timeout(),
        ):
            out = list(stream_response("oi", {}))
        assert "timed out" in json.loads(out[0])["message"]
        assert json.loads(out[-1])["type"] == "done"

    def test_connection_error(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        with patch.object(
            ai_operator.requests,
            "post",
            side_effect=ai_operator.requests.exceptions.ConnectionError(),
        ):
            out = list(stream_response("oi", {}))
        assert "conectar" in json.loads(out[0])["message"].lower()
        assert json.loads(out[-1])["type"] == "done"

    def test_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        with patch.object(
            ai_operator.requests, "post", side_effect=RuntimeError("weird")
        ):
            out = list(stream_response("oi", {}))
        assert "AI error" in json.loads(out[0])["message"]
        assert json.loads(out[-1])["type"] == "done"


# ═══════════════════════════════════════════════════════════════════════════
# 5. stream_response — success streaming (text + tool calls)
# ═══════════════════════════════════════════════════════════════════════════


class _IterLines:
    """Mock response.iter_lines() yielding SSE data lines."""

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        for line in self._lines:
            yield line


def _make_chunk(delta=None, finish_reason=None):
    return {
        "choices": [{"delta": delta or {}, "finish_reason": finish_reason}],
    }


class TestStreamSuccess:
    def test_text_stream(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        lines = [
            b"data: " + json.dumps(_make_chunk({"content": "Olá"})).encode(),
            b"data: " + json.dumps(_make_chunk({"content": " miner!"})).encode(),
            b"data: [DONE]",
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.iter_lines.side_effect = _IterLines(lines).iter_lines
        with patch.object(ai_operator.requests, "post", return_value=mock_resp):
            out = list(stream_response("oi", {}))
        texts = [
            json.loads(o)["content"] for o in out if json.loads(o)["type"] == "text"
        ]
        assert "".join(texts) == "Olá miner!"
        assert json.loads(out[-1])["type"] == "done"

    def test_tool_call_suggest_action(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        args = json.dumps(
            {"device_id": "d1", "action": "restart", "params": {}, "reason": "overheat"}
        )
        # Stream: first the tool-call fragment, then finish_reason=tool_calls
        tool_frag = {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "function": {"name": "suggest_action", "arguments": ""},
                }
            ]
        }
        args_frag = {
            "tool_calls": [
                {"index": 0, "id": "", "function": {"name": "", "arguments": args}}
            ]
        }
        lines = [
            b"data: " + json.dumps(_make_chunk(tool_frag)).encode(),
            b"data: " + json.dumps(_make_chunk(args_frag)).encode(),
            b"data: " + json.dumps(_make_chunk({}, "tool_calls")).encode(),
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.iter_lines.side_effect = _IterLines(lines).iter_lines
        with patch.object(ai_operator.requests, "post", return_value=mock_resp):
            out = list(stream_response("oi", {}))
        actions = [
            json.loads(o)["action"] for o in out if json.loads(o)["type"] == "action"
        ]
        assert len(actions) == 1
        assert actions[0]["device_id"] == "d1"
        assert actions[0]["command"] == "restart"
        assert actions[0]["reason"] == "overheat"
        assert json.loads(out[-1])["type"] == "done"

    def test_bad_tool_args_skipped(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        tool_frag = {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "function": {"name": "suggest_action", "arguments": "not-json"},
                }
            ]
        }
        lines = [
            b"data: " + json.dumps(_make_chunk(tool_frag)).encode(),
            b"data: " + json.dumps(_make_chunk({}, "tool_calls")).encode(),
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.iter_lines.side_effect = _IterLines(lines).iter_lines
        with patch.object(ai_operator.requests, "post", return_value=mock_resp):
            out = list(stream_response("oi", {}))
        # No action emitted, but stream still completes
        types = [json.loads(o)["type"] for o in out]
        assert "action" not in types
        assert json.loads(out[-1])["type"] == "done"

    def test_malformed_sse_lines_skipped(self, monkeypatch):
        monkeypatch.setattr(ai_operator, "AI_API_KEY", "sk-test")
        lines = [
            b"event: ping",  # non-data line → skipped
            b"data: not-json",  # bad JSON → skipped
            b"data: " + json.dumps(_make_chunk({"content": "ok"})).encode(),
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.iter_lines.side_effect = _IterLines(lines).iter_lines
        with patch.object(ai_operator.requests, "post", return_value=mock_resp):
            out = list(stream_response("oi", {}))
        texts = [
            json.loads(o)["content"] for o in out if json.loads(o)["type"] == "text"
        ]
        assert "".join(texts) == "ok"
