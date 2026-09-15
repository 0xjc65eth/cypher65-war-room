#!/usr/bin/env python3
"""verify_production.py — pos-deploy read-only validation of a live deployment.

Usage:
  python3 scripts/verify_production.py --base-url https://exemplo.onrender.com
  python3 scripts/verify_production.py --base-url http://127.0.0.1:8765 --skip-bundle

  # valida o caminho autenticado (o token NUNCA aparece na saída)
  VERIFY_ACCESS_TOKEN="$JWT" python3 scripts/verify_production.py --base-url URL \
      --expect-tenant default

  # `--access-token` também funciona, mas argv é visível em `ps` e no histórico
  # do shell: prefira o env quando o token for de verdade.

  python3 scripts/verify_production.py --base-url URL --json    # saída de máquina

Exit codes: 0 = tudo verde · 1 = falhou (pode convergir — retry faz sentido) ·
            2 = uso/entorno · 3 = falhou e RETRY NÃO CONSERTA. O exit 3 existe
            porque o loop do `diagnose-render` repete 20× (~8 min): repetir uma
            configuração errada gasta o dobro de CI para chegar no mesmo
            vermelho. O 3 só aparece depois que o processo live provou ser o
            código deste commit (`deploy marker`).

O QUE ELE RESOLVE
-----------------
Duas falhas reais passaram por "deploy verificado" e chegaram em produção:

  · #576 — o painel polla `/api/snapshot`, que serve o dict do poll GLOBAL. O
    campo `pool_detection` existia só no caminho de SESSÃO: o bundle novo estava
    no ar, o JSON não tinha as chaves, e a feature simplesmente não existia. O
    gate de deploy passava porque o marcador de backend que ele usava era um
    texto de um commit ANTERIOR (`IP privado`, do #570) — stale por construção.
  · #578 — `/api/agent/token` cunhava um JWT de frota de 1 ano para um POST
    anônimo numa instância pública. Nenhum gate olhava essa rota.
  · #586 — `REVOKED_TOKENS_DB=1` foi ligada no blueprint sem sonda nenhuma. Uma
    flag no `render.yaml` não prova que o processo a recebeu, e persistir num
    disco efêmero (free tier) SEM o backup do gist não é persistir. A própria
    rota de revogação também não era olhada por gate algum.

Por isso o marcador do schema aqui **não é uma lista fixa**: as chaves esperadas
são extraídas do PRÓPRIO `app.py` do checkout que está sendo deployado (os
literais que constroem o snapshot global). O check é, por construção, específico
do commit — não envelhece.

REQUISIÇÕES FEITAS (todas read-only ou recusadas antes de qualquer efeito)
-------------------------------------------------------------------------
  GET  /api/healthz                 leitura
  GET  /api/snapshot                leitura (o payload que o painel consome)
  GET  /static/app.js               leitura (paridade de bundle)
  GET  /agent/agent.py              leitura (o artefato que o usuário instala)
  POST /api/network/scan            recusado na nuvem ANTES do scan (400 is_cloud)
  POST /api/axe-fleet/scan          recusado na nuvem ANTES do scan (400 is_cloud)
  POST /api/agent/token             anônimo: recusado (403). Com --access-token:
                                    cunha o token DO CHAMADOR (o caminho legítimo)
  POST /api/agent/tokens/revoke      anônimo: recusado (403) — nunca chamado em
                                    self-host, onde ele REVOGARIA de verdade
  POST /api/agent/register          sem token: 401 antes de tocar no registry
  GET  /api/healthz → persistence    leitura (modo da blacklist + durabilidade)

Num self-host (sem flag de nuvem) os dois scans NÃO são disparados: um verificador
não deve varrer a LAN de ninguém. Eles saem como `skip`, com o motivo.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Um literal conta como "snapshot global" se tiver estas chaves — as mesmas que
# os produtores carregam desde muito antes desta issue (app.py: defaults de
# módulo, reset_memory_state() e _do_poll()).
_SNAPSHOT_SHAPE = {"ts", "btc_address", "pool"}

CLOUD_ENV_FLAGS = ("RENDER", "RENDER_SERVICE_ID", "RENDER_INSTANCE_ID", "CLOUD_MODE")


# ══════════════════════════════════════════════════════════════════════════
#  Fonte da verdade local (o contrato do commit que está sendo verificado)
# ══════════════════════════════════════════════════════════════════════════


def snapshot_keys_by_producer(
    app_py: pathlib.Path | None = None,
) -> tuple[set[str], set[str]]:
    """``(chaves_de_boot, chaves_do_poll)`` do snapshot global, do checkout local.

    A distinção importa porque o snapshot tem DOIS tempos: o boot (default de
    módulo / `reset_memory_state`) já serve as chaves dele, e o primeiro poll
    (`_do_poll`) acrescenta as do ciclo. Um app recém-subido que ainda não
    pollou tem o boot e não tem o poll — um verificador que exigisse tudo de
    uma vez daria vermelho numa janela de 15s legítima.

    Derivar isto do checkout (em vez de manter uma lista no CI) é o que torna o
    marcador específico do commit: quando alguém adiciona uma chave a um
    produtor e esquece o outro, a produção acusa sozinha (#576).
    """
    path = app_py or (ROOT / "app.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def literal_keys(node: ast.Dict) -> set[str] | None:
        literal = {
            k.value
            for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        return literal if _SNAPSHOT_SHAPE <= literal else None

    boot: set[str] = set()
    poll: set[str] = set()
    for node in tree.body:  # literais de nível de módulo
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "latest_snapshot":
                    if isinstance(node.value, ast.Dict):
                        keys = literal_keys(node.value)
                        if keys:
                            boot |= keys
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(func):
            if not isinstance(node, ast.Dict):
                continue
            keys = literal_keys(node)
            if keys is None:
                continue
            # `reset_memory_state` devolve o dict aos defaults do boot;
            # `_do_poll` monta o do ciclo.
            (boot if func.name == "reset_memory_state" else poll).update(keys)

    if not boot or not poll:
        raise RuntimeError(
            f"não consegui derivar boot/poll do snapshot global em {path} "
            f"(boot={len(boot)}, poll={len(poll)})"
        )
    return boot, poll - boot  # as de boot são exigíveis já; o resto converge


def global_snapshot_keys(app_py: pathlib.Path | None = None) -> set[str]:
    """União das chaves de boot e de poll — o contrato completo do snapshot."""
    boot, poll = snapshot_keys_by_producer(app_py)
    return boot | poll


def sha256_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_gzip(body: bytes) -> bytes:
    """`/static/app.js` pode chegar gzipado mesmo sem pedirmos."""
    if body[:2] == b"\x1f\x8b":
        import gzip

        return gzip.decompress(body)
    return body


# ══════════════════════════════════════════════════════════════════════════
#  Transporte
# ══════════════════════════════════════════════════════════════════════════


class Response:
    __slots__ = ("status", "body", "error")

    def __init__(self, status: int, body: bytes = b"", error: str = ""):
        self.status = status
        self.body = body
        self.error = error

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


def http(
    method: str, url: str, timeout: float = 20.0, headers: dict | None = None
) -> Response:
    """Um request, sem retry. Nunca levanta: erro vira `Response(error=...)`.

    Sem retry de propósito: isto valida um deploy recém-feito, e uma resposta
    intermitente é informação, não algo a esconder atrás de uma espera.
    """
    request = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return Response(resp.status, resp.read())
    except urllib.error.HTTPError as exc:  # 4xx/5xx são respostas, não falhas
        return Response(exc.code, exc.read() or b"")
    except Exception as exc:  # noqa: BLE001 — rede/DNS/timeout viram o detalhe
        return Response(0, b"", f"{type(exc).__name__}: {exc}")


Transport = "callable"  # assinatura: (method, url, timeout, headers) -> Response


# ══════════════════════════════════════════════════════════════════════════
#  Checks — todos puros: recebem `get` e devolvem (nome, ok, detalhe)
# ══════════════════════════════════════════════════════════════════════════


def check_healthz(base: str, get, timeout: float) -> tuple:
    resp = get("GET", f"{base}/api/healthz", timeout, None)
    if resp.error:
        return "healthz", False, resp.error
    if resp.status != 200:
        return "healthz", False, f"HTTP {resp.status}"
    data = resp.json() or {}
    if not data.get("ok"):
        return "healthz", False, f"ok={data.get('ok')!r}"
    return "healthz", True, f"ok · cloud={bool(data.get('cloud'))}"


def check_deploy_marker(health: dict | None) -> tuple:
    """O processo que respondeu é o código DESTE commit?

    Durante um deploy a instância ANTIGA continua servindo — então um check
    vermelho pode ser só convergência, e um retry resolve. Este marcador é o
    que permite distinguir os dois casos: ele exige algo que só o código novo
    publica. `persistence.revoked_tokens_db` (Issue #586) é o mais recente.

    O princípio é o do #576: um marcador que NÃO muda com o commit não prova
    nada. Foi por isso que o gate ficou verde servindo um backend antigo.

    Atenção: a PRESENÇA da chave prova o código; o VALOR dela é a configuração
    (checada em `persistence · revoked_tokens_db`). Dois fatos, dois remédios —
    redeploy num caso, sincronizar o blueprint no outro.
    """
    name = "deploy marker"
    flags = (health or {}).get("persistence")
    if not isinstance(flags, dict):
        return name, False, "healthz sem o bloco `persistence`"
    if "revoked_tokens_db" not in flags:
        return (
            name,
            False,
            "`persistence.revoked_tokens_db` ausente — quem responde é um "
            "processo ANTERIOR a este commit (deploy ainda em andamento?)",
        )
    return name, True, "o código deste commit está no ar"


def check_snapshot_schema(
    base: str,
    get,
    timeout: float,
    expected: set[str],
    required: set[str] | None = None,
) -> tuple:
    """O payload que o painel consome carrega o que os produtores escrevem (#576).

    ``required`` (padrão: ``expected``) é o que tem de estar lá AGORA — as
    chaves de boot. ``expected`` é o conjunto completo: as de poll podem
    chegar no próximo ciclo, então quem quiser tolerar a janela de convergência
    repete a chamada (é o que o runner faz, com `--schema-wait`).
    """
    hard = expected if required is None else required
    resp = get("GET", f"{base}/api/snapshot", timeout, None)
    if resp.error:
        return "snapshot schema", False, resp.error
    if resp.status != 200:
        return "snapshot schema", False, f"HTTP {resp.status}"
    data = resp.json()
    if not isinstance(data, dict):
        return "snapshot schema", False, "corpo não é um objeto JSON"

    served = set(data)
    missing_now = sorted(hard - served)
    if missing_now:
        return (
            "snapshot schema",
            False,
            f"{len(missing_now)} chave(s) de BOOT ausentes no payload servido: {missing_now}",
        )
    missing_after_poll = sorted(expected - served)
    if missing_after_poll:
        return (
            "snapshot schema",
            False,
            f"{len(missing_after_poll)} chave(s) do poll ausentes no payload servido: "
            f"{missing_after_poll}",
        )
    return (
        "snapshot schema",
        True,
        f"{len(data)} chaves · nenhuma das {len(expected)} esperadas falta",
    )


def check_bundle_parity(base: str, get, timeout: float, app_js: pathlib.Path) -> tuple:
    resp = get("GET", f"{base}/static/app.js", timeout, None)
    if resp.error:
        return "bundle parity", False, resp.error
    if resp.status != 200:
        return "bundle parity", False, f"HTTP {resp.status}"
    served = hashlib.md5(strip_gzip(resp.body)).hexdigest()
    local = hashlib.md5(app_js.read_bytes()).hexdigest()
    if served != local:
        return "bundle parity", False, f"servido {served[:12]}… ≠ local {local[:12]}…"
    return "bundle parity", True, f"md5 {local[:12]}… idêntico"


def check_agent_script_parity(
    base: str, get, timeout: float, agent_py: pathlib.Path
) -> tuple:
    """O `agent.py` que o usuário baixa é o do repositório (não uma cópia velha)."""
    resp = get("GET", f"{base}/agent/agent.py", timeout, None)
    if resp.error:
        return "agent.py parity", False, resp.error
    if resp.status != 200:
        return "agent.py parity", False, f"HTTP {resp.status}"
    served = hashlib.sha256(resp.body).hexdigest()
    local = sha256_of(agent_py)
    if served != local:
        return "agent.py parity", False, f"servido {served[:12]}… ≠ repo {local[:12]}…"
    return "agent.py parity", True, f"sha256 {local[:12]}… idêntico"


def check_cloud_command_guard(
    base: str, get, timeout: float, path: str, cloud: bool
) -> tuple:
    """Numa instância de nuvem, varrer 'a LAN' tem de ser recusado — e antes do scan.

    Em self-host o check é `skip`: disparar um scan de sub-rede de verdade não é
    papel de um verificador.
    """
    name = f"guard {path}"
    if not cloud:
        return name, None, "skip — self-host (não disparo scan de LAN daqui)"
    resp = get("POST", f"{base}{path}", timeout, None)
    if resp.error:
        return name, False, resp.error
    if resp.status != 400:
        return name, False, f"HTTP {resp.status} (esperado 400 is_cloud)"
    data = resp.json() or {}
    if not data.get("is_cloud"):
        return name, False, f"400 sem is_cloud: {str(data)[:120]}"
    return name, True, "400 · is_cloud (recusado antes de varrer)"


def check_agent_token_anonymous(base: str, get, timeout: float, cloud: bool) -> tuple:
    """O furo do #578: anônimo na nuvem NÃO ganha token de frota.

    Em self-host o modo aberto é o comportamento esperado (o operador é o dono
    da máquina), então o check é afirmado ao contrário — e o resultado nunca
    carrega o token.
    """
    name = "agent token anônimo"
    resp = get("POST", f"{base}/api/agent/token", timeout, None)
    if resp.error:
        return name, False, resp.error
    if cloud:
        if resp.status != 403:
            return (
                name,
                False,
                f"HTTP {resp.status} (esperado 403 — modo aberto numa instância pública)",
            )
        data = resp.json() or {}
        if data.get("code") != "AGENT_TOKEN_NEEDS_IDENTITY":
            return name, False, f"403 com code inesperado: {data.get('code')!r}"
        if data.get("token"):
            return name, False, "403 mas o corpo traz um token"
        return name, True, "403 · AGENT_TOKEN_NEEDS_IDENTITY, sem token no corpo"
    if resp.status != 200:
        return (
            name,
            False,
            f"HTTP {resp.status} (self-host: modo aberto deveria emitir)",
        )
    return name, True, "200 · modo aberto do self-host preservado"


def check_agent_token_with_identity(
    base: str, get, timeout: float, access_token: str, expect_tenant: str
) -> tuple:
    """O caminho legítimo, com credencial. Só roda quando o token é fornecido."""
    name = "agent token com identidade"
    resp = get(
        "POST",
        f"{base}/api/agent/token",
        timeout,
        {"Authorization": f"Bearer {access_token}"},
    )
    if resp.error:
        return name, False, resp.error
    if resp.status != 200:
        return name, False, f"HTTP {resp.status}: {resp.text()[:160]}"
    data = resp.json() or {}
    if not data.get("token"):
        return name, False, "200 sem token no corpo"
    tenant = data.get("tenant_id") or ""
    if expect_tenant and tenant != expect_tenant:
        return name, False, f"tenant {tenant!r} ≠ esperado {expect_tenant!r}"
    # O token NUNCA vai para a saída (nem truncado): um log de CI não é lugar.
    return name, True, f"200 · tenant={tenant} · expires_in={data.get('expires_in')}"


def check_agent_revoke_anonymous(base: str, get, timeout: float, cloud: bool) -> tuple:
    """A rota que derruba a frota tem de recusar quem não provou identidade.

    Nenhum gate olhava esta rota (Issue #586). Se ela aceitar um POST anônimo,
    qualquer estranho invalida todos os tokens de agente do tenant com um
    curl — o kill switch é tão sensível quanto a cunhagem.

    Em self-host o check é `skip`, e não por preguiça: no modo aberto o POST
    anônimo **revoga de verdade** (incrementa o epoch do tenant). Um validador
    não muta o ambiente que está medindo.
    """
    name = "agent revoke anônimo"
    if not cloud:
        return (
            name,
            None,
            "skip — self-host: em modo aberto o POST anônimo revoga de verdade "
            "(um validador não muta o que mede)",
        )
    resp = get("POST", f"{base}/api/agent/tokens/revoke", timeout, None)
    if resp.error:
        return name, False, resp.error
    if resp.status != 403:
        return (
            name,
            False,
            f"HTTP {resp.status} (esperado 403 — anônimo não pode derrubar a frota)",
        )
    data = resp.json() or {}
    # Duas camadas podem recusar, e as duas são legítimas: sem auth configurada
    # a recusa é a identidade do #578 (`_require_caller_identity_on_cloud`); com
    # auth configurada o RBAC recusa antes (`permission denied`). O check do
    # MINT acima exige o code exato porque ele codifica a regressão do #578;
    # aqui o que não pode variar é o EFEITO — nenhuma revogação pode ter
    # acontecido.
    refused = data.get("code") == "AGENT_TOKEN_NEEDS_IDENTITY" or (
        data.get("error") == "permission denied"
    )
    if not refused:
        return name, False, f"403 sem recusa reconhecível: {str(data)[:120]}"
    if data.get("success") or data.get("active_epoch") is not None:
        return name, False, "403 mas o corpo sugere que a revogação aconteceu"
    return name, True, "403 · recusado antes de qualquer efeito"


def check_persistence_revoked_db(health: dict | None, cloud: bool) -> tuple:
    """A flag está no PROCESSO — não só no `render.yaml` (Issue #586).

    Um valor no blueprint não prova nada sobre o código que está rodando: se o
    Render não aplicar o `render.yaml`, a flag fica no git e a produção segue
    com a blacklist só em memória, sem ninguém perceber.
    """
    name = "persistence · revoked_tokens_db"
    flags = (health or {}).get("persistence") or {}
    if not cloud:
        return (
            name,
            None,
            f"skip — self-host (revoked_tokens_db={flags.get('revoked_tokens_db')})",
        )
    if flags.get("revoked_tokens_db") is not True:
        return (
            name,
            False,
            "revoked_tokens_db != true — a flag existe no render.yaml e não no "
            "processo: o deploy não aplicou o blueprint (sincronize o serviço "
            "no Render) e a revogação continua só em memória",
        )
    return name, True, "true · a revogação sobrevive a um restart do processo"


def check_persistence_durability(health: dict | None, cloud: bool) -> tuple:
    """Persistir num disco efêmero sem backup não é persistir (Issue #586).

    A tabela `revoked_tokens` vive em `data/war_room.sqlite`, então ela só
    sobrevive a um redeploy se o backup remoto do gist a levar junto. Com
    `plan: free` (disco efêmero) e sem `remote_backup`, ligar
    `REVOKED_TOKENS_DB=1` é decorativo — e o mesmo vale para usuários, devices
    e alertas que moram no mesmo arquivo.
    """
    name = "persistence · durabilidade"
    flags = (health or {}).get("persistence") or {}
    if not cloud:
        return (
            name,
            None,
            f"skip — self-host (disco próprio; remote_backup={flags.get('remote_backup')})",
        )
    if flags.get("remote_backup") is not True:
        return (
            name,
            False,
            "remote_backup=false — o disco do free tier é EFÊMERO: sem "
            "GITHUB_TOKEN + REMOTE_BACKUP_ENCRYPTION_KEY, a tabela "
            "revoked_tokens (e usuários/devices/alertas em data/war_room.sqlite) "
            "some no próximo redeploy",
        )
    return name, True, "true · o gist leva e restaura data/war_room.sqlite"


def check_agent_register_without_token(base: str, get, timeout: float) -> tuple:
    name = "agent register sem token"
    resp = get(
        "POST",
        f"{base}/api/agent/register",
        timeout,
        {"Content-Type": "application/json"},
    )
    if resp.error:
        return name, False, resp.error
    if resp.status != 401:
        return name, False, f"HTTP {resp.status} (esperado 401)"
    return name, True, "401 (recusado antes de tocar no registry)"


# ══════════════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════════════


def probe_health(base: str, get, timeout: float) -> dict | None:
    """O corpo de `/api/healthz` — ou None se ele não respondeu 200.

    Uma sonda, três fatos: a topologia vista PELO SERVIDOR (`cloud`), o modo da
    blacklist (`persistence.revoked_tokens_db`) e a durabilidade
    (`persistence.remote_backup`). `cloud` não pode vir do `os.environ` de quem
    roda: o validador roda no CI (sem RENDER) verificando uma produção que É
    nuvem — a resposta do servidor é a única fonte correta.
    """
    resp = get("GET", f"{base}/api/healthz", timeout, None)
    if resp.status != 200:
        return None
    return resp.json() or {}


def probe_cloud(base: str, get, timeout: float):
    """Só o modo (`healthz.cloud`), ou None quando o healthz não responde."""
    health = probe_health(base, get, timeout)
    if health is None:
        return None
    return bool(health.get("cloud"))


# Checks que podem falhar num app recém-subido e ficar verdes no próximo poll.
# Só o schema do snapshot: o boot já serve as chaves dele, o primeiro poll
# (≤15s) traz o resto — a janela está medida em `--schema-wait`.
_CONVERGING = {"snapshot schema"}


def durable_failures(results: list[tuple]) -> list[str]:
    """Falhas que repetir NÃO conserta — o loop de CI deve parar nelas.

    Antes do `deploy marker` passar, um vermelho é (provavelmente) a instância
    antiga servindo: retry. Depois que ele passa, o processo É este código, e
    só o schema do snapshot tem direito de esperar. Persistência sem durabilidade
    é uma configuração ausente: 20 tentativas depois o resultado é o mesmo.
    """
    if not any(name == "deploy marker" and ok is True for name, ok, _ in results):
        return []
    return [name for name, ok, _ in results if ok is False and name not in _CONVERGING]


def run_checks(
    base_url: str,
    *,
    get=http,
    timeout: float = 20.0,
    expected_keys: set[str] | None = None,
    app_js: pathlib.Path | None = None,
    agent_py: pathlib.Path | None = None,
    skip_bundle: bool = False,
    skip_agent_script: bool = False,
    access_token: str = "",
    expect_tenant: str = "",
    schema_wait: float = 0.0,
) -> list[tuple]:
    """Roda todos os checks e devolve ``[(nome, True|False|None, detalhe), …]``.

    ``None`` no segundo campo = `skip` (com o motivo no detalhe) — nunca um
    verde silencioso.
    """
    base = base_url.rstrip("/")
    expected = expected_keys if expected_keys is not None else global_snapshot_keys()
    boot, poll_keys = snapshot_keys_by_producer()
    if expected_keys is not None:
        # Um `expected_keys` explícito (testes) não tem classificação: tudo é
        # exigível já.
        boot = set(expected)
    health = probe_health(base, get, timeout)
    cloud = None if health is None else bool(health.get("cloud"))

    results = [check_healthz(base, get, timeout)]
    results.append(check_deploy_marker(health))
    # O schema converge em um ciclo de poll (15s) num app recém-subido; exigir
    # as chaves de poll de uma vez acusaria uma janela legítima de boot.
    deadline = time.monotonic() + schema_wait
    while True:
        schema = check_snapshot_schema(base, get, timeout, expected, boot)
        if schema[1] or time.monotonic() >= deadline:
            break
        time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
    results.append(schema)
    if skip_bundle:
        results.append(("bundle parity", None, "skip — --skip-bundle"))
    else:
        results.append(
            check_bundle_parity(
                base, get, timeout, app_js or (ROOT / "static" / "app.js")
            )
        )
    if skip_agent_script:
        results.append(("agent.py parity", None, "skip — --skip-agent-script"))
    else:
        results.append(
            check_agent_script_parity(
                base, get, timeout, agent_py or (ROOT / "agent" / "agent.py")
            )
        )

    if cloud is None:
        reason = "skip — /api/healthz não respondeu (modo indefinido)"
        results.append(("guard /api/network/scan", None, reason))
        results.append(("guard /api/axe-fleet/scan", None, reason))
        results.append(("agent token anônimo", None, reason))
        results.append(("agent revoke anônimo", None, reason))
        results.append(("persistence · revoked_tokens_db", None, reason))
        results.append(("persistence · durabilidade", None, reason))
    else:
        results.append(
            check_cloud_command_guard(
                base, get, timeout, "/api/network/scan", bool(cloud)
            )
        )
        results.append(
            check_cloud_command_guard(
                base, get, timeout, "/api/axe-fleet/scan", bool(cloud)
            )
        )
        results.append(check_agent_token_anonymous(base, get, timeout, bool(cloud)))
        results.append(check_agent_revoke_anonymous(base, get, timeout, bool(cloud)))
        results.append(check_persistence_revoked_db(health, bool(cloud)))
        results.append(check_persistence_durability(health, bool(cloud)))

    if access_token:
        results.append(
            check_agent_token_with_identity(
                base, get, timeout, access_token, expect_tenant
            )
        )
    else:
        results.append(
            (
                "agent token com identidade",
                None,
                "skip — informe VERIFY_ACCESS_TOKEN (ou --access-token) para validar "
                "o caminho autenticado",
            )
        )

    results.append(check_agent_register_without_token(base, get, timeout))
    return results


# ══════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════

_MARK = {True: "✅", False: "❌", None: "⏭ "}


def _print_report(results: list[tuple], base_url: str) -> None:
    width = max(len(name) for name, _, _ in results)
    print(f"\nverificação de produção — {base_url}\n" + "─" * 60)
    for name, ok, detail in results:
        print(f"{_MARK.get(ok, '?')} {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in results if ok is False]
    skipped = [name for name, ok, _ in results if ok is None]
    print("─" * 60)
    if failed:
        print(f"❌ {len(failed)} check(s) vermelho(s): {', '.join(failed)}")
    else:
        print(
            f"✅ todos os checks passaram ({len(results)} rodados, {len(skipped)} skip)"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validação read-only de um deploy em execução (pos-deploy)."
    )
    parser.add_argument(
        "--base-url", required=True, help="ex.: https://app.onrender.com"
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="segundos por request"
    )
    parser.add_argument(
        "--access-token",
        # `argv` é visível em `ps` e fica no histórico do shell; o env não.
        default=os.environ.get("VERIFY_ACCESS_TOKEN", ""),
        help="JWT para validar o caminho autenticado (ou VERIFY_ACCESS_TOKEN)",
    )
    parser.add_argument(
        "--expect-tenant", default="", help="tenant esperado do token cunhado"
    )
    parser.add_argument(
        "--app-js", default="", help="caminho do static/app.js local (paridade)"
    )
    parser.add_argument(
        "--agent-py", default="", help="caminho do agent/agent.py local (paridade)"
    )
    parser.add_argument(
        "--app-py", default="", help="app.py do checkout (fonte do schema esperado)"
    )
    parser.add_argument(
        "--schema-wait",
        type=float,
        default=45.0,
        help="segundos de tolerância para as chaves que só o primeiro poll escreve",
    )
    parser.add_argument(
        "--skip-bundle", action="store_true", help="pula a paridade de bundle"
    )
    parser.add_argument(
        "--skip-agent-script", action="store_true", help="pula a paridade do agent.py"
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="saída de máquina"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        expected = global_snapshot_keys(
            pathlib.Path(args.app_py) if args.app_py else None
        )
    except (OSError, SyntaxError, RuntimeError) as exc:
        print(f"❌ não consegui derivar o schema esperado: {exc}", file=sys.stderr)
        return 2

    results = run_checks(
        args.base_url,
        timeout=args.timeout,
        expected_keys=expected,
        app_js=pathlib.Path(args.app_js) if args.app_js else None,
        agent_py=pathlib.Path(args.agent_py) if args.agent_py else None,
        skip_bundle=args.skip_bundle,
        skip_agent_script=args.skip_agent_script,
        access_token=args.access_token,
        expect_tenant=args.expect_tenant,
        schema_wait=args.schema_wait,
    )

    durable = durable_failures(results)
    if args.as_json:
        print(
            json.dumps(
                {
                    "base_url": args.base_url,
                    "checks": [
                        {"name": name, "ok": ok, "detail": detail}
                        for name, ok, detail in results
                    ],
                    "failed": [n for n, ok, _ in results if ok is False],
                    "durable_failed": durable,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_report(results, args.base_url)
        if durable:
            print(
                "\n⛔ falha DURÁVEL (exit 3) — repetir não conserta: "
                + ", ".join(durable)
            )

    if durable:
        return 3
    return 1 if any(ok is False for _, ok, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
