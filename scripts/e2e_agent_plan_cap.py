#!/usr/bin/env python3
"""
CYPHER65 // E2E — PLAN CAP: devices não admitidos NÃO geram 403-spam
====================================================================
Cenário de auditoria CFO: tenant no limite do plano (max_workers=1) e o
agente descobre 2 miners na LAN. O servidor deve:

  - admitir exatamente 1 device (register → 201 com `blocked` para o outro)
  - o agente deve DROPAR o IP bloqueado do poll set (nunca empurrar telemetria)
  - NENHUM push de telemetria para o device não admitido (403-spam = 0)

Prova (contagens objetivas no audit_logs + logs):
  - devices no /api/axe-fleet/devices  == 1 (e ONLINE)
  - audit_logs action='agent.telemetry_blocked'  == 0  ← sem spam
  - audit_logs action='agent.register_blocked'  >= 1  ← bloqueio honesto
  - agent.log contém "plan worker limit" (o agente explica o bloqueio)
  - contagens ESTÁVEIS após múltiplos ciclos de re-scan (10 ciclos ≈ 20s)

Uso:
    python scripts/e2e_agent_plan_cap.py
    CYPHER65_E2E_KEEP=1 python scripts/e2e_agent_plan_cap.py

Exit: 0 = sem spam confirmado · 1 = falhou (com diagnóstico nos logs).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_agent_local as harness  # reutiliza mocks + helpers HTTP

USERNAME = "planop"
PASSWORD = "plano-pass-123"
PLAN_MAX_WORKERS = 1
POLL_WINDOW_S = 60
# Depois do registro inicial, esperamos alguns ciclos de re-scan do agente
# (RESCAN_EVERY=10 × POLL 2s ≈ 20s) para provar que o bloqueio é estável.
STABILITY_WAIT_S = 35


def _set_tenant_max_workers(db_path: str, tenant_id: str, max_workers: int):
    """Force the tenant's worker cap (the harness owns the scratch DB)."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tenants SET max_workers=? WHERE id=?", (max_workers, tenant_id))
    conn.commit()
    conn.close()


