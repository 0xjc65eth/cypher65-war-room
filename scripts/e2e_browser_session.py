#!/usr/bin/env python3
"""
CYPHER65 // E2E — BROWSER SESSION (servidor + mocks + agente vivos p/ UI)
=======================================================================
Sobe o mesmo cenário do e2e_agent_local.py (servidor REAL num DB
descartável + 2 miners mock + agente REAL) mas NÃO derruba nada ao
terminar: escreve um state file com a URL/credenciais e fica rodando
até o browser terminar a verificação.

  State file:  /tmp/cypher65_browser_session.json
  Parar:       touch /tmp/cypher65_browser_session.stop   (ou timeout)

Uso:
    python scripts/e2e_browser_session.py          # roda até stop file / 15min
    CYPHER65_BROWSER_SESSION_MAX_S=900 python ...   # timeout customizado
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Importa o MÓDULO (não `from ... import` dos contadores): se um dia este
# harness precisar provar execução de comandos, leia `e2e._AXEOS_RESTARTS`
# como referência viva — `from ... import` traria uma cópia congelada (0).
import scripts.e2e_agent_local as e2e  # noqa: E402 — reutiliza mocks + helpers

USERNAME = e2e.USERNAME
PASSWORD = e2e.PASSWORD
POLL_WINDOW_S = e2e.POLL_WINDOW_S
_start_axeos_mock = e2e._start_axeos_mock
_start_cgminer_mock = e2e._start_cgminer_mock
_http_json = e2e._http_json
_wait_for_server = e2e._wait_for_server
_free_port = e2e._free_port
_log_tail = e2e._log_tail

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = Path("/tmp/cypher65_browser_session.json")
STOP_FILE = Path("/tmp/cypher65_browser_session.stop")
MAX_S = int(os.environ.get("CYPHER65_BROWSER_SESSION_MAX_S", "900"))


def _write_state(base, tmp, axeos_port, cgminer_port, server_log, agent_log,
                 session=None):
    STATE_FILE.write_text(json.dumps({
        "base_url": base, "username": USERNAME, "password": PASSWORD,
        "tmp_dir": str(tmp), "axeos_port": axeos_port,
        "cgminer_port": cgminer_port,
        "server_log": str(server_log), "agent_log": str(agent_log),
        # The dashboard persists the tenant session in localStorage under
        # _cypher65_auth_session — the browser agent injects these exactly.
        "session": session or {},
    }))


def main() -> int:
    print("=" * 74)
    print("CYPHER65 // BROWSER SESSION — servidor + mocks + agente vivos")
    print("=" * 74)

    tmp = Path(tempfile.mkdtemp(prefix="cypher65_browser_"))
    keep = os.environ.get("CYPHER65_E2E_KEEP") == "1"
    db_path = tmp / "war_room.sqlite"
    server_log = tmp / "server.log"
    agent_log = tmp / "agent.log"
    STOP_FILE.unlink(missing_ok=True)

    procs = []
    axeos = cgminer = cgminer_stop = None
    try:
        # 1 ─ Mocks de miner na "LAN" (loopback)
        axeos, axeos_port = _start_axeos_mock()
        cgminer, cgminer_stop, cgminer_port = _start_cgminer_mock()
        print(f"  1. miners mock  ✓  AxeOS 127.0.0.1:{axeos_port} · "
              f"cgminer localhost:{cgminer_port}")

        # 2 ─ Servidor real num DB descartável (modo self-host, nunca nuvem)
        server_port = _free_port()
        env = dict(os.environ)
        env.update({
            "DB_PATH": str(db_path),
            "SECRET_KEY": "e2e-secret-key-0001",
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
        if not _wait_for_server(base):
            print(f"  ❌ servidor não subiu — log:\n{_log_tail(server_log)}")
            return 1
        print(f"  2. servidor real ✓  {base} (DB descartável)")

        # 3 ─ Registro de usuário + AGENT TOKEN
        code, reg = _http_json("POST", base + "/api/auth/register",
                               {"username": USERNAME, "password": PASSWORD})
        if code != 201 or not reg.get("access_token"):
            print(f"  ❌ register falhou (HTTP {code}): {reg}")
            return 1
        access = reg["access_token"]
        code, tok = _http_json("POST", base + "/api/agent/token", {}, token=access)
        if code != 200 or not tok.get("token"):
            print(f"  ❌ /api/agent/token falhou (HTTP {code}): {tok}")
            return 1
        agent_token = tok["token"]
        print("  3. agente token  ✓  tenant=%s" % tok.get("tenant_id"))

        # 4 ─ Agente real
        aenv = dict(os.environ)
        aenv.update({
            "CYPHER65_SERVER_URL": base,
            "CYPHER65_AGENT_TOKEN": agent_token,
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
        print("  4. agente local ✓  (poll 2s → registra → empurra telemetria)")

        # 5 ─ Espera os 2 devices ONLINE (senão o browser não teria o que ver)
        devices = []
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            code, resp = _http_json("GET", base + "/api/axe-fleet/devices",
                                    token=access)
            if code == 200:
                devices = resp.get("devices") or []
                if (len(devices) >= 2 and all(
                        d.get("status") == "ONLINE"
                        and int(d.get("hashrate_hs") or 0) > 0
                        and d.get("agent_managed")
                        for d in devices)):
                    break
            time.sleep(2)
        if len(devices) < 2:
            print("  ❌ devices não registraram — log do agente:\n"
                  + _log_tail(agent_log))
            return 1
        print("  5. devices ✓  %d ONLINE (agent_managed)" % len(devices))

        _write_state(base, tmp, axeos_port, cgminer_port, server_log, agent_log,
                     session={
                         "access_token": access,
                         "refresh_token": reg.get("refresh_token", ""),
                         "expires_at": reg.get("expires_at"),
                         "tenant_id": reg.get("tenant_id", "default"),
                     })
        print("-" * 74)
        print(f"  ✅ PRONTO PARA O BROWSER")
        print(f"     URL:        {base}")
        print(f"     login:      {USERNAME} / {PASSWORD}")
        print(f"     state file: {STATE_FILE}")
        print(f"     logs:       {tmp}")
        print(f"  Rodando até stop file ou {MAX_S}s — ")
        print(f"  touch {STOP_FILE} para encerrar.")
        print("-" * 74)
        sys.stdout.flush()

        # Mantém tudo vivo; encerra no stop file / timeout / Ctrl-C.
        started = time.time()
        while time.time() - started < MAX_S:
            if STOP_FILE.exists():
                print("  stop file detectado — encerrando sessão")
                break
            time.sleep(2)
        return 0

    except KeyboardInterrupt:
        print("\nsessão interrompida pelo usuário")
        return 130
    except Exception as e:
        print(f"  ❌ exceção no harness: {type(e).__name__}: {e}")
        print("     log do agente (últimas linhas):\n" + _log_tail(agent_log))
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
        try:
            STATE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        if keep:
            print(f"(logs preservados em {tmp})")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
