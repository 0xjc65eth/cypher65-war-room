"""test_verify_production.py — self-test do validador pós-deploy.

Roda de duas formas (padrão dos guards do repo):
    python3 tests/test_verify_production.py   # standalone (exit code)
    pytest tests/test_verify_production.py    # suíte completa

O que este self-test prova:

1. O validador PASSA contra um servidor que responde o esperado — e ele fala
   HTTP de verdade (um `http.server` em porta efêmera, não um mock de função).
2. Cada check FALHA quando a resposta correspondente está errada (uma mutação
   por check). Um validador que só sabe dizer "verde" não é um validador: foi
   exatamente assim que o gate do Render passou com o `#575` quebrado em
   produção (o marcador dele era um texto de um commit ANTERIOR — stale).
3. O schema esperado é derivado do `app.py` do checkout, e não de uma lista no
   CI: por isso o marcador é específico do commit que está sendo deployado.
4. O job `diagnose-render` usa este validador — e não voltou a depender de um
   marcador hardcoded.
5. A tolerância ao primeiro poll não é anistia: sem convergir, o check fica
   vermelho (senão a espera viraria um jeito silencioso de passar).
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "verify_production", ROOT / "scripts" / "verify_production.py"
)
VP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VP)

WORKFLOW = ROOT / ".github" / "workflows" / "execution-pipeline.yml"
APP_JS_BYTES = b"/* bundle de teste */\n"
AGENT_PY_BYTES = b"#!/usr/bin/env python3\n# agente de teste\n"


class Stub:
    """Servidor HTTP real com respostas canned.

    Porta efêmera (`:0`) e desligado no `close()` — nada de porta fixa que
    colida com o Flask do e2e (Issue #437).
    """

    def __init__(self, routes=None):
        self.routes = dict(DEFAULT_ROUTES)
        if routes:
            self.routes.update(routes)
        self.server = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silêncio no pytest
                pass

            def _respond(self, method):
                key = (method, self.path.split("?")[0])
                status, body = outer.routes.get(key, (404, {"error": "not found"}))
                if callable(body):  # resposta que muda a cada chamada (convergência)
                    body = body()
                if isinstance(body, (dict, list)):
                    raw = json.dumps(body).encode()
                    ctype = "application/json"
                elif isinstance(body, bytes):
                    raw, ctype = body, "application/javascript"
                else:
                    raw, ctype = str(body).encode(), "text/plain"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._respond("GET")

            def do_POST(self):
                self._respond("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _expected_keys():
    return VP.global_snapshot_keys()


def _good_snapshot():
    """Payload conforme: TODAS as chaves que os produtores locais escrevem.

    Derivar do próprio código é o ponto: se alguém adicionar uma chave ao poll
    e esquecer o outro produtor, este stub deixa de satisfazer o check — que é
    exatamente o comportamento desejado em produção (#576).
    """
    snap = {k: None for k in _expected_keys()}
    snap["ts"] = 1
    return snap


def _healthz(cloud=True, **flags):
    """Corpo do healthz com o bloco `persistence` — o marcador do commit (#586).

    O bloco é o que permite ao validador distinguir "a instância antiga ainda
    está servindo" (retry resolve) de "o código novo está no ar e um check
    durável está vermelho" (retry não resolve). Sem ele o marcador reprova, o
    que é o comportamento correto: um healthz sem `persistence` é código de um
    commit anterior.
    """
    base = {"remote_backup": True, "sentry": True, "revoked_tokens_db": True}
    base.update({k: v for k, v in flags.items() if k in base})
    return {"ok": True, "cloud": cloud, "persistence": base}


# Self-host: o código é este, então o bloco existe (a flag é que pode estar off).
SELF_HOST_HEALTHZ = _healthz(
    cloud=False, remote_backup=False, sentry=False, revoked_tokens_db=False
)

DEFAULT_ROUTES = {
    ("GET", "/api/healthz"): (200, _healthz()),
    ("GET", "/api/snapshot"): (200, _good_snapshot()),
    ("GET", "/static/app.js"): (200, APP_JS_BYTES),
    ("GET", "/agent/agent.py"): (200, AGENT_PY_BYTES),
    ("POST", "/api/network/scan"): (400, {"success": False, "is_cloud": True}),
    ("POST", "/api/axe-fleet/scan"): (400, {"success": False, "is_cloud": True}),
    ("POST", "/api/agent/token"): (403, {"code": "AGENT_TOKEN_NEEDS_IDENTITY"}),
    ("POST", "/api/agent/tokens/revoke"): (
        403,
        {"code": "AGENT_TOKEN_NEEDS_IDENTITY"},
    ),
    ("POST", "/api/agent/register"): (401, {"error": "agent token required"}),
}


class _Fixture:
    """Stub + os dois arquivos locais usados na paridade."""

    def __init__(self, routes=None):
        self.stub = Stub(routes)
        self.tmp = tempfile.TemporaryDirectory()
        self.app_js = pathlib.Path(self.tmp.name) / "app.js"
        self.agent_py = pathlib.Path(self.tmp.name) / "agent.py"
        self.app_js.write_bytes(APP_JS_BYTES)
        self.agent_py.write_bytes(AGENT_PY_BYTES)

    def run(self, **kwargs):
        # `schema_wait=0` por padrão: um teste quer determinismo e velocidade, não
        # os 45s de tolerância do runner de produção (a janela de convergência
        # tem teste próprio — `test_snapshot_converges_after_the_first_poll`).
        kwargs.setdefault("schema_wait", 0.0)
        return VP.run_checks(
            self.stub.base_url,
            app_js=self.app_js,
            agent_py=self.agent_py,
            timeout=5.0,
            **kwargs,
        )

    def main(self):
        return VP.main(
            [
                "--base-url",
                self.stub.base_url,
                "--app-js",
                str(self.app_js),
                "--agent-py",
                str(self.agent_py),
                "--timeout",
                "5",
                "--schema-wait",
                "0",
            ]
        )

    def close(self):
        self.stub.close()
        self.tmp.cleanup()


def _with_fixture(routes=None):
    fixture = _Fixture(routes)
    try:
        return fixture
    except Exception:
        fixture.close()
        raise


def _failed(results):
    return [name for name, ok, _ in results if ok is False]


# ── 1. Caminho feliz ──────────────────────────────────────────────────────


def test_all_checks_pass_on_a_healthy_deploy():
    fixture = _with_fixture()
    try:
        results = fixture.run()
        assert _failed(results) == [], f"checks vermelhos: {_failed(results)}"
        assert fixture.main() == 0
    finally:
        fixture.close()


def test_the_authenticated_path_can_be_validated_with_a_token():
    fixture = _with_fixture(
        {
            ("POST", "/api/agent/token"): (
                200,
                {
                    "success": True,
                    "token": "jwt",
                    "tenant_id": "default",
                    "expires_in": 31536000,
                },
            )
        }
    )
    try:
        results = fixture.run(access_token="qualquer-jwt", expect_tenant="default")
        by_name = {name: (ok, detail) for name, ok, detail in results}
        assert by_name["agent token com identidade"][0] is True
        assert (
            "jwt" not in by_name["agent token com identidade"][1]
        ), "o token não pode aparecer na saída (log de CI não é lugar de credencial)"
        # O check do anônimo continua rodando e continua exigindo 403.
        assert by_name["agent token anônimo"][0] is False or "AGENT_TOKEN" in str(
            by_name["agent token anônimo"][1]
        )
    finally:
        fixture.close()


def test_token_check_requires_a_token_in_the_body():
    fixture = _with_fixture(
        {("POST", "/api/agent/token"): (200, {"success": True, "tenant_id": "default"})}
    )
    try:
        results = fixture.run(access_token="jwt")
        assert "agent token com identidade" in _failed(results)
    finally:
        fixture.close()


def test_expected_tenant_is_enforced():
    fixture = _with_fixture(
        {("POST", "/api/agent/token"): (200, {"token": "jwt", "tenant_id": "outro"})}
    )
    try:
        results = fixture.run(access_token="jwt", expect_tenant="default")
        assert "agent token com identidade" in _failed(results)
    finally:
        fixture.close()


# ── 2. Cada check FALHA na mutação correspondente ─────────────────────────


def test_healthz_down_fails():
    fixture = _with_fixture({("GET", "/api/healthz"): (500, {"ok": False})})
    try:
        assert "healthz" in _failed(fixture.run())
    finally:
        fixture.close()


def test_missing_snapshot_key_fails_and_names_it():
    """O bug do #576: o payload servido não traz o que o produtor escreve."""
    snap = _good_snapshot()
    for key in ("pool_detection", "pool_worker"):
        snap.pop(key, None)
    fixture = _with_fixture({("GET", "/api/snapshot"): (200, snap)})
    try:
        results = fixture.run()
        failed = {name: detail for name, ok, detail in results if ok is False}
        assert "snapshot schema" in failed
        assert "pool_detection" in failed["snapshot schema"]
        assert fixture.main() == 1
    finally:
        fixture.close()


def test_bundle_drift_is_detected():
    fixture = _with_fixture({("GET", "/static/app.js"): (200, b"/* bundle velho */")})
    try:
        assert "bundle parity" in _failed(fixture.run())
    finally:
        fixture.close()


def test_agent_script_drift_is_detected():
    fixture = _with_fixture({("GET", "/agent/agent.py"): (200, b"# agent velho\n")})
    try:
        assert "agent.py parity" in _failed(fixture.run())
    finally:
        fixture.close()


def test_scan_guard_missing_on_cloud_fails():
    fixture = _with_fixture(
        {("POST", "/api/network/scan"): (200, {"success": True, "devices": []})}
    )
    try:
        assert "guard /api/network/scan" in _failed(fixture.run())
    finally:
        fixture.close()


def test_scan_guard_without_is_cloud_flag_fails():
    """400 genérico não é a guarda: tem de ser o `is_cloud` do #570."""
    fixture = _with_fixture({("POST", "/api/axe-fleet/scan"): (400, {"error": "nope"})})
    try:
        assert "guard /api/axe-fleet/scan" in _failed(fixture.run())
    finally:
        fixture.close()


def test_anonymous_agent_token_minted_on_cloud_fails():
    """A regressão exata do #578.

    Exit **3**, não 1: o marcador passa (o código novo está no ar) e esta falha
    é de configuração — o loop do CI não deve gastar 8 min repetindo.
    """
    fixture = _with_fixture(
        {
            ("POST", "/api/agent/token"): (
                200,
                {"success": True, "tenant_id": "default", "token": "jwt-de-frota"},
            )
        }
    )
    try:
        results = fixture.run()
        assert "agent token anônimo" in _failed(results)
        assert VP.durable_failures(results) == ["agent token anônimo"]
        assert fixture.main() == 3
    finally:
        fixture.close()


def test_anonymous_revoke_on_cloud_is_refused():
    """O kill switch da frota não pode aceitar um POST anônimo (Issue #586).

    Se aceitar, qualquer estranho invalida todos os tokens de agente do tenant
    com um curl — e nenhum gate olhava esta rota.
    """
    fixture = _with_fixture(
        {
            ("POST", "/api/agent/tokens/revoke"): (
                200,
                {"success": True, "active_epoch": 1, "revoked_epoch": 0},
            )
        }
    )
    try:
        results = fixture.run()
        assert "agent revoke anônimo" in _failed(results)
        # Exit 3: o marcador passa (o código novo está no ar) e esta falha é de
        # configuração. O loop do CI não deve repetir 20× por ela.
        assert fixture.main() == 3
    finally:
        fixture.close()


def test_a_refusal_that_still_revoked_is_a_failure():
    """403 com epoch no corpo: o status diz "negado" e o efeito diz "revogou".

    É o pior caso possível — o usuário acharia que a frota dele está de pé.
    """
    fixture = _with_fixture(
        {
            ("POST", "/api/agent/tokens/revoke"): (
                403,
                {"code": "AGENT_TOKEN_NEEDS_IDENTITY", "active_epoch": 3},
            )
        }
    )
    try:
        assert "agent revoke anônimo" in _failed(fixture.run())
    finally:
        fixture.close()


def test_the_rbac_refusal_shape_is_also_accepted():
    """Com auth configurada quem recusa é o RBAC, com outro corpo.

    As duas formas são legítimas: a identidade (nuvem sem `API_KEY`) e o papel.
    Exigir só uma delas faria o check virar um falso vermelho no dia em que o
    operador ligasse `TENANT_API_KEYS`.
    """
    fixture = _with_fixture(
        {
            ("POST", "/api/agent/tokens/revoke"): (
                403,
                {
                    "error": "permission denied",
                    "required_role": "admin",
                    "role": "anonymous",
                },
            )
        }
    )
    try:
        by_name = {name: ok for name, ok, _ in fixture.run()}
        assert by_name["agent revoke anônimo"] is True
    finally:
        fixture.close()


def test_an_unrecognized_403_is_a_failure():
    """Um 403 que não sabemos explicar não é a recusa que este check promete."""
    fixture = _with_fixture(
        {("POST", "/api/agent/tokens/revoke"): (403, {"error": "nope"})}
    )
    try:
        assert "agent revoke anônimo" in _failed(fixture.run())
    finally:
        fixture.close()


def test_revoked_db_flag_missing_in_the_process_fails():
    """A regressão exata do #586: a flag no blueprint e não no processo.

    Um `render.yaml` verde que o Render não aplicou deixa a produção com a
    blacklist só em memória — invisível de fora, que é o motivo de existir a
    sonda no healthz.
    """
    fixture = _with_fixture(
        {
            ("GET", "/api/healthz"): (
                200,
                {
                    "ok": True,
                    "cloud": True,
                    "persistence": {
                        "remote_backup": True,
                        "revoked_tokens_db": False,
                    },
                },
            )
        }
    )
    try:
        failed = {name: detail for name, ok, detail in fixture.run() if ok is False}
        assert "persistence · revoked_tokens_db" in failed
        assert "render.yaml" in failed["persistence · revoked_tokens_db"]
        assert "persistence · durabilidade" not in failed, "os dois são independentes"
    finally:
        fixture.close()


def test_persistence_without_a_remote_backup_fails():
    """Persistir num disco efêmero e sem gist não é persistir."""
    fixture = _with_fixture(
        {
            ("GET", "/api/healthz"): (
                200,
                {
                    "ok": True,
                    "cloud": True,
                    "persistence": {
                        "remote_backup": False,
                        "revoked_tokens_db": True,
                    },
                },
            )
        }
    )
    try:
        failed = {name: detail for name, ok, detail in fixture.run() if ok is False}
        assert "persistence · durabilidade" in failed
        assert "EFÊMERO" in failed["persistence · durabilidade"]
        assert "persistence · revoked_tokens_db" not in failed, "a flag chegou"
    finally:
        fixture.close()


def test_a_healthz_without_the_persistence_block_fails():
    """Sem o bloco, os dois checks reprovam — nunca um verde silencioso."""
    fixture = _with_fixture(
        {("GET", "/api/healthz"): (200, {"ok": True, "cloud": True})}
    )
    try:
        failed = _failed(fixture.run())
        assert "persistence · revoked_tokens_db" in failed
        assert "persistence · durabilidade" in failed
    finally:
        fixture.close()


def test_self_host_skips_persistence_and_never_touches_revoke():
    """Self-host: skip nos três, e o do revoke pelo motivo que importa.

    Em modo aberto o POST anônimo revoga DE VERDADE. Um validador não pode
    mutar o ambiente que está medindo — então aqui não se faz o request.
    """
    fixture = _with_fixture(
        {
            ("GET", "/api/healthz"): (200, SELF_HOST_HEALTHZ),
            ("POST", "/api/agent/token"): (
                200,
                {"success": True, "tenant_id": "default"},
            ),
        }
    )
    try:
        by_name = {name: (ok, detail) for name, ok, detail in fixture.run()}
        assert by_name["deploy marker"][0] is True
        assert by_name["agent revoke anônimo"][0] is None
        assert "revoga de verdade" in by_name["agent revoke anônimo"][1]
        assert by_name["persistence · revoked_tokens_db"][0] is None
        assert by_name["persistence · durabilidade"][0] is None
        assert _failed(fixture.run()) == []
    finally:
        fixture.close()


def test_snapshot_converges_after_the_first_poll():
    """App recém-subido: o boot já serve as chaves dele, o primeiro poll não rodou.

    O snapshot tem DOIS tempos. Exigir as chaves de poll de imediato daria
    vermelho numa janela legítima de ~15s — e um verificador que dá falso
    vermelho é desligado, o que é pior do que não existir. Aqui a espera é
    curta de propósito; em produção ela é `--schema-wait` (45s).
    """
    boot, poll_keys = VP.snapshot_keys_by_producer()
    assert poll_keys, "o teste perde o sentido se não houver chaves de poll"
    calls = {"n": 0}

    def snapshot_body():
        calls["n"] += 1
        snap = _good_snapshot()
        if calls["n"] == 1:  # ainda não pollou
            for key in poll_keys:
                snap.pop(key, None)
        return snap

    fixture = _with_fixture({("GET", "/api/snapshot"): (200, snapshot_body)})
    try:
        results = fixture.run(schema_wait=3.0)
        assert results and calls["n"] >= 2, "o runner tem de repetir até convergir"
        assert "snapshot schema" not in _failed(results), _failed(results)
    finally:
        fixture.close()


def test_snapshot_never_converging_still_fails():
    """A tolerância não pode virar anistia: sem convergir, o check fica vermelho."""
    _, poll_keys = VP.snapshot_keys_by_producer()

    def snapshot_body():
        snap = _good_snapshot()
        for key in poll_keys:
            snap.pop(key, None)
        return snap

    fixture = _with_fixture({("GET", "/api/snapshot"): (200, snapshot_body)})
    try:
        assert "snapshot schema" in _failed(fixture.run(schema_wait=1.0))
    finally:
        fixture.close()


def test_audit_endpoint_not_found_is_detected():
    fixture = _with_fixture({("GET", "/api/snapshot"): (404, {"error": "not found"})})
    try:
        assert "snapshot schema" in _failed(fixture.run())
    finally:
        fixture.close()


# ── 3. Self-host: o modo muda a expectativa, não o rigor ──────────────────


def test_self_host_skips_the_lan_scans_and_expects_open_mode():
    fixture = _with_fixture(
        {
            ("GET", "/api/healthz"): (200, SELF_HOST_HEALTHZ),
            ("POST", "/api/agent/token"): (
                200,
                {"success": True, "tenant_id": "default"},
            ),
        }
    )
    try:
        by_name = {name: (ok, detail) for name, ok, detail in fixture.run()}
        # Não disparo scan de LAN de ninguém: skip com motivo, nunca verde mudo.
        assert by_name["guard /api/network/scan"][0] is None
        assert "self-host" in by_name["guard /api/network/scan"][1]
        assert by_name["guard /api/axe-fleet/scan"][0] is None
        # Modo aberto do self-host é o comportamento esperado.
        assert by_name["agent token anônimo"][0] is True
        assert _failed(fixture.run()) == []
    finally:
        fixture.close()


def test_self_host_anonymous_mint_refused_is_a_failure():
    """Se o self-host parar de emitir, o operador local ficou trancado fora."""
    fixture = _with_fixture(
        {("GET", "/api/healthz"): (200, SELF_HOST_HEALTHZ)}
    )
    try:
        by_name = {name: ok for name, ok, _ in fixture.run()}
        assert by_name["agent token anônimo"] is False
    finally:
        fixture.close()


def test_mode_is_unknown_when_healthz_is_down():
    fixture = _with_fixture({("GET", "/api/healthz"): (503, {"ok": False})})
    try:
        by_name = {name: ok for name, ok, _ in fixture.run()}
        assert by_name["guard /api/network/scan"] is None  # indefinido ≠ verde
        assert by_name["agent token anônimo"] is None
        assert by_name["agent revoke anônimo"] is None
        assert by_name["persistence · revoked_tokens_db"] is None
        assert by_name["persistence · durabilidade"] is None
    finally:
        fixture.close()


# ── 3b. Exit 3: a falha que o retry NÃO conserta (Issue #586) ────────────
#
# O loop do `diagnose-render` repete 20× (~8 min) qualquer vermelho. Isso faz
# sentido enquanto o deploy não chegou — e é desperdício puro quando o processo
# live JÁ é este commit e o que falta é uma configuração. O marcador distingue
# os dois casos, e é o que dá ao gate o direito de parar cedo.


def test_the_deploy_marker_requires_the_new_healthz_block():
    """Sem o bloco `persistence`, quem responde é código anterior a este commit.

    É o `persistence` que prova a identidade do commit — a mesma lição do #576:
    um marcador que não muda com o commit não prova nada.
    """
    fixture = _with_fixture(
        {("GET", "/api/healthz"): (200, {"ok": True, "cloud": True})}
    )
    try:
        by_name = {name: (ok, detail) for name, ok, detail in fixture.run()}
        assert by_name["deploy marker"][0] is False
        assert "sem o bloco" in by_name["deploy marker"][1]
        # Sem marcador nada é declarado durável: o loop TEM de tentar de novo,
        # porque pode ser só a instância antiga servindo durante o deploy.
        assert fixture.main() == 1
    finally:
        fixture.close()


def test_the_deploy_marker_rejects_a_block_without_the_new_key():
    """O caso do deploy pela metade: o bloco existe e a chave nova não.

    É um healthz REAL de um commit anterior a este — e o marcador tem de
    dizer exatamente isso ("processo ANTERIOR"), não confundir com "sem bloco".
    """
    fixture = _with_fixture(
        {
            ("GET", "/api/healthz"): (
                200,
                {
                    "ok": True,
                    "cloud": True,
                    "persistence": {"remote_backup": True, "sentry": True},
                },
            )
        }
    )
    try:
        by_name = {name: (ok, detail) for name, ok, detail in fixture.run()}
        assert by_name["deploy marker"][0] is False
        assert "ANTERIOR" in by_name["deploy marker"][1]
    finally:
        fixture.close()


def test_a_live_commit_with_a_durable_failure_exits_3():
    """Marcador verde + check durável vermelho = parar o loop, não repetir 20×."""
    fixture = _with_fixture(
        {("GET", "/api/healthz"): (200, _healthz(revoked_tokens_db=False))}
    )
    try:
        assert fixture.main() == 3
    finally:
        fixture.close()


def test_a_convergence_failure_still_exits_1():
    """A tolerância do primeiro poll não pode virar exit 3: ela É convergência."""
    _, poll_keys = VP.snapshot_keys_by_producer()

    def snapshot_body():
        snap = _good_snapshot()
        for key in poll_keys:
            snap.pop(key, None)
        return snap

    fixture = _with_fixture({("GET", "/api/snapshot"): (200, snapshot_body)})
    try:
        results = fixture.run(schema_wait=0.0)
        assert "snapshot schema" in _failed(results)
        assert VP.durable_failures(results) == []
        assert fixture.main() == 1
    finally:
        fixture.close()


def test_marker_presence_is_the_code_and_the_value_is_the_config():
    """Dois fatos, dois remédios: presença da chave = código; valor = configuração.

    Confundir os dois daria o conselho errado ao operador — "faça redeploy"
    quando o problema é sincronizar o blueprint, ou o contrário.
    """
    fixture = _with_fixture(
        {("GET", "/api/healthz"): (200, _healthz(revoked_tokens_db=False))}
    )
    try:
        by_name = {name: ok for name, ok, _ in fixture.run()}
        assert by_name["deploy marker"] is True, "o código É este commit"
        assert by_name["persistence · revoked_tokens_db"] is False, "a flag não chegou"
    finally:
        fixture.close()


# ── 4. O contrato vem do checkout, não do CI ─────────────────────────────


def test_access_token_can_come_from_the_environment():
    """O env é o caminho sem vazar: `argv` aparece em `ps` e no histórico do shell."""
    base = ["--base-url", "http://exemplo.invalido"]
    assert VP.build_parser().parse_args(base).access_token == ""
    os.environ["VERIFY_ACCESS_TOKEN"] = "jwt-do-ambiente"
    try:
        assert VP.build_parser().parse_args(base).access_token == "jwt-do-ambiente"
        # A flag explícita continua ganhando do env.
        assert (
            VP.build_parser()
            .parse_args(base + ["--access-token", "jwt-da-flag"])
            .access_token
            == "jwt-da-flag"
        )
    finally:
        os.environ.pop("VERIFY_ACCESS_TOKEN", None)
    assert VP.build_parser().parse_args(base).access_token == ""


def test_expected_keys_come_from_the_global_snapshot_producers():
    keys = VP.global_snapshot_keys()
    # As duas chaves que o #576 perdeu no payload servido.
    assert {"pool_detection", "pool_worker"} <= keys
    # E as que identificam o dict como snapshot global.
    assert {"ts", "btc_address", "pool", "worker", "network"} <= keys


def test_expected_keys_are_a_superset_of_every_producer():
    """Nenhum produtor pode escrever uma chave que o check não exija."""
    import ast

    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    producers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            literal = {
                k.value
                for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if VP._SNAPSHOT_SHAPE <= literal:
                producers.append(literal)
    assert len(producers) >= 3, "esperado default de módulo + reset + _do_poll"
    expected = VP.global_snapshot_keys()
    for literal in producers:
        assert literal <= expected


def test_json_output_is_machine_readable():
    fixture = _with_fixture()
    try:
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = VP.main(
                [
                    "--base-url",
                    fixture.stub.base_url,
                    "--json",
                    "--app-js",
                    str(fixture.app_js),
                    "--agent-py",
                    str(fixture.agent_py),
                    "--timeout",
                    "5",
                ]
            )
        payload = json.loads(buf.getvalue())
        assert code == 0
        assert payload["failed"] == []
        assert payload["durable_failed"] == []
        assert any(c["name"] == "snapshot schema" for c in payload["checks"])
        assert any(c["name"] == "deploy marker" for c in payload["checks"])
    finally:
        fixture.close()


# ── 5. O gate de deploy usa este validador (e não um marcador stale) ─────


def test_diagnose_render_runs_the_verifier():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "scripts/verify_production.py" in workflow
    ), "o job diagnose-render tem de validar o contrato do commit deployado"
    assert "--base-url" in workflow


def test_no_step_depends_on_a_stale_marker():
    """O marcador antigo (`IP privado`, do #570) não pode voltar.

    Era ele que fazia o gate passar com o backend de um commit ANTERIOR — e foi
    por isso que o #576 chegou em produção com o gate verde.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "IP privado" not in workflow


def _run_all() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    fails = 0
    print("verify-production self-test")
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as exc:
            print(f"  ❌ {name}: {exc}")
            fails += 1
    print()
    if fails:
        print(f"❌ self-test FAILED — {fails} teste(s) vermelho(s)")
        return 1
    print(f"✅ self-test green — {len(tests)} testes")
    return 0


if __name__ == "__main__":
    sys.exit(_run_all())
