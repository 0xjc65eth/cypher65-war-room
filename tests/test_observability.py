"""Hermetic tests for services/observability.py (Issue #30 · cost-$0).

Covers:
  1. JsonFormatter emits one parseable JSON line with structured fields.
  2. exc_info is serialized (never crashes the formatter).
  3. JSON mode is only active when LOG_JSON=1 (default stays text).
  4. build_logger returns a named logger; boot_health logs without crashing.

Hermetic rule: no test touches data/war_room.sqlite.
"""
import json
import logging
import os
import sys

import pytest

from services import observability


def _mkrecord(msg="hello world", level=logging.INFO, name="cypher65.test",
              exc_info=None, ctx=None, lineno=42, func="test_func"):
    r = logging.LogRecord(name, level, __file__, lineno, msg, (), exc_info)
    r.funcName = func
    if ctx is not None:
        r.ctx = ctx
    return r


def test_json_formatter_emits_parseable_line():
    fmt = observability.JsonFormatter()
    out = fmt.format(_mkrecord("miner online", ctx={"device": "bitaxe1"}))
    data = json.loads(out)
    assert data["message"] == "miner online"
    assert data["level"] == "INFO"
    assert data["module"] == "cypher65.test"
    assert data["func"] == "test_func"
    assert data["ctx"] == {"device": "bitaxe1"}
    assert data["service"] == "cypher65-war-room"


def test_json_formatter_handles_exception_info():
    fmt = observability.JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        r = _mkrecord("failed", level=logging.ERROR)
        r.exc_info = sys.exc_info()  # real (type, value, tb) tuple like logger.exception
        out = fmt.format(r)
    data = json.loads(out)
    assert "boom" in data["exc"]


def test_json_formatter_survives_bare_true_exc_info():
    """LogRecords built with exc_info=True (not a tuple) must not crash."""
    fmt = observability.JsonFormatter()
    out = fmt.format(_mkrecord("edge", level=logging.ERROR, exc_info=True))
    data = json.loads(out)  # exc simply omitted
    assert data["message"] == "edge"


def test_json_formatter_never_crashes_on_unserializable_ctx():
    fmt = observability.JsonFormatter()
    r = _mkrecord("weird", ctx={"obj": object()})  # object() is not JSON-safe
    out = fmt.format(r)  # must not raise
    assert isinstance(out, str)


def test_setup_logging_default_is_text(monkeypatch):
    monkeypatch.delenv("LOG_JSON", raising=False)
    active = observability.setup_logging()
    assert active is False
    root = logging.getLogger()
    handler = root.handlers[0]
    assert not isinstance(handler.formatter, observability.JsonFormatter)


def test_setup_logging_json_mode(monkeypatch):
    monkeypatch.setenv("LOG_JSON", "1")
    active = observability.setup_logging()
    assert active is True
    root = logging.getLogger()
    handler = root.handlers[0]
    assert isinstance(handler.formatter, observability.JsonFormatter)


def test_build_logger_and_boot_health_noop_safe():
    logger = observability.build_logger("cypher65.test")
    assert logger.name == "cypher65.test"
    # boot_health must never raise, whatever the ctx shape.
    observability.boot_health({"port": 8765})
    observability.boot_health()
