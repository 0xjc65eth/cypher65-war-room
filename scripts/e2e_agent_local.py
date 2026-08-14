#!/usr/bin/env python3
"""
CYPHER65 // E2E — LOCAL AGENT FULL LOOP (real processes, mock miners)
====================================================================
Prova ponta-a-ponta do caminho de telemetria do SaaS (o fluxo que os
usuários do Render usam para conectar os miners da LAN):

  1. Sobe o SERVIDOR REAL (app.py) num DB descartável + porta aleatória
  2. Registra um usuário → pega access_token → emite AGENT TOKEN
     (POST /api/agent/token — o mesmo clique de "CONNECT AGENT")
  3. Sobe miners MOCK no loopback (AxeOS HTTP :port + cgminer TCP :port)
  4. Roda o AGENTE REAL (agent/agent.py) apontado para o servidor local
     (mesmas env vars do docker one-liner da UI)
  5. Asserta que os devices aparecem ONLINE com telemetria viva em:
       GET /api/axe-fleet/devices   (com telemetria)
       GET /api/snapshot            (bloco axe_fleet)
  6. Command round-trip REAL: enqueue restart (AxeOS + cgminer) e
     pause/resume (AxeOS) via /api/axe-fleet/devices/<id>/... → o agente
     local puxa e EXECUTA no miner mock (contadores do mock provam) →
     telemetria seguinte confirma PAUSED/ONLINE no servidor

Uso:
    python scripts/e2e_agent_local.py
    CYPHER65_E2E_KEEP=1 python scripts/e2e_agent_local.py   # não apaga logs

Exit: 0 = fluxo completo OK · 1 = falhou (com diagnóstico no log).
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

ROOT = Path(__file__).resolve().parents[1]

USERNAME = "e2eoperator"
PASSWORD = "e2e-pass-123"
POLL_WINDOW_S = 60  # janela máxima para o agente registrar + empurrar telemetria


# ── Mock miners (payloads realistas — mesmos shapes do test_agent_protocol) ─

_AXEOS_INFO = {
    "board": "GAMMA",
    "model": "Gamma 900",
    "firmware": "AxeOS 2.13.0",
    "version": "2.13.0",
    "hostname": "bitaxe-gamma-01",
    "mac": "5C:86:4A:11:22:33",
    "hashrate": 912345678901,
    "temp": 53.2,
    "fanRPM": 4600,
    "fanSpeed": 92,
    "power": 15.6,
    "coreVoltage": 1201,
    "frequency": 550,
    "bestDiff": "8.2T",
    "sharesAccepted": 1450,
    "sharesRejected": 7,
    "uptime": 86500,
    "stratumURL": "public-pool.io",
    "stratumPort": 21496,
    "stratumUser": "bc1qtest.gamma01",
    "wifiRSSI": -52,
}


def _cgminer_reply(cmd):
    if cmd == "version":
        return {
            "STATUS": [
                {
                    "STATUS": "S",
                    "Code": 22,
                    "Msg": "CGMiner versions",
                    "Description": "cgminer 4.11.1",
                }
            ],
            "VERSION": [
                {
                    "CGMiner": "4.11.1",
                    "API": "3.1",
                    "Miner": "X19",
                    "Type": "Antminer S19j Pro",
                }
            ],
        }
    if cmd == "summary":
        return {
            "STATUS": [{"STATUS": "S", "Code": 11, "Msg": "Summary"}],
            "SUMMARY": [
                {
                    "GHS 5s": 91.2,
                    "GHS av": 89.4,
                    "Accepted": 1450,
                    "Rejected": 7,
                    "Elapsed": 86500,
                    "Best Share": "9.4T",
                }
            ],
        }
    if cmd == "stats":
        return {
            "STATUS": [{"STATUS": "S", "Code": 71, "Msg": "Stats"}],
            "STATS": [
                {"STATS": 0, "ID": "POOL0"},
                {
                    "STATS": 1,
                    "ID": "BM1397_0",
                    "temp2_0": 62.5,
                    "temp2_1": 48.2,
                    "temp3_0": 61.0,
                    "fan1": 4200,
                    "fan2": 4100,
                },
            ],
        }
    if cmd == "pools":
        return {
            "STATUS": [{"STATUS": "S", "Code": 54, "Msg": "Pools"}],
            "POOLS": [
                {
                    "POOL": 0,
                    "URL": "stratum+tcp://public-pool.io:21496",
                    "User": "bc1qtest.gamma01",
                    "Status": "Alive",
                    "Accepted": 1450,
                }
            ],
        }
    if cmd == "restart":
        # cgminer-family restart: accepted then the device reboots. The
        # counter proves the agent actually executed the command on the LAN.
        global _CGMINER_RESTARTS
        _CGMINER_RESTARTS += 1
        return {"STATUS": [{"STATUS": "S", "Code": 7, "Msg": "Restarting..."}]}
    return {"STATUS": [{"STATUS": "E", "Msg": f"unknown {cmd}"}]}


_CGMINER_RESTARTS = 0


_AXEOS_PAUSED = False  # estado de mining do mock AxeOS (espelha ESP-Miner)


def _axeos_info_body():
    """Payload de /api/system/info do mock. Reflete o estado de mining real:
    um miner pausado reporta miningPaused=true e hashrate 0 (não inventa
    hashrate de um device pausado) — é isso que o agente empurra e o servidor
    usa para derivar PAUSED/ONLINE (Issue #13/#16)."""
    info = dict(_AXEOS_INFO)
    info["miningPaused"] = _AXEOS_PAUSED
    if _AXEOS_PAUSED:
        info["hashrate"] = 0
    return info


class _AxeOSHandler(BaseHTTPRequestHandler):
    """Mock de um Bitaxe com AxeOS: responde /api/system/info com JSON.

    Dois miners compartilham o loopback (127.0.0.1), então distinguimos pelo
    header Host: quando o agente sonda o hostname `localhost`, este mock
    responde 404 e o probe cai no protocolo cgminer (:port2) — é assim que o
    harness consegue um miner AxeOS E um cgminer em dois "IPs" diferentes.

    Comandos suportados (contadores provam execução real na LAN):
      POST /api/system/restart · /api/system/identify → _AXEOS_RESTARTS
      POST /api/system/miningPause                    → _AXEOS_PAUSES
      POST /api/system/miningResume                   → _AXEOS_RESUMES
    """

    def log_message(self, *a):
        pass

    def _is_localhost_probe(self) -> bool:
        host = self.headers.get("Host", "").lower()
        return host.startswith("localhost")

    def do_GET(self):
        if self._is_localhost_probe():
            # Sonda do hostname `localhost` deve NÃO achar AxeOS aqui.
            self.send_response(404)
            self.end_headers()
        elif self.path.rstrip("/").endswith("/api/system/info"):
            body = json.dumps(_axeos_info_body()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # AxeOS commands over HTTP :80 — counters prove the agent actually
        # executed the queued command on the LAN (command fix).
        global _AXEOS_RESTARTS, _AXEOS_PAUSED, _AXEOS_PAUSES, _AXEOS_RESUMES
        path = self.path.rstrip("/")
        if self._is_localhost_probe():
            self.send_response(404)
            self.end_headers()
            return
        if path.endswith("/api/system/restart") or path.endswith(
            "/api/system/identify"
        ):
            _AXEOS_RESTARTS += 1
            body = b'{"success": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.endswith("/api/system/miningPause"):
            # ESP-Miner miningPause: pausa o hashing no mock → info reflete
            # miningPaused=true + hashrate 0 → servidor deriva PAUSED.
            _AXEOS_PAUSED = True
            _AXEOS_PAUSES += 1
            body = b'{"success": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.endswith("/api/system/miningResume"):
            # ESP-Miner miningResume: retoma → hashrate volta e o servidor
            # só sai de PAUSED quando a telemetria real mostra hashrate > 0.
            _AXEOS_PAUSED = False
            _AXEOS_RESUMES += 1
            body = b'{"success": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


_AXEOS_RESTARTS = 0
_AXEOS_PAUSES = 0
_AXEOS_RESUMES = 0


def _start_axeos_mock():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _AxeOSHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _start_cgminer_mock():
    """Mock de um Antminer (JSON-over-TCP :port) no loopback.

    O hostname `localhost` resolve para 127.0.0.1 (mesmo IP do mock AxeOS),
    mas o mock AxeOS responde 404 para sondas com Host=localhost — então o
    agente só acha o cgminer quando sonda `localhost` (fallback do probe)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _loop():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(2)
                data = conn.recv(4096)
                if data:
                    try:
                        cmd = json.loads(data.decode().strip()).get("command")
                    except (json.JSONDecodeError, ValueError):
                        cmd = None
                    conn.sendall(json.dumps(_cgminer_reply(cmd)).encode() + b"\x00")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    threading.Thread(target=_loop, daemon=True).start()
    return srv, stop, port


# ── Helpers HTTP ──────────────────────────────────────────────────────────


def _http_json(method, url, payload=None, token=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode(errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode(errors="replace"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _wait_for_server(base, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _free_port():
    # TOCTOU clássico (bind → close → reuso) — irrelevante num harness com
    # porta aleatória; não "consertar".
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _log_tail(path, n=40):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError as e:
        return f"(sem log: {e})"


# ── Fluxo principal ───────────────────────────────────────────────────────


def main() -> int:
    print("=" * 74)
    print("CYPHER65 // E2E — agente local ponta-a-ponta (servidor real + mocks)")
    print("=" * 74)

    tmp = Path(tempfile.mkdtemp(prefix="cypher65_e2e_"))
    keep = os.environ.get("CYPHER65_E2E_KEEP") == "1"
    db_path = tmp / "war_room.sqlite"
    server_log = tmp / "server.log"
    agent_log = tmp / "agent.log"

    procs = []
    axeos = cgminer = None
    try:
        # 1 ─ Mocks de miner na "LAN" (loopback)
        axeos, axeos_port = _start_axeos_mock()
        cgminer, cgminer_stop, cgminer_port = _start_cgminer_mock()
        print(
            f"  1. miners mock  ✓  AxeOS 127.0.0.1:{axeos_port} · "
            f"cgminer localhost:{cgminer_port}"
        )

        # 2 ─ Servidor real num DB descartável (modo self-host, nunca nuvem)
        server_port = _free_port()
        env = dict(os.environ)
        env.update(
            {
                "DB_PATH": str(db_path),
                "SECRET_KEY": "e2e-secret-key-0001",
                "PORT": str(server_port),
                # Poll curto do servidor para o bloco axe_fleet do /api/snapshot
                # (reconstruído a cada ciclo) atualizar rápido e o teste ser
                # determinístico. O AGENTE tem o próprio CYPHER65_POLL_INTERVAL.
                "POLL_INTERVAL": "3",
                "RATE_LIMIT_PER_MINUTE": "100000",
                "AUTH_RATE_LIMIT_PER_MINUTE": "100000",
            }
        )
        for k in (
            "RENDER",
            "RENDER_SERVICE_ID",
            "RENDER_INSTANCE_ID",
            "CLOUD_MODE",
            "API_KEY",
            "TENANT_API_KEYS",
        ):
            env.pop(k, None)
        with open(server_log, "wb") as flog:
            server = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=str(ROOT),
                env=env,
                stdout=flog,
                stderr=subprocess.STDOUT,
            )
        procs.append(server)
        base = f"http://127.0.0.1:{server_port}"
        if not _wait_for_server(base):
            print(
                f"  ❌ servidor não subiu em {POLL_WINDOW_S}s — log:\n{_log_tail(server_log)}"
            )
            return 1
        print(f"  2. servidor real ✓  {base} (DB descartável)")

        # 3 ─ Registro de usuário + AGENT TOKEN (o clique de CONNECT AGENT)
        code, reg = _http_json(
            "POST",
            base + "/api/auth/register",
            {"username": USERNAME, "password": PASSWORD},
        )
        if code != 201 or not reg.get("access_token"):
            print(f"  ❌ register falhou (HTTP {code}): {reg}")
            return 1
        access = reg["access_token"]
        code, tok = _http_json("POST", base + "/api/agent/token", {}, token=access)
        if code != 200 or not tok.get("token"):
            print(f"  ❌ /api/agent/token falhou (HTTP {code}): {tok}")
            return 1
        agent_token = tok["token"]
        server_url = tok.get("server_url", "")
        if server_url != base:
            print(f"  ❌ server_url inesperado: {server_url!r} (esperado {base!r})")
            return 1
        print(
            "  3. agente token  ✓  tenant=%s · server_url=%s"
            % (tok.get("tenant_id"), server_url)
        )

        # 4 ─ Agente real (mesmas env vars do one-liner Docker da UI)
        aenv = dict(os.environ)
        aenv.update(
            {
                "CYPHER65_SERVER_URL": base,
                "CYPHER65_AGENT_TOKEN": agent_token,
                "CYPHER65_POLL_INTERVAL": "2",
                "CYPHER65_DEVICES": "127.0.0.1,localhost",
                "CYPHER65_AXEOS_PORT": str(axeos_port),
                "CYPHER65_CGMINER_PORT": str(cgminer_port),
            }
        )
        with open(agent_log, "wb") as flog:
            agent_proc = subprocess.Popen(
                [sys.executable, "agent/agent.py"],
                cwd=str(ROOT),
                env=aenv,
                stdout=flog,
                stderr=subprocess.STDOUT,
            )
        procs.append(agent_proc)
        print("  4. agente local ✓  (poll 2s → registra → empurra telemetria)")

        # 5 ─ Asserta devices ONLINE em /api/axe-fleet/devices
        devices = []
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            code, resp = _http_json(
                "GET", base + "/api/axe-fleet/devices", token=access
            )
            if code == 200:
                devices = resp.get("devices") or []
                if len(devices) >= 2 and all(
                    d.get("status") == "ONLINE" and int(d.get("hashrate_hs") or 0) > 0
                    for d in devices
                ):
                    break
            time.sleep(2)
        if len(devices) < 2:
            print(
                "  ❌ devices não registrados no tempo — log do agente:\n"
                + _log_tail(agent_log)
            )
            print("     log do servidor (últimas linhas):\n" + _log_tail(server_log))
            return 1
        bad = [
            d
            for d in devices
            if d.get("status") != "ONLINE" or int(d.get("hashrate_hs") or 0) <= 0
        ]
        if bad:
            print(
                f"  ❌ devices com status/hashrate errados: {json.dumps(bad, default=str)}"
            )
            return 1
        # agent_managed=1 é o que impede o poll do servidor de marcar o device
        # como OFFLINE (a nuvem não alcança a LAN) — coração do fluxo SaaS.
        if not all(bool(d.get("agent_managed")) for d in devices):
            print(
                "  ❌ nem todo device está agent_managed: "
                + json.dumps(devices, default=str)
            )
            return 1
        print("  5. /api/axe-fleet/devices ✓  %d device(s) ONLINE" % len(devices))

        # 6 ─ Asserta o bloco axe_fleet em /api/snapshot
        fleet = []
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            code, snap = _http_json("GET", base + "/api/snapshot", token=access)
            if code == 200:
                fleet = snap.get("axe_fleet") or []
                if len(fleet) >= 2 and all(
                    int(e.get("hashrate_hs") or 0) > 0 for e in fleet
                ):
                    break
            time.sleep(2)
        if len(fleet) < 2:
            print(
                "  ❌ axe_fleet vazio/parcial no /api/snapshot — log do agente:\n"
                + _log_tail(agent_log)
            )
            return 1
        print(
            "  6. /api/snapshot    ✓  axe_fleet com %d device(s) e telemetria"
            % len(fleet)
        )

        # 7 ─ Command round-trip: enqueue restart → agent pulls → EXECUTES on
        #    the LAN → acks. This is the regression test for the command fix
        #    (server now sends ip_address; the agent opens a real socket).
        #    The mock counters prove the miner was actually restarted.
        cgminer_dev = next(
            d for d in devices if d.get("model", "").lower().startswith("antminer")
        )
        axeos_dev = next(d for d in devices if d.get("model", "") == "Gamma 900")
        # cgminer: restart via /api/axe-fleet/devices/<id>/restart (agent path).
        code, resp = _http_json(
            "POST",
            base + f"/api/axe-fleet/devices/{cgminer_dev['id']}/restart",
            payload={},
            token=access,
        )
        if code not in (200, 201) or not resp.get("queued"):
            print("  ❌ restart enqueue (cgminer) falhou: ", code, resp)
            return 1
        # AxeOS: same endpoint, bitaxe device.
        code, resp = _http_json(
            "POST",
            base + f"/api/axe-fleet/devices/{axeos_dev['id']}/restart",
            payload={},
            token=access,
        )
        if code not in (200, 201) or not resp.get("queued"):
            print("  ❌ restart enqueue (axeos) falhou: ", code, resp)
            return 1
        # Poll window: agent pulls commands on every cycle (2s) and executes.
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            if _AXEOS_RESTARTS >= 1 and _CGMINER_RESTARTS >= 1:
                break
            time.sleep(1)
        if _AXEOS_RESTARTS < 1:
            print(
                "  ❌ AxeOS mock nunca recebeu o restart (agente não executou):"
                "\n" + _log_tail(agent_log)
            )
            return 1
        if _CGMINER_RESTARTS < 1:
            print(
                "  ❌ cgminer mock nunca recebeu o restart (agente não executou):"
                "\n" + _log_tail(agent_log)
            )
            return 1
        print(
            "  7. command round-trip ✓  restart AXEOS(%d) + cgminer(%d) executados na LAN"
            % (_AXEOS_RESTARTS, _CGMINER_RESTARTS)
        )

        # 8 ─ Pause/Resume round-trip real (Issue #16): mesmo caminho
        #    ponta-a-ponta do restart — enqueue → agente puxa → EXECUTA
        #    miningPause/miningResume no mock AxeOS (contadores) → a próxima
        #    telemetria empurrada carrega mining_paused/hashrate real → o
        #    servidor deriva PAUSED/ONLINE (não só o reflexo do enqueue).

        def _device_status(dev_id):
            """GET /api/axe-fleet/devices → dict do device (ou {})."""
            _code, _resp = _http_json(
                "GET", base + "/api/axe-fleet/devices", token=access
            )
            return next(
                (x for x in (_resp.get("devices") or []) if x.get("id") == dev_id), {}
            )

        # Pause: enqueue → servidor reflete PAUSED no ato (Issue #13).
        code, resp = _http_json(
            "POST",
            base + f"/api/axe-fleet/devices/{axeos_dev['id']}/pause",
            payload={},
            token=access,
        )
        if code not in (200, 201) or not resp.get("queued"):
            print("  ❌ pause enqueue falhou: ", code, resp)
            return 1
        # Issue #13: o servidor reflete PAUSED no ato do enqueue. MAS o agente
        # empurra telemetria ANTES de puxar comandos — entre o enqueue e a
        # execução do miningPause no mock, a telemetria (mining_paused=False +
        # hashrate>0) pode re-derivar ONLINE. Poll curto em vez de assert
        # único (raça): reflete de volta a PAUSED assim que o agente executa.
        reflected_ok = False
        deadline = time.time() + 15
        while time.time() < deadline:
            if _device_status(axeos_dev["id"]).get("status") == "PAUSED":
                reflected_ok = True
                break
            time.sleep(1)
        if not reflected_ok:
            print("  ❌ status PAUSED não refletido após o enqueue do pause")
            return 1
        # O AGENTE REAL puxa e executa o miningPause no mock (contador).
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            if _AXEOS_PAUSES >= 1:
                break
            time.sleep(1)
        if _AXEOS_PAUSES < 1:
            print(
                "  ❌ AxeOS mock nunca recebeu o miningPause (agente não executou):"
                "\n" + _log_tail(agent_log)
            )
            return 1
        # Telemetria real do mock pausado (hashrate 0 + miningPaused=true)
        # confirma PAUSED no servidor — não só o reflexo do enqueue.
        paused_ok = False
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            if _device_status(axeos_dev["id"]).get("status") == "PAUSED":
                paused_ok = True
                break
            time.sleep(2)
        if not paused_ok:
            print(
                "  ❌ servidor não confirmou PAUSED via telemetria do agente:\n"
                + _log_tail(agent_log)
            )
            return 1
        # Resume: enqueue → agente executa miningResume → telemetria real volta
        # com hashrate → o servidor só sai de PAUSED quando hashrate > 0.
        code, resp = _http_json(
            "POST",
            base + f"/api/axe-fleet/devices/{axeos_dev['id']}/resume",
            payload={},
            token=access,
        )
        if code not in (200, 201) or not resp.get("queued"):
            print("  ❌ resume enqueue falhou: ", code, resp)
            return 1
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            if _AXEOS_RESUMES >= 1:
                break
            time.sleep(1)
        if _AXEOS_RESUMES < 1:
            print(
                "  ❌ AxeOS mock nunca recebeu o miningResume (agente não executou):"
                "\n" + _log_tail(agent_log)
            )
            return 1
        resumed_ok = False
        deadline = time.time() + POLL_WINDOW_S
        while time.time() < deadline:
            d = _device_status(axeos_dev["id"])
            if d.get("status") == "ONLINE" and int(d.get("hashrate_hs") or 0) > 0:
                resumed_ok = True
                break
            time.sleep(2)
        if not resumed_ok:
            print(
                "  ❌ servidor não voltou a ONLINE via telemetria do agente:\n"
                + _log_tail(agent_log)
            )
            return 1
        # Refresh para o resumo final mostrar o estado pós-round-trip.
        _, resp = _http_json("GET", base + "/api/axe-fleet/devices", token=access)
        devices = resp.get("devices") or devices
        print(
            "  8. pause/resume round-trip ✓  miningPause(%d) + miningResume(%d) "
            "executados na LAN · status ONLINE→PAUSED→ONLINE"
            % (_AXEOS_PAUSES, _AXEOS_RESUMES)
        )

        # Resumo
        print("-" * 74)
        print(f"{'IP':<12}{'model':<20}{'status':<9}{'HR (H/s)':<16}{'agent':<6}")
        for d in devices:
            print(
                "%-12s%-20s%-9s%-16d%s"
                % (
                    d.get("ip_address"),
                    (d.get("model") or "?")[:19],
                    d.get("status"),
                    int(d.get("hashrate_hs") or 0),
                    "1" if d.get("agent_managed") else "0",
                )
            )
        print("-" * 74)
        print(
            "✅ E2E OK — o fluxo completo do agente local funciona "
            "(token → registro → telemetria → comandos → dashboard)."
        )
        return 0

    except KeyboardInterrupt:
        print("\ninterrompido pelo usuário")
        return 130
    except Exception as e:
        print(f"  ❌ exceção no harness: {type(e).__name__}: {e}")
        print("     log do agente (últimas linhas):\n" + _log_tail(agent_log))
        print("     log do servidor (últimas linhas):\n" + _log_tail(server_log))
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
                axeos.server_close()  # libera o listening socket do mock
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
