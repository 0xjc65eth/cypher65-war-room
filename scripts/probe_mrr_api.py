#!/usr/bin/env python3
"""Probe MRR API v2 — cada usuário valida a PRÓPRIA chave (Issue #152).

Usage:
  python scripts/probe_mrr_api.py                          # .env (operador self-host)
  python scripts/probe_mrr_api.py --key K --secret S       # qualquer usuário, sem tocar .env
  python scripts/probe_mrr_api.py --check --key K --secret S  # validação rápida /whoami

Precedência de credenciais (por campo): CLI > env var > .env.
Saída de --check: veredito VALID/INVALID + exit code (0/1) — pronto para
scripting. O erro "Invalid Key - Bad Nonce." indica credencial
inválida/desatualizada ou tracker de nonce da chave preso (regenerar a
key/secret na conta MRR) — NÃO é bug de concorrência (fix #150 garante
nonces monotônicos).
"""
import argparse
import hashlib
import hmac
import json
import os
import sys

BASE = "https://www.miningrigrentals.com/api/v2"


def load_env(path):
    env = {}
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = load_env(os.path.join(_root, ".env"))
KEY = env.get("MRR_API_KEY", "")
SEC = env.get("MRR_API_SECRET", "")

import requests  # noqa: E402 — requests só é exigido em runtime

sys.path.insert(0, _root)
from helpers import next_monotonic_nonce_ms  # noqa: E402 — precisa do _root


def resolve_credentials(cli_key="", cli_secret=""):
    """CLI > env var > .env, por campo. Sempre strip (valor com \n/ espaço
    corrompe a assinatura HMAC e vira um falso 401)."""
    key = (cli_key or "").strip() or (os.environ.get("MRR_API_KEY") or "").strip()
    sec = (cli_secret or "").strip() or (os.environ.get("MRR_API_SECRET") or "").strip()
    if not key:
        key = (env.get("MRR_API_KEY") or "").strip()
    if not sec:
        sec = (env.get("MRR_API_SECRET") or "").strip()
    return key, sec


def creds_source(cli_key="", cli_secret=""):
    """Descreve a origem de cada campo (sem expor valores)."""

    def _src(cli_val, env_var, env_key):
        if (cli_val or "").strip():
            return "cli"
        if (os.environ.get(env_var) or "").strip():
            return "env"
        if (env.get(env_key) or "").strip():
            return ".env"
        return "none"

    return (
        f"key={_src(cli_key, 'MRR_API_KEY', 'MRR_API_KEY')} · "
        f"sec={_src(cli_secret, 'MRR_API_SECRET', 'MRR_API_SECRET')}"
    )


def call(ep, method="GET", params=None, body=None):
    # Issue #150 — nonce monotônico compartilhado (nunca time.time()*1000 cru).
    nonce = next_monotonic_nonce_ms()
    sign = hmac.new(SEC.encode(), (KEY + nonce + ep).encode(), hashlib.sha1).hexdigest()
    headers = {
        "x-api-key": KEY,
        "x-api-nonce": nonce,
        "x-api-sign": sign,
        "Content-Type": "application/json",
    }
    try:
        if method == "GET":
            r = requests.get(BASE + ep, headers=headers, params=params, timeout=15)
        else:
            r = requests.post(BASE + ep, headers=headers, json=body or {}, timeout=15)
        if r.status_code != 200:
            return {"HTTP": r.status_code, "body": r.text[:200]}
        return r.json()
    except Exception as e:
        return {"error": str(e)[:150]}


def validate_credentials():
    """Validação rápida: /whoami com as credenciais resolvidas (globais).

    Returns {"authed": bool, "msg": str}. ``msg`` carrega a mensagem de auth
    do MRR (ex.: 'Invalid Key - Bad Nonce.') ou erro de transporte.
    """
    res = call("/whoami")
    if isinstance(res, dict) and res.get("error"):
        return {"authed": False, "msg": res["error"]}
    if isinstance(res, dict) and "HTTP" in res:
        return {
            "authed": False,
            "msg": f"HTTP {res['HTTP']}: {str(res.get('body'))[:100]}",
        }
    data = res.get("data", {}) if isinstance(res, dict) else {}
    authed = data.get("authed") is True
    msg = data.get("auth_mesage") or f"success (authed={data.get('authed')})"
    return {"authed": authed, "msg": str(msg)}


def summarize(data):
    """Compact JSON summary (keys + types, first values)."""
    if isinstance(data, dict):
        out = {}
        for k, v in list(data.items())[:12]:
            if isinstance(v, (dict, list)):
                out[k] = (
                    f"{type(v).__name__}[{len(v)}]"
                    if not isinstance(v, list)
                    else f"list[{len(v)}]"
                )
            else:
                out[k] = str(v)[:60]
        return out
    if isinstance(data, list):
        return f"list[{len(data)}] first={summarize(data[0]) if data else None}"
    return str(data)[:80]


def _build_parser():
    p = argparse.ArgumentParser(
        prog="probe_mrr_api.py",
        description="Probe MRR API v2 com credenciais próprias (CLI > env > .env).",
    )
    p.add_argument("--key", help="MRR API key (override env/.env)")
    p.add_argument("--secret", help="MRR API secret (override env/.env)")
    p.add_argument(
        "--check",
        action="store_true",
        help="Validação rápida: só /whoami, veredito VALID/INVALID + exit code (0/1)",
    )
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()

    # Escopo de módulo: rebind direto já atualiza KEY/SEC usados por call().
    KEY, SEC = resolve_credentials(args.key, args.secret)
    print(
        f"creds: {creds_source(args.key, args.secret)} "
        f"| key ok={bool(KEY)} sec ok={bool(SEC)}"
    )

    if not (KEY and SEC):
        print(
            "Sem credenciais. Forneça --key/--secret, defina MRR_API_KEY/"
            "MRR_API_SECRET no ambiente, ou preencha .env (self-host)."
        )
        sys.exit(2)

    if args.check:
        v = validate_credentials()
        if v["authed"]:
            print(f"✅ VALID — credenciais autenticam no MRR ({v['msg']})")
            sys.exit(0)
        print(f"❌ INVALID — {v['msg']}")
        print(
            "   'Invalid Key - Bad Nonce.' = credencial inválida/desatualizada ou "
            "tracker de nonce da chave preso."
        )
        print(
            "   Regenerar key/secret na conta MRR (miningrigrentals.com → Account "
            "→ API) e atualizar em Settings → MRR."
        )
        sys.exit(1)

    for ep, method, params in [
        ("/whoami", "GET", None),
        ("/account", "GET", None),
        ("/account/balance", "GET", None),
        ("/rig", "GET", {"type": "sha256", "order": "price"}),
        ("/rig/my", "GET", None),
        ("/rental", "GET", None),
        ("/rental", "GET", {"type": "renter"}),
        ("/rental", "GET", {"type": "owner"}),
        ("/rental", "GET", {"type": "renter", "history": "true"}),
        ("/info/algos", "GET", None),
        ("/account/transactions", "GET", {"limit": 3}),
    ]:
        res = call(ep, method, params)
        print(f"\n=== {method} {ep} {params or ''} ===")
        print(json.dumps(summarize(res), ensure_ascii=False, indent=1)[:1200])
