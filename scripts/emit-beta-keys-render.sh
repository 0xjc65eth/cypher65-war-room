#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# CYPHER65 · Beta Trial Key Emitter — Render Shell (Issue #475)
# ═══════════════════════════════════════════════════════════════════════
# Emissão de trial keys PRO sem vazar segredos:
#   • License keys NUNCA vão para stdout (scrollback do Render é um sink
#     de segredos — auditoria enterprise 2026-09-10, Issue #475).
#   • Keys gravadas em arquivo 0600 (mktemp) que se AUTO-DESTRÓI no fim
#     da sessão de shell. Rode `cat "$RESULT_FILE"` durante a sessão,
#     distribua por canal seguro e deixe o trap limpar.
#   • curl --fail: 4xx/5xx não são engolidos (antes, HTML de erro virava
#     "ERROR" 10× em silêncio). POST NÃO tem retry — reemitir duplica keys.
#
# Contrato da API (verificado em routes/admin_routes.py::api_admin_issue_license):
#   POST /api/admin/licenses  {"plan":"pro","months":1,"source":...,
#                              "email":...}
#     → 200 {"ok": true, "license_key": "C65-XXXX-..."}
#   • Validade é em MESES ("months", int) — a API não aceita "days".
#   • A resposta NÃO traz expires — a validade é política do servidor.
#   • Não existe GET /api/admin/licenses (a versão antiga deste script
#     terminava com um curl em 405 silencioso).
#   • Gate: localhost real OU header X-API-Key = env API_KEY do operador
#     (Issue #254). No Render Shell o gate por localhost se aplica.
#
# ROTAÇÃO: se rodou a versão antiga (≤ 2026-09), as keys foram impressas
# no scrollback do Render. Revogue-as e emita novas; considere o
# scrollback exposto.
#
# Uso:
#   bash scripts/emit-beta-keys-render.sh                 # 10 keys
#   COUNT=5 bash scripts/emit-beta-keys-render.sh         # custom
#   ADMIN_API_KEY=... bash scripts/emit-beta-keys-render.sh  # força header
#   KEEP=1 ...      # mantém o keyfile após a sessão (não recomendado)
# ═══════════════════════════════════════════════════════════════════════

set -u

URL="${URL:-http://localhost:8765}"
COUNT="${COUNT:-10}"
MONTHS="${MONTHS:-1}"

echo "═══ CYPHER65 · Beta Trial Key Emitter ═══"
echo "Emitindo $COUNT keys (plan=pro, months=$MONTHS)..."

# Arquivo de resultado: 0600 desde a criação (umask 077 + chmod explícito).
# Template sem '-t' + sufixo: portável entre GNU mktemp (aceita XXXXXX no
# template) e BSD/macOS (o -t prefixo mantém o template literal no nome).
umask 077
RESULT_FILE="$(mktemp "${TMPDIR:-/tmp}/beta-keys-XXXXXX")" || {
    echo "❌ mktemp falhou — abortando" >&2
    exit 1
}
chmod 600 "$RESULT_FILE"

# Auto-destruição do keyfile no fim da sessão (ou em Ctrl-C).
if [ "${KEEP:-0}" != "1" ]; then
    trap 'rm -f "$RESULT_FILE"' EXIT INT TERM
fi

# Autenticação opcional por header (localhost-trust continua funcionando
# quando ADMIN_API_KEY não está definida).
AUTH_ARGS=()
if [ -n "${ADMIN_API_KEY:-}" ]; then
    AUTH_ARGS=(-H "X-API-Key: ${ADMIN_API_KEY}")
    echo "Auth: header X-API-Key (ADMIN_API_KEY definida)."
else
    echo "Auth: localhost-trust (defina ADMIN_API_KEY para forçar header)."
fi
# Portabilidade bash 3.2 (macOS): expandir array possivelmente vazio sob
# set -u só com o guard "${arr[@]+"${arr[@]}"}".
AUTH_EXPAND="${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"}"

OK=0
FAIL=0

for i in $(seq 1 "$COUNT"); do
    PAYLOAD="{\"plan\":\"pro\",\"months\":${MONTHS},\"source\":\"beta-trial-${i}\",\"email\":\"beta-tester-${i}@example.com\"}"
    RESP="$(curl -fsS --show-error \
        -X POST "$URL/api/admin/licenses" \
        -H "Content-Type: application/json" \
        $AUTH_EXPAND \
        -d "$PAYLOAD" 2>&1)"
    CURL_RC=$?

    if [ "$CURL_RC" -ne 0 ]; then
        echo "  ❌ [$i] HTTP falhou (curl rc=$CURL_RC): ${RESP:-sem corpo}" >&2
        FAIL=$((FAIL + 1))
        sleep 0.2
        continue
    fi

    # Contrato real: {"ok": true, "license_key": "C65-..."}.
    # (A v1 lia ".key" — campo que nunca existiu; toda emissão falharia.)
    KEY="$(printf '%s' "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("license_key",""))' 2>/dev/null)"

    if [ -n "$KEY" ]; then
        # stdout: só o status. A key vai EXCLUSIVAMENTE para o arquivo.
        printf '%s\n' "$KEY" >> "$RESULT_FILE"
        OK=$((OK + 1))
        echo "  ✅ [$i] emitida — gravada em $RESULT_FILE"
    else
        echo "  ❌ [$i] resposta sem license_key: $(printf '%s' "$RESP" | head -c 200)" >&2
        FAIL=$((FAIL + 1))
    fi
    sleep 0.2
done

echo ""
echo "═══ Resumo ═══"
echo "Emitidas: $OK · Falhas: $FAIL"
echo "🔑 Keys em: $RESULT_FILE (perm 600)"
if [ "${KEEP:-0}" != "1" ]; then
    echo "   ⚠️  auto-destrói no fim desta sessão — rode 'cat $RESULT_FILE' AGORA"
    echo "   ⚠️  e distribua por canal seguro (não cole keys em tickets/chats)."
fi
echo "Ativação pelo cliente: header X-License-Key (ou ?license=)."
echo "Revogação: docs/DEPLOYMENT_OPS.md · Este endpoint NÃO tem GET — para"
echo "auditar keys emitidas, consulte o DB (tabela de licensing) no server."

if [ "$FAIL" -gt 0 ]; then
    echo "❌ $FAIL falha(s) — sem retry automática (POST não-idempotente)." >&2
    exit 1
fi
echo "═══ Fim ═══"
