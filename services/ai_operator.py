"""
CYPHER65 // AI Operator — LLM-powered mining assistant
=======================================================
Provides a real-time chat endpoint backed by an LLM (DeepSeek by default,
OpenAI-compatible). The AI is grounded in the current snapshot data so it
can answer questions about the user's mining operation.

Environment variables (all optional):
  AI_API_KEY       — API key (default: reads DEEPSEEK_API_KEY, then OPENAI_API_KEY)
  AI_API_BASE_URL  — Base URL for OpenAI-compatible API (default: https://api.deepseek.com/v1)
  AI_MODEL         — Model name (default: deepseek-chat for DeepSeek, gpt-4o-mini for OpenAI)
  AI_PROVIDER      — "deepseek" (default) or "openai"
"""

import os
import json
import time
import logging
import re
from typing import Any, Dict, Generator, List, Optional

import requests

log = logging.getLogger("cypher65.ai")

# ── Configuration from environment ──────────────────────────────────────────
AI_PROVIDER = os.environ.get("AI_PROVIDER", "deepseek").lower()

# Resolve API key: AI_API_KEY > DEEPSEEK_API_KEY > OPENAI_API_KEY
AI_API_KEY = (
    os.environ.get("AI_API_KEY")
    or os.environ.get("DEEPSEEK_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or ""
)

if AI_PROVIDER == "openai":
    AI_API_BASE_URL = os.environ.get(
        "AI_API_BASE_URL", "https://api.openai.com/v1"
    ).rstrip("/")
    AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")
else:
    # Default: DeepSeek
    AI_API_BASE_URL = os.environ.get(
        "AI_API_BASE_URL", "https://api.deepseek.com/v1"
    ).rstrip("/")
    AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")

AI_CHAT_ENDPOINT = f"{AI_API_BASE_URL}/chat/completions"

# Rate limiting
AI_QUERIES_PER_MINUTE = 10

# ── Callable tool definitions (for AI to use) ───────────────────────────────
AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_snapshot_summary",
            "description": "Get a text summary of the current mining snapshot (worker, pool, network, BTC price)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fleet_health",
            "description": "Get a summary of Axe Fleet device health (online/offline, temps, hashrates)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_action",
            "description": "Suggest a device action for the user to confirm (restart, identify, change config). The user must confirm before execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device ID"},
                    "action": {"type": "string", "description": "Command to execute (restart, identify, configure)"},
                    "params": {"type": "object", "description": "Optional parameters for the action"},
                    "reason": {"type": "string", "description": "Why this action is recommended"},
                },
                "required": ["device_id", "action", "reason"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  System prompt builder
# ═══════════════════════════════════════════════════════════════════════════

def build_system_prompt(snapshot: Dict[str, Any]) -> str:
    """Build a context-rich system prompt from the current snapshot."""
    w = snapshot.get("worker") or {}
    pool = snapshot.get("pool") or {}
    net = snapshot.get("network") or {}
    btc = snapshot.get("btc_price") or {}
    prox = snapshot.get("proximity") or {}
    acct = snapshot.get("account") or {}
    axe = snapshot.get("axe_fleet") or []
    alerts = snapshot.get("alerts_recent") or []

    lines = [
        "You are CYPHER65 AI Operator, a specialized assistant for a Bitcoin solo mining operation.",
        "You answer questions concisely and accurately. Use metric units and mining terminology.",
        "You can suggest device actions (restart, identify, configure) but the user must confirm them.",
        "You NEVER execute actions without user confirmation.",
        "",
        "=== CURRENT OPERATION STATUS ===",
    ]

    # Worker
    hr = w.get("hashrate")
    best = w.get("bestDifficulty")
    last_sub = w.get("lastSubmission")
    if hr:
        lines.append(f"- Worker hashrate: {_fmt_hashrate(hr)}")
    if best:
        lines.append(f"- Best difficulty: {_fmt_diff(best)}")
    if last_sub:
        lines.append(f"- Last share: {_fmt_age(last_sub)} ago")
    lines.append(f"- Primary worker: {w.get('name', 'N/A')} ({w.get('id', 'N/A')})")

    # Pool
    lines.append(f"- Pool hashrate: {_fmt_hashrate(pool.get('hashrate'))}")
    lines.append(f"- Pool workers: {pool.get('workers', 'N/A')}")
    lines.append(f"- Pool last block: {pool.get('lastBlock', 'N/A')}")

    # Network
    lines.append(f"- Network difficulty: {_fmt_diff(net.get('difficulty'))}")
    lines.append(f"- Network height: #{net.get('height', 'N/A')}")
    lines.append(f"- BTC price: ${btc.get('usd', 'N/A')}")

    # Proximity / block finding
    pct = prox.get("pct_of_network_cur")
    if pct is not None:
        lines.append(f"- Share of network: {pct:.6f}%")
    exp_time = prox.get("expected_time_human")
    if exp_time:
        lines.append(f"- Expected block time: {exp_time}")
    chance = prox.get("chance_per_share_label")
    if chance:
        lines.append(f"- Per-share chance: {chance}")

    # Account
    total_diff = acct.get("total_diff")
    if total_diff:
        lines.append(f"- Account total difficulty: {_fmt_diff(total_diff)}")

    # Axe Fleet
    online = sum(1 for d in axe if d.get("status") == "ONLINE")
    total = len(axe)
    if total > 0:
        lines.append(f"- Fleet: {online}/{total} devices online")
        for d in axe:
            name = d.get("name", d.get("id", "?"))
            status = d.get("status", "UNKNOWN")
            temp = d.get("temperature")
            d_hr = d.get("hashrate")
            parts = [f"  - {name}: {status}"]
            if temp:
                parts.append(f"{temp}°C")
            if d_hr:
                parts.append(f"HR {_fmt_hashrate(d_hr)}")
            lines.append(" ".join(parts))

    # Alerts
    if alerts:
        lines.append(f"- Active alerts: {len(alerts)}")
        for a in alerts[:5]:
            lines.append(f"  - [{a.get('severity', 'INFO')}] {a.get('message', '')}")

    lines.extend([
        "",
        "=== CAPABILITIES ===",
        "- Answer questions about current mining data",
        "- Explain mining concepts (difficulty, hashrate, probability, pool luck)",
        "- Suggest device actions (restart, identify, configure) — user must confirm",
        "- Compare rental market prices (Braiins, NiceHash, MRR)",
        "",
        "=== CONSTRAINTS ===",
        "- NEVER execute device actions without explicit user confirmation",
        "- Always respond in the same language as the user's question",
        "- Be concise — keep responses under 200 words unless asked for detail",
        "- Use metric: TH/s for hashrate, BTC for prices, sat/vB for fees",
        "- Mark estimated/probabilistic values clearly",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  LLM streaming
# ═══════════════════════════════════════════════════════════════════════════

def _build_messages(query: str, snapshot: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build the messages array for the LLM chat completion request."""
    system_prompt = build_system_prompt(snapshot)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]


def stream_response(
    query: str,
    snapshot: Dict[str, Any],
) -> Generator[str, None, None]:
    """Stream an AI response as SSE text chunks. Yields JSONL strings.

    Each yield is a JSON object with one of these shapes:
      {"type": "text", "content": "..."}    — normal text chunk
      {"type": "action", "action": {...}}   — suggested device action
      {"type": "error", "message": "..."}   — error message
      {"type": "done"}                      — stream complete

    The caller flushes each yield to the HTTP response as a Server-Sent Event.
    """
    if not AI_API_KEY:
        yield json.dumps({"type": "error", "message": (
            "AI Operator não configurado. Configure a variável de ambiente "
            "AI_API_KEY (ou DEEPSEEK_API_KEY / OPENAI_API_KEY) e reinicie o servidor."
        )})
        yield json.dumps({"type": "done"})
        return

    messages = _build_messages(query, snapshot)

    try:
        response = requests.post(
            AI_CHAT_ENDPOINT,
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json={
                "model": AI_MODEL,
                "messages": messages,
                "stream": True,
                "tools": AI_TOOLS,
                "tool_choice": "auto",
                "temperature": 0.3,
                "max_tokens": 1024,
            },
            stream=True,
            timeout=30,
        )

        if not response.ok:
            error_body = ""
            try:
                error_body = response.text[:500]
            except Exception:
                pass
            yield json.dumps({
                "type": "error",
                "message": f"LLM API error: HTTP {response.status_code} — {error_body}",
            })
            yield json.dumps({"type": "done"})
            return

        # Stream the response
        tool_calls_buffer = {}
        current_tool_call_id = None

        for line in response.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8", errors="replace")

            if decoded.startswith("data: "):
                data_str = decoded[6:].strip()
            elif decoded.startswith("data:"):
                data_str = decoded[5:].strip()
            else:
                continue

            if data_str == "[DONE]":
                break

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})

            # Text content
            content = delta.get("content", "")
            if content:
                yield json.dumps({"type": "text", "content": content})

            # Tool calls
            tc_list = delta.get("tool_calls", [])
            for tc in tc_list:
                idx = tc.get("index", 0)
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": tc.get("id", ""),
                        "function": {"name": "", "arguments": ""},
                    }
                buf = tool_calls_buffer[idx]
                if tc.get("id"):
                    buf["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    buf["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    buf["function"]["arguments"] += fn["arguments"]

            # On finish reason, process tool calls
            finish = choices[0].get("finish_reason")
            if finish in ("tool_calls", "stop", "length"):
                # Process completed tool calls
                for idx, tc in sorted(tool_calls_buffer.items()):
                    if tc["function"]["name"] == "suggest_action":
                        try:
                            args = json.loads(tc["function"]["arguments"])
                            yield json.dumps({
                                "type": "action",
                                "action": {
                                    "device_id": args.get("device_id", ""),
                                    "command": args.get("action", ""),
                                    "params": args.get("params", {}),
                                    "reason": args.get("reason", ""),
                                },
                            })
                        except (json.JSONDecodeError, KeyError) as e:
                            log.warning("[ai] failed to parse suggest_action args: %s", e)

                tool_calls_buffer = {}

    except requests.exceptions.Timeout:
        yield json.dumps({"type": "error", "message": "LLM request timed out after 30s"})
    except requests.exceptions.ConnectionError:
        yield json.dumps({
            "type": "error",
            "message": f"Não foi possível conectar ao provedor LLM em {AI_API_BASE_URL}. "
                       f"Verifique a URL e a conectividade de rede.",
        })
    except Exception as e:
        log.exception("[ai] stream error")
        yield json.dumps({"type": "error", "message": f"AI error: {str(e)[:200]}"})

    yield json.dumps({"type": "done"})


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers (mirror frontend formatters for system prompt readability)
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_hashrate(h) -> str:
    if not h:
        return "—"
    v = float(h)
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"]
    i = 0
    x = v
    while x >= 1000 and i < len(units) - 1:
        x /= 1000
        i += 1
    return f"{x:.2f} {units[i]}"


def _fmt_diff(d) -> str:
    if not d:
        return "—"
    v = float(d)
    if v == 0:
        return "0"
    units = ["", "K", "M", "G", "T", "P", "E"]
    i = 0
    x = abs(v)
    while x >= 1000 and i < len(units) - 1:
        x /= 1000
        i += 1
    return f"{x:.2f} {units[i]}".strip()


def _fmt_age(ts) -> str:
    if not ts:
        return "—"
    d = max(0, int(time.time()) - int(ts))
    if d < 60:
        return f"{d}s"
    if d < 3600:
        return f"{d // 60}m"
    if d < 86400:
        return f"{d // 3600}h"
    return f"{d // 86400}d"
