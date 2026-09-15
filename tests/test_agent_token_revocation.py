"""test_agent_token_revocation.py — revogação de tokens de agente por tenant (#582).

O que este arquivo prova, e por quê:

1. **Revogar funciona de verdade** — o MESMO token que entrou deixa de entrar, e
   um token novo volta a entrar. Sem isso a feature é decorativa.
2. **É por tenant** — revogar o de A não derruba o agente de B.
3. **Fail-closed no legado** — um token emitido ANTES desta feature (sem o
   claim) morre no primeiro incremento. Não dá para "escapar" da revogação por
   ter sido cunhado antes.
4. **O epoch é durável e não depende de enumerar tokens.** A blacklist de
   `services/auth.revoke_token` exige a string do token, é FIFO-podada em
   memória (10 000 / guarda 5 000) e a persistência (`REVOKED_TOKENS_DB=1`,
   agora ligada no render.yaml pela Issue #586) só retém **7d1h** — para um
   token de 365 dias isso significa: a revogação some antes do token. É por
   isso que os agentes usam epoch, e não a blacklist.
5. **Só `admin` revoga** (Issue #586) — `member` cunha, `member` não revoga — e
   uma recusa tem de ter ZERO efeito (ver `TestRevokeRequiresAdmin`).
6. **A falha de leitura é best-effort com valor conhecido, mas nunca inventa
   sucesso** — o que NUNCA é best-effort é a resposta ao usuário: uma revogação
   que não persistiu devolve 500, não 200.

Hermeticidade: cada teste usa um **tenant próprio**. O DB do pytest é único para
a sessão inteira (tests/conftest.py), então incrementar o epoch de um tenant
compartilhado contaminaria os outros testes — a mesma armadilha que o memo de
5s teria.
"""

import sqlite3
import uuid
from unittest.mock import patch

import pytest

from app import app as _app
from axe_fleet.registry import DeviceRegistry
from services import agent_tokens
from services.auth import create_token, verify_token


