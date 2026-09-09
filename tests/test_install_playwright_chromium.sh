#!/usr/bin/env bash
# Hermetic self-test for the bounded retry used by Playwright CI setup.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/scripts/install-playwright-chromium.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -u' \
  'if [ "${2:-}" = "install-deps" ]; then' \
  '  if [ -n "${FAKE_BLOCKING_APT_SOURCE:-}" ] && [ -f "$FAKE_BLOCKING_APT_SOURCE" ]; then exit 43; fi' \
  '  count=0' \
  '  [ ! -f "$FAKE_NPX_STATE" ] || count="$(cat "$FAKE_NPX_STATE")"' \
  '  count=$((count + 1))' \
  '  printf "%s" "$count" > "$FAKE_NPX_STATE"' \
  '  if [ "$count" -le "${FAKE_NPX_FAIL_DEPS:-0}" ]; then exit 42; fi' \
  '  exit 0' \
  'fi' \
  'exit "${FAKE_NPX_BROWSER_STATUS:-0}"' > "$TMP/bin/npx"
printf '%s\n' '#!/usr/bin/env bash' 'exec "$@"' > "$TMP/bin/sudo"
chmod +x "$TMP/bin/npx" "$TMP/bin/sudo"

PASS=0
FAIL=0

run_case() { # label expected_exit failures max_attempts browser_status expected_calls
  local label="$1" expected="$2" failures="$3" max_attempts="$4"
  local browser_status="$5" expected_calls="$6" got calls
  rm -f "$TMP/state"
  PATH="$TMP/bin:$PATH" \
    FAKE_NPX_STATE="$TMP/state" \
    FAKE_NPX_FAIL_DEPS="$failures" \
    FAKE_NPX_BROWSER_STATUS="$browser_status" \
    PLAYWRIGHT_DEPS_MAX_ATTEMPTS="$max_attempts" \
    PLAYWRIGHT_DEPS_BACKOFF_SECONDS=0 \
    PLAYWRIGHT_APT_SOURCES_DIR="$TMP/empty-sources" \
    bash "$INSTALLER" >/dev/null 2>&1
  got=$?
  calls=0
  [ ! -f "$TMP/state" ] || calls="$(cat "$TMP/state")"
  if [ "$got" -eq "$expected" ] && [ "$calls" -eq "$expected_calls" ]; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    echo "FAIL: $label (exit=$got/$expected deps_calls=$calls/$expected_calls)" >&2
  fi
}

run_case 'success without retry' 0 0 5 0 1
run_case 'four transient failures recover' 0 4 5 0 5
run_case 'persistent failure remains blocking' 42 9 3 0 3
run_case 'browser failure stops before apt deps' 17 0 5 17 0

mkdir -p "$TMP/apt-sources"
printf '%s\n' 'deb [arch=amd64] https://dl.google.com/linux/chrome-stable/deb stable main' \
  > "$TMP/apt-sources/google-chrome.list"
rm -f "$TMP/state"
PATH="$TMP/bin:$PATH" FAKE_NPX_STATE="$TMP/state" \
  FAKE_BLOCKING_APT_SOURCE="$TMP/apt-sources/google-chrome.list" \
  PLAYWRIGHT_APT_SOURCES_DIR="$TMP/apt-sources" \
  PLAYWRIGHT_DEPS_MAX_ATTEMPTS=1 PLAYWRIGHT_DEPS_BACKOFF_SECONDS=0 \
  bash "$INSTALLER" >/dev/null 2>&1
source_status=$?
if [ "$source_status" -eq 0 ] \
  && [ -f "$TMP/apt-sources/google-chrome.list" ] \
  && [ ! -e "$TMP/apt-sources/google-chrome.list.cypher65-disabled" ]; then
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
  echo "FAIL: Chrome source isolation and restoration" >&2
fi

PATH="$TMP/bin:$PATH" FAKE_NPX_STATE="$TMP/state" \
  PLAYWRIGHT_DEPS_MAX_ATTEMPTS=0 PLAYWRIGHT_DEPS_BACKOFF_SECONDS=0 \
  PLAYWRIGHT_APT_SOURCES_DIR="$TMP/empty-sources" \
  bash "$INSTALLER" >/dev/null 2>&1
invalid_status=$?
if [ "$invalid_status" -eq 2 ]; then
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
  echo "FAIL: invalid attempt bound (exit=$invalid_status/2)" >&2
fi

if [ "$FAIL" -ne 0 ]; then
  echo "$FAIL installer self-test(s) failed; $PASS passed" >&2
  exit 1
fi
echo "All $PASS Playwright installer self-tests passed."
