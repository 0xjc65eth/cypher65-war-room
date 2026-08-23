#!/usr/bin/env bash
# check-tokens-hex.sh — CI tokens-gate (Issue #237)
# =================================================
# FALHA se houver #hex hard-coded fora do allowlist nos arquivos de UI:
#
#   GATE (exit 1):
#     static/app.js, static/sw.js, templates/*.html (exceto *.backup)
#     — qualquer #hex é cor fora do token system → cssVar()/var() obrigatório.
#
#   ALLOWLIST (permitido):
#     - static/style.css            — fonte dos tokens (NUNCA escaneado)
#     - linhas "theme-color"        — <meta theme-color content="#070808">
#                                     (única exceção on-palette, documentada)
#     - rgb()/rgba()                — neutros ou derivados; o gate duro é hex
#                                     (tradeoff documentado no PR #240)
#
#   FALSOS POSITIVOS (excluídos por linha inteira):
#     - "Issue #NNN"                — refs de issues em comentários
#     - "#hex-"                     — seletores de DOM por id ($('#fcc-...'))
#
#   GATE (exit 1) — mobile/ (Issue #239):
#     - qualquer #hex fora de mobile/src/theme.ts — a paleta RN vive SÓ
#       nos tokens (theme.ts é excluído do scan, como style.css no web).
#     - testes co-localizados *.test.ts / *.spec.ts / __tests__ / tests/
#       ficam FORA do GATE (Issue #341) — fixtures de cor em teste não
#       devem quebrar o CI; o GATE cobre código de produção apenas.
#
# Env overrides (self-test):
#   TOKENS_SCAN_FILES — lista de arquivos a escanear (substitui o GATE)
#   TOKENS_MOBILE_DIR — dir mobile a medir ("" desliga o scan mobile)
#
# Exit: 0 clean · 1 violações · 2 erro de execução
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEX_RE='#[0-9a-fA-F]{3,8}\b'
FAILED=0
VIOLATIONS=0

scan_file() {  # $1 = arquivo
  local f="$1"
  # SED-STRIP ANTES de extrair: os não-cores (ref "Issue #NNN", selector
  # "#hex-", allowlist theme-color) são REMOVIDOS da linha, não a linha
  # descartada — uma linha com cor real + ref de Issue continua auditada
  # (sem falso negativo em linha mista, ver self-test caso 8).
  local out
  out=$(sed -E \
    -e 's/theme-color.*#070808//g' \
    -e 's/Issue[[:space:]]*#[0-9a-fA-F]{3,8}//g' \
    -e 's/#[0-9a-fA-F]{3,8}-//g' \
    "$f" 2>/dev/null \
    | grep -noE "$HEX_RE" || true)
  if [ -n "$out" ]; then
    echo "  ❌ $f"
    echo "$out" | sed 's/^/     /'
    VIOLATIONS=$((VIOLATIONS + $(printf '%s\n' "$out" | wc -l | tr -d ' ')))
    FAILED=1
  fi
}

# Todo cssVar('--X') no app.js precisa existir no :root do style.css — token
# com nome errado renderiza '' (UI invisível) sem erro no console.
check_cssvar_tokens() {
  local bad
  bad=$(grep -oE "cssVar\('--[a-z0-9-]+'\)" static/app.js \
    | sed -E "s/cssVar\('(--[a-z0-9-]+)'\)/\1/" \
    | sort -u \
    | while read -r t; do grep -qF -- "$t:" static/style.css || echo "$t"; done)
  if [ -n "$bad" ]; then
    echo "❌ cssVar() aponta para tokens inexistentes no :root:"
    echo "$bad" | sed 's/^/     /'
    FAILED=1
  fi
}

if [ -n "${TOKENS_SCAN_FILES:-}" ]; then
  # Modo self-test: arquivos explícitos, sem o scan mobile nem o cssVar-check.
  for f in $TOKENS_SCAN_FILES; do scan_file "$f"; done
else
  for f in static/app.js static/sw.js $(ls templates/*.html 2>/dev/null | grep -v '\.backup'); do
    [ -f "$f" ] && scan_file "$f"
  done
  check_cssvar_tokens
fi

# GATE — mobile/ (Issue #239): a paleta RN vive SÓ em theme.ts. Qualquer
# #hex fora dos tokens falha o CI (theme.ts é excluído do scan).
MOBILE_DIR="${TOKENS_MOBILE_DIR:-mobile}"
MOBILE_HEX=0
if [ -n "$MOBILE_DIR" ] && [ -d "$MOBILE_DIR" ]; then
  MOBILE_HEX=$(grep -rnE "$HEX_RE" "$MOBILE_DIR" \
      --include='*.tsx' --include='*.ts' --include='*.js' \
      --exclude='theme.ts' \
      --exclude='*.test.ts' --exclude='*.spec.ts' \
      --exclude-dir=node_modules --exclude-dir='__tests__' 2>/dev/null \
    | grep -vE '/tests/' \
    | grep -vE 'Issue[[:space:]]*#[0-9a-fA-F]{3,8}' \
    | grep -vE '#[0-9a-fA-F]{3,8}-' \
    | wc -l | tr -d ' ')
  if [ "$MOBILE_HEX" -gt 0 ]; then
    echo "❌ [tokens-hex] mobile/: $MOBILE_HEX hex fora do theme.ts — use tokens de mobile/src/theme.ts"
    FAILED=1
  fi
fi

if [ "$FAILED" -ne 0 ]; then
  echo "❌ [tokens-hex] $VIOLATIONS hex fora do allowlist (style.css + theme-color) — use cssVar()/tokens"
  exit 1
fi
echo "✅ [tokens-hex] guards OK — zero hex fora do style.css em app.js/sw/templates e zero hex fora do theme.ts em mobile/"
exit 0