def _tid(prefix="revoke"):
    """Tenant exclusivo por teste — nunca colide com 'acme'/'default'."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def client(monkeypatch):
    _app.config["TESTING"] = True
    saved = _app.config.get("JWT_SECRET_KEY")
    _app.config["JWT_SECRET_KEY"] = "agent-test-secret-123-0123456789abcdef"
    monkeypatch.setenv("SECRET_KEY", "agent-test-secret-123-0123456789abcdef")
    c = _app.test_client()
    yield c
    agent_tokens.invalidate_memo()
    if saved is not None:
        _app.config["JWT_SECRET_KEY"] = saved
    else:
        _app.config.pop("JWT_SECRET_KEY", None)


@pytest.fixture
def registry(tmp_path):
    db_path = str(tmp_path / "agent.sqlite")

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    r = DeviceRegistry(get_db)
    r.ensure_tables()
    return r


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _user_token(tenant):
    """Usuário logado do tenant (role admin → member+)."""
    return create_token(subject=tenant, extra_claims={"role": "admin"})


def _use_agent(client, token, ip="192.168.1.50"):
    """Exercita o token como o agente real: um POST em rota de agente."""
    return client.post(
        "/api/agent/register", headers=_headers(token), json={"devices": [{"ip": ip}]}
    )


# ══════════════════════════════════════════════════════════════════════
#  O caminho completo: cunhar → usar → revogar → parar de funcionar
# ══════════════════════════════════════════════════════════════════════


class TestRevocationEndToEnd:
    def test_revoking_kills_the_old_token_and_a_new_one_works(self, client, registry):
        tenant = _tid()
        user = _user_token(tenant)

        mint = client.post("/api/agent/token", headers=_headers(user))
        assert mint.status_code == 200
        first = mint.get_json()["token"]

        with patch("axe_fleet.routes._registry", registry):
            assert _use_agent(client, first).status_code == 201

            revoked = client.post("/api/agent/tokens/revoke", headers=_headers(user))
            assert revoked.status_code == 200
            data = revoked.get_json()
            assert data["success"] is True
            assert data["active_epoch"] == data["revoked_epoch"] + 1

            # O MESMO token agora é recusado — e com motivo acionável.
            refused = _use_agent(client, first, ip="192.168.1.51")
            assert refused.status_code == 401
            body = refused.get_json()
            assert body["code"] == "AGENT_TOKEN_REVOKED"
            assert "POST /api/agent/token" in body["hint"]

            # Um token novo entra normalmente: revogar não é um lock-out.
            second = client.post("/api/agent/token", headers=_headers(user)).get_json()[
                "token"
            ]
            assert second != first
            assert _use_agent(client, second, ip="192.168.1.52").status_code == 201

    def test_the_check_is_what_stops_the_token(self, client, registry):
        """Prova em suíte de que o check é load-bearing (mutação local).

        Com `is_revoked` forçado a False, o token revogado volta a entrar — é
        exatamente o mutante que a suíte tem de matar, então ele é exercitado
        aqui em vez de ficar só na medição manual.
        """
        tenant = _tid()
        user = _user_token(tenant)
        token = client.post("/api/agent/token", headers=_headers(user)).get_json()[
            "token"
        ]

        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/tokens/revoke", headers=_headers(user))
            assert _use_agent(client, token).status_code == 401

            with patch("services.agent_tokens.is_revoked", return_value=False):
                assert _use_agent(client, token, ip="192.168.1.60").status_code == 201

    def test_a_pre_feature_token_dies_on_the_first_revocation(self, client, registry):
        """Fail-closed: token sem o claim conta como epoch 0 e é revogado junto."""
        tenant = _tid()
        legacy = create_token(
            subject=tenant,
            ttl=365 * 86400,
            extra_claims={"agent": True, "role": "agent"},  # sem agent_epoch
        )
        assert verify_token(legacy)["sub"] == tenant

        with patch("axe_fleet.routes._registry", registry):
            assert _use_agent(client, legacy).status_code == 201
            client.post(
                "/api/agent/tokens/revoke", headers=_headers(_user_token(tenant))
            )
            refused = _use_agent(client, legacy, ip="192.168.1.55")
            assert refused.status_code == 401
            assert refused.get_json()["code"] == "AGENT_TOKEN_REVOKED"

    def test_revocation_does_not_touch_another_tenant(self, client, registry):
        tenant_a, tenant_b = _tid("a"), _tid("b")
        user_a, user_b = _user_token(tenant_a), _user_token(tenant_b)
        token_b = client.post("/api/agent/token", headers=_headers(user_b)).get_json()[
            "token"
        ]

        with patch("axe_fleet.routes._registry", registry):
            client.post("/api/agent/tokens/revoke", headers=_headers(user_a))
            # O agente de B segue trabalhando: revogar é escopado por tenant.
            assert _use_agent(client, token_b).status_code == 201

    def test_revoked_agent_token_does_not_authenticate_anything_else(
        self, client, registry
    ):
        """O token revogado não vira um passe livre em outra rota de agente."""
        tenant = _tid()
        user = _user_token(tenant)
        token = client.post("/api/agent/token", headers=_headers(user)).get_json()[
            "token"
        ]
        client.post("/api/agent/tokens/revoke", headers=_headers(user))

        for path, payload in (
            ("/api/agent/telemetry", {"devices": []}),
            ("/api/agent/commands/pull", {}),
        ):
            resp = client.post(path, headers=_headers(token), json=payload)
            assert resp.status_code == 401, path


# ══════════════════════════════════════════════════════════════════════
#  Quem pode revogar
# ══════════════════════════════════════════════════════════════════════


class TestWhoCanRevoke:
    CLOUD_FLAGS = ("RENDER", "RENDER_SERVICE_ID", "RENDER_INSTANCE_ID", "CLOUD_MODE")

    def test_anonymous_revoke_is_refused_on_cloud(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)

        resp = client.post("/api/agent/tokens/revoke")

        assert resp.status_code == 403
        assert "token" not in resp.get_json()

    def test_a_logged_in_user_revokes_on_cloud(self, client, monkeypatch):
        monkeypatch.setenv("RENDER", "true")
        tenant = _tid()
        resp = client.post(
            "/api/agent/tokens/revoke", headers=_headers(_user_token(tenant))
        )
        assert resp.status_code == 200
        assert resp.get_json()["tenant_id"] == tenant

    def test_open_self_host_mode_still_revokes(self, client, monkeypatch):
        """O operador do self-host é o dono — não pode ser trancado fora."""
        for flag in self.CLOUD_FLAGS:
            monkeypatch.delenv(flag, raising=False)
        resp = client.post("/api/agent/tokens/revoke")
        assert resp.status_code == 200
        assert resp.get_json()["tenant_id"] == "default"

    def test_the_audit_trail_records_both_epochs(self, client, monkeypatch):
        """Uma revogação sem rastro não é auditável — os dois epochs vão pro log."""
        calls = []
        monkeypatch.setattr(
            "axe_fleet.routes._log_audit",
            lambda tid, action, details=None: calls.append(
                (tid, action, details or {})
            ),
        )
        tenant = _tid("audit")
        client.post("/api/agent/token", headers=_headers(_user_token(tenant)))
        client.post("/api/agent/tokens/revoke", headers=_headers(_user_token(tenant)))

        by_action = {action: (tid, details) for tid, action, details in calls}
        assert by_action["agent.token_issued"][0] == tenant
        assert by_action["agent.token_issued"][1]["epoch"] == 0
        assert by_action["agent.tokens_revoked"][1] == {
            "from_epoch": 0,
            "to_epoch": 1,
        }


class TestRevokeRequiresAdmin:
    """Issue #586: revogar exige `admin`; cunhar continua `member`.

    A assimetria é o desenho, não um descuido: cunhar só afeta a credencial de
    quem cunha, revogar derruba a frota INTEIRA do tenant de uma vez e não tem
    desfazer. Um teste que só olhasse o 200 do admin não distinguiria isso de
    "todo mundo pode" — por isso os casos negativos são a maioria aqui.

    Nota medida: hoje `member` NÃO é alcançável por HTTP nenhum — o signup
    grava `role='admin'` (`provision_tenant_with_admin`), o login por API key
    também, e `create_user(role="member")` não tem chamador. Estes testes forjam
    o JWT do membro justamente porque nenhuma rota o produz: a restrição é
    defensiva, e é o teste que a mantém viva se a hierarquia mudar.
    """

    def _rbac_on(self, monkeypatch):
        """Auth configurada é o ÚNICO modo em que o `role_required` morde.

        Sem `API_KEY`/`TENANT_API_KEYS` o modo aberto do self-host faz dele um
        no-op — e aí a recusa de um anônimo vem da identidade
        (`AGENT_TOKEN_NEEDS_IDENTITY`), não do papel.
        """
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.setenv("API_KEY", "op-key-que-liga-o-rbac")

    def _as(self, tenant, role):
        return _headers(create_token(subject=tenant, extra_claims={"role": role}))

    def test_member_cannot_revoke(self, client, monkeypatch):
        self._rbac_on(monkeypatch)
        resp = client.post(
            "/api/agent/tokens/revoke", headers=self._as(_tid("mbr"), "member")
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["required_role"] == "admin"
        assert body["role"] == "member"

    def test_viewer_cannot_revoke(self, client, monkeypatch):
        self._rbac_on(monkeypatch)
        resp = client.post(
            "/api/agent/tokens/revoke", headers=self._as(_tid("viw"), "viewer")
        )
        assert resp.status_code == 403

    def test_admin_can_revoke(self, client, monkeypatch):
        self._rbac_on(monkeypatch)
        tenant = _tid("adm")
        resp = client.post("/api/agent/tokens/revoke", headers=self._as(tenant, "admin"))
        assert resp.status_code == 200
        assert resp.get_json()["tenant_id"] == tenant

    def test_member_can_still_mint(self, client, monkeypatch):
        """A assimetria, escrita como teste: `member` cunha, `member` não revoga.

        Se um dia alguém "uniformizar" os dois decorators, este teste cai.
        """
        self._rbac_on(monkeypatch)
        mint = client.post("/api/agent/token", headers=self._as(_tid("mnt"), "member"))
        assert mint.status_code == 200
        assert mint.get_json()["token"]
        revoke = client.post(
            "/api/agent/tokens/revoke", headers=self._as(_tid("mnt2"), "member")
        )
        assert revoke.status_code == 403

    def test_a_refused_revoke_revokes_nothing(self, client, registry, monkeypatch):
        """A parte que importa: recusa tem de significar ZERO efeito.

        Um 403 que ainda assim incrementasse o epoch seria pior que um 200 — o
        usuário veria "negado" enquanto a frota dele caía.
        """
        self._rbac_on(monkeypatch)
        tenant = _tid("nop")
        minted = client.post(
            "/api/agent/token", headers=self._as(tenant, "admin")
        ).get_json()["token"]
        before = agent_tokens.get_epoch(tenant)

        resp = client.post("/api/agent/tokens/revoke", headers=self._as(tenant, "member"))
        assert resp.status_code == 403

        agent_tokens.invalidate_memo(tenant)
        assert agent_tokens.get_epoch(tenant) == before, "o 403 não pode ter revogado"
        with patch("axe_fleet.routes._registry", registry):
            assert _use_agent(client, minted).status_code == 201

    def test_the_anonymous_refusal_names_the_identity_gap(self, client, monkeypatch):
        """Sem auth configurada a recusa é a do #578 — o que o gate de produção cobra."""
        monkeypatch.setenv("RENDER", "true")
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("TENANT_API_KEYS", raising=False)

        resp = client.post("/api/agent/tokens/revoke")

        assert resp.status_code == 403
        assert resp.get_json()["code"] == "AGENT_TOKEN_NEEDS_IDENTITY"
        assert "active_epoch" not in resp.get_json()