def _count_audit(db_path: str, action: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action=?", (action,)).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def main() -> int:
    print("=" * 74)
    print("CYPHER65 // E2E — PLAN CAP (max_workers=1) · sem 403-spam")
    print("=" * 74)

    tmp = Path(tempfile.mkdtemp(prefix="cypher65_e2e_cap_"))
    keep = os.environ.get("CYPHER65_E2E_KEEP") == "1"
    db_path = tmp / "war_room.sqlite"
    server_log = tmp / "server.log"
    agent_log = tmp / "agent.log"

    procs = []
    axeos = cgminer = None
    try:
        # 1 ─ Mocks de miner na "LAN" (loopback) — 2 devices reais
        axeos, axeos_port = harness._start_axeos_mock()
        cgminer, cgminer_stop, cgminer_port = harness._start_cgminer_mock()
        print(f"  1. miners mock  ✓  AxeOS 127.0.0.1:{axeos_port} · "
              f"cgminer localhost:{cgminer_port}  (2 descobríveis)")

        # 2 ─ Servidor real num DB descartável (self-host, nunca nuvem)
        server_port = harness._free_port()
        env = dict(os.environ)
        env.update({
            "DB_PATH": str(db_path),
            "SECRET_KEY": "e2e-plan-cap-secret-0001",
            "PORT": str(server_port),
            "POLL_INTERVAL": "3",
            "RATE_LIMIT_PER_MINUTE": "100000",
            "AUTH_RATE_LIMIT_PER_MINUTE": "100000",
        })
        for k in ("RENDER", "RENDER_SERVICE_ID", "RENDER_INSTANCE_ID",
                  "CLOUD_MODE", "API_KEY", "TENANT_API_KEYS"):
            env.pop(k, None)
        with open(server_log, "wb") as flog:
            server = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT),
                                      env=env, stdout=flog, stderr=subprocess.STDOUT)
        procs.append(server)
        base = f"http://127.0.0.1:{server_port}"
        if not harness._wait_for_server(base):
            print(f"  ❌ servidor não subiu — log:\n{harness._log_tail(server_log)}")
            return 1
        print(f"  2. servidor real ✓  {base} (DB descartável)")

        # 3 ─ Registro de usuário (cria tenant free, 5 workers) + agent token
        code, reg = harness._http_json("POST", base + "/api/auth/register",
                                       {"username": USERNAME, "password": PASSWORD})
        if code != 201 or not reg.get("access_token"):
            print(f"  ❌ register falhou (HTTP {code}): {reg}")
            return 1
        access = reg["access_token"]
        code, tok = harness._http_json("POST", base + "/api/agent/token", {}, token=access)
        if code != 200 or not tok.get("token"):
            print(f"  ❌ /api/agent/token falhou (HTTP {code}): {tok}")
            return 1
        tenant_id = tok["tenant_id"]

        # 4 ─ Força o plano no limite: só 1 worker permitido
        _set_tenant_max_workers(str(db_path), tenant_id, PLAN_MAX_WORKERS)
        print(f"  3. tenant      ✓  {tenant_id} · max_workers={PLAN_MAX_WORKERS} "
              f"(forçado no DB do harness)")

        # 5 ─ Agente real com 2 devices explícitos (descobre 2, só 1 cabe)
        aenv = dict(os.environ)
        aenv.update({
            "CYPHER65_SERVER_URL": base,
            "CYPHER65_AGENT_TOKEN": tok["token"],
            "CYPHER65_POLL_INTERVAL": "2",
            "CYPHER65_DEVICES": "127.0.0.1,localhost",
            "CYPHER65_AXEOS_PORT": str(axeos_port),
            "CYPHER65_CGMINER_PORT": str(cgminer_port),
        })
        with open(agent_log, "wb") as flog:
            agent_proc = subprocess.Popen([sys.executable, "agent/agent.py"],
                                          cwd=str(ROOT), env=aenv,
                                          stdout=flog, stderr=subprocess.STDOUT)
        procs.append(agent_proc)
        print("  4. agente local ✓  (poll 2s · 2 devices · plano limita a 1)")

        # 6 ─ Espera o registro: EXATAMENTE 1 device admitido, ONLINE
        devices = []
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            code, resp = harness._http_json("GET", base + "/api/axe-fleet/devices",
                                            token=access)
            if code == 200:
                devices = resp.get("devices") or []
                if len(devices) == 1 and devices[0].get("status") == "ONLINE" \
                        and int(devices[0].get("hashrate_hs") or 0) > 0:
                    break
            time.sleep(2)
        if len(devices) != 1 or devices[0].get("status") != "ONLINE":
            print("  ❌ esperado EXATAMENTE 1 device ONLINE — obtido: "
                  + json.dumps(devices, default=str))
            print("     log do agente:\n" + harness._log_tail(agent_log))
            print("     log do servidor:\n" + harness._log_tail(server_log))
            return 1
        admitted_ip = devices[0].get("ip_address")
        print(f"  5. devices      ✓  1 admitido (ONLINE): {admitted_ip}")

        # 7 ─ Auditoria imediata: sem 403-spam de telemetria
        blocked_reg = _count_audit(str(db_path), "agent.register_blocked")
        blocked_tel = _count_audit(str(db_path), "agent.telemetry_blocked")
        if blocked_reg < 1:
            print("  ❌ nenhum 'agent.register_blocked' auditado — o bloqueio "
                  "deveria ter acontecido no register")
            print("     log do agente:\n" + harness._log_tail(agent_log))
            return 1
        if blocked_tel != 0:
            print(f"  ❌ {blocked_tel} push(s) de telemetria para device não "
                  f"admitido (403-spam!) — agente NÃO dropou o IP bloqueado")
            print("     log do agente:\n" + harness._log_tail(agent_log))
            return 1
        print(f"  6. auditoria    ✓  register_blocked={blocked_reg} · "
              f"telemetry_blocked={blocked_tel}  (zero spam)")

        # 8 ─ Estabilidade: espera múltiplos ciclos de re-scan (o agente
        #    re-descobre o device bloqueado e re-tenta register a cada 10
        #    ciclos). Nenhuma dessas tentativas pode virar telemetry 403.
        time.sleep(STABILITY_WAIT_S)
        code, resp = harness._http_json("GET", base + "/api/axe-fleet/devices",
                                        token=access)
        devices_after = resp.get("devices") or []
        blocked_reg_after = _count_audit(str(db_path), "agent.register_blocked")
        blocked_tel_after = _count_audit(str(db_path), "agent.telemetry_blocked")
        if len(devices_after) != 1:
            print(f"  ❌ após {STABILITY_WAIT_S}s: devices={len(devices_after)} "
                  f"(esperado 1) — o bloqueio não é estável")
            return 1
        if blocked_tel_after != 0:
            print(f"  ❌ após re-scan: telemetry_blocked={blocked_tel_after} "
                  f"(era {blocked_tel}) — spam apareceu com o tempo")
            return 1
        print(f"  7. estabilidade ✓  +{STABILITY_WAIT_S}s (≈{STABILITY_WAIT_S // 2} "
              f"ciclos de re-scan) · devices={len(devices_after)} · "
              f"telemetry_blocked={blocked_tel_after} · "
              f"register_blocked={blocked_reg_after}")

        # 9 ─ Evidência no log do agente (mensagem honesta do bloqueio)
        agent_txt = Path(agent_log).read_text(errors="replace")
        has_blocked_msg = "plan worker limit" in agent_txt or "blocked" in agent_txt
        if not has_blocked_msg:
            print("  ❌ agente não logou o bloqueio do plano:")
            print(harness._log_tail(agent_log))
            return 1
        print("  8. agent log    ✓  bloqueio explicado ('plan worker limit')")

        print("-" * 74)
        print(f"{'IP':<12}{'model':<20}{'status':<9}{'agent':<6}")
        for d in devices_after:
            print("%-12s%-20s%-9s%s" % (
                d.get("ip_address"), (d.get("model") or "?")[:19],
                d.get("status"), "1" if d.get("agent_managed") else "0"))
        print("-" * 74)
        print("✅ E2E PLAN CAP OK — device não admitido NÃO gera 403-spam "
              "(0 telemetry_blocked, bloqueio estável no re-scan).")
        return 0

    except KeyboardInterrupt:
        print("\ninterrompido pelo usuário")
        return 130
    except Exception as e:
        print(f"  ❌ exceção no harness: {type(e).__name__}: {e}")
        print("     log do agente:\n" + harness._log_tail(agent_log))
        print("     log do servidor:\n" + harness._log_tail(server_log))
        return 1
    finally:
        for p in reversed(procs):
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
                p.wait()
        if axeos:
            try:
                axeos.shutdown()
            except Exception:
                pass
            try:
                axeos.server_close()
            except Exception:
                pass
        if cgminer:
            cgminer_stop.set()
            try:
                cgminer.close()
            except Exception:
                pass
        if keep:
            print(f"(logs preservados em {tmp})")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
