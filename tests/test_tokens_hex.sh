#!/usr/bin/env bash
# test_tokens_hex.sh — self-test do guard scripts/check-tokens-hex.sh (Issue #237)
#
# Roda o guard REAL (subprocesso) contra fixtures descartáveis via override
# TOKENS_SCAN_FILES e asserta os exit codes:
#
#   1. app.js limpo (sem hex)            → exit 0
#   2. color: '#00c853'                  → exit 1 (GUARD: hex fora da allowlist)
#   3. comentário "Issue #186"           → exit 0 (sem falso positivo)
#   4. seletor de id "$('#fcc-…')"       → exit 0 (sem falso positivo)
#   5. template só com theme-color       → exit 0 (allowlist)
#   6. rgb() permitido                   → exit 0 (tradeoff documentado)
#   7. repo real (sem override)          → exit 0 (sweep feito; mobile é INFO)
#
# Run: bash tests/test_tokens_hex.sh   (wire no check_frontend.sh)

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUARD="$ROOT/scripts/check-tokens-hex.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0

check() {  # $1=label  $2=esperado  $3...=arquivos fixture
  local label="$1" expected="$2"
  shift 2
  local files=()
  local f
  for f in "$@"; do files+=("$TMP/$f"); done
  TOKENS_SCAN_FILES="${files[*]}" TOKENS_MOBILE_DIR="" bash "$GUARD" >/dev/null 2>&1
  local got=$?
  if [ "$got" -eq "$expected" ]; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    echo "  ❌ $label: esperado $expected, got $got"
  fi
}

# 1. Limpo.
printf 'const el = document.body;\nel.textContent = "ok";\n' > "$TMP/clean.js"
check '1 · app.js limpo exit 0' 0 clean.js

# 2. Hex de cor.
printf 'const c = "#00c853";\n' > "$TMP/bad.js"
check '2 · hex de cor exit 1' 1 bad.js

# 3. Ref de Issue em comentário.
printf '// Issue #186: defer no Chart.js\nconst x = 1;\n' > "$TMP/issue.js"
check '3 · Issue #NNN sem FP exit 0' 0 issue.js

# 4. Seletor de id por #hex-.
printf "const el = \$('#fcc-summary-hr');\n" > "$TMP/idsel.js"
check '4 · seletor #hex- sem FP exit 0' 0 idsel.js

# 5. Allowlist theme-color.
printf '<meta name="theme-color" content="#070808">\n' > "$TMP/theme.html"
check '5 · theme-color allowlist exit 0' 0 theme.html

# 6. rgb() permitido (tradeoff documentado).
printf "const c = 'rgb(6,214,240)';\n" > "$TMP/rgb.js"
check '6 · rgb() permitido exit 0' 0 rgb.js

# 7b. Linha MISTA: cor real + ref de Issue — a linha NÃO pode ser
# descartada inteira (falso negativo antigo do filtro por linha).
printf "const c = '#00c853'; // Issue #186: cor legítima\n" > "$TMP/mixed.js"
check '7b · linha mista (cor + Issue ref) exit 1' 1 mixed.js

# 7. Repo real (app.js + sw.js + templates/*.html, sem override).
bash "$GUARD" >/dev/null 2>&1
if [ "$?" -eq 0 ]; then
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
  echo '  ❌ 7 · repo real exit 0'
fi

echo
echo '══════════════════════════════════════════════'
if [ "$FAIL" -eq 0 ]; then
  echo "✅ ALL $PASS TOKENS-HEX SELF-TESTS PASSED"
else
  echo "❌ $FAIL/$((PASS + FAIL)) TOKENS-HEX SELF-TESTS FAILED"
fi
exit $((FAIL > 0 ? 1 : 0))