# ══════════════════════════════════════════════════════════════════════
#  O store do epoch (services/agent_tokens.py)
# ══════════════════════════════════════════════════════════════════════


class TestEpochStore:
    def test_unknown_tenant_is_epoch_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "e.sqlite"))
        agent_tokens.invalidate_memo()
        assert agent_tokens.get_epoch(_tid()) == 0

    def test_bump_increments_and_persists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "e.sqlite"))
        agent_tokens.invalidate_memo()
        tenant = _tid()

        assert agent_tokens.bump_epoch(tenant) == 1
        assert agent_tokens.bump_epoch(tenant) == 2
        assert agent_tokens.get_epoch(tenant) == 2

        agent_tokens.invalidate_memo()  # como um segundo processo veria
        assert agent_tokens.get_epoch(tenant) == 2

    def test_the_memo_never_serves_a_stale_epoch_after_a_bump(
        self, tmp_path, monkeypatch
    ):
        """O bug que o cache de settings teria: um worker com epoch velho."""
        monkeypatch.setenv("DB_PATH", str(tmp_path / "e.sqlite"))
        agent_tokens.invalidate_memo()
        tenant = _tid()

        assert agent_tokens.get_epoch(tenant) == 0  # aquece o memo
        agent_tokens.bump_epoch(tenant)
        assert agent_tokens.get_epoch(tenant) == 1  # memo NÃO pode servir 0

    def test_epoch_of_is_zero_for_anything_unusable(self):
        assert agent_tokens.epoch_of(None) == 0
        assert agent_tokens.epoch_of({}) == 0
        assert agent_tokens.epoch_of({"agent_epoch": None}) == 0
        assert agent_tokens.epoch_of({"agent_epoch": "não é número"}) == 0
        assert agent_tokens.epoch_of({"agent_epoch": "3"}) == 3

    def test_a_db_failure_falls_back_to_the_last_known_value(
        self, tmp_path, monkeypatch
    ):
        """Best-effort, como services/auth: leitura falha NÃO derruba a frota."""
        monkeypatch.setenv("DB_PATH", str(tmp_path / "e.sqlite"))
        agent_tokens.invalidate_memo()
        tenant = _tid()
        agent_tokens.bump_epoch(tenant)
        assert agent_tokens.get_epoch(tenant) == 1  # memo quente

        def boom():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(agent_tokens, "_connect", boom)
        agent_tokens._memo[tenant] = (0.0, 1)  # memo expirado, valor conhecido
        assert agent_tokens.get_epoch(tenant) == 1
        # E o token revogado continua sendo recusado com o valor conhecido.
        assert agent_tokens.is_revoked({"sub": tenant, "agent_epoch": 0}) is True

    def test_a_cold_db_failure_does_not_falsely_revoke(self, tmp_path, monkeypatch):
        """Sem valor conhecido libera (fail-open) — e é honesto sobre isso."""
        monkeypatch.setenv("DB_PATH", str(tmp_path / "e.sqlite"))
        agent_tokens.invalidate_memo()
        tenant = _tid()

        def boom():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(agent_tokens, "_connect", boom)
        assert agent_tokens.get_epoch(tenant) is None
        assert agent_tokens.is_revoked({"sub": tenant, "agent_epoch": 0}) is False

    def test_bump_raises_instead_of_pretending(self, tmp_path, monkeypatch):
        """Uma revogação que não persistiu não pode parecer sucesso."""
        monkeypatch.setenv("DB_PATH", str(tmp_path / "e.sqlite"))
        agent_tokens.invalidate_memo()

        def boom():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(agent_tokens, "_connect", boom)
        with pytest.raises(sqlite3.OperationalError):
            agent_tokens.bump_epoch(_tid())


class TestRevokeRouteNeverLies:
    def test_a_failed_persist_is_a_500(self, client, monkeypatch):
        def boom(tenant_id):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("services.agent_tokens.bump_epoch", boom)
        resp = client.post("/api/agent/tokens/revoke")
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_the_minted_token_carries_the_current_epoch(self, client):
        tenant = _tid()
        agent_tokens.bump_epoch(tenant)  # 1
        data = client.post(
            "/api/agent/token", headers=_headers(_user_token(tenant))
        ).get_json()
        assert data["agent_epoch"] == 1
        assert verify_token(data["token"])[agent_tokens.EPOCH_CLAIM] == 1
