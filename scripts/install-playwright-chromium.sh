#!/usr/bin/env bash
# Install Chromium and its system dependencies for Playwright.
#
# Third-party APT indexes can be briefly inconsistent while being published.
# Retry only the idempotent dependency installation with bounded backoff;
# persistent failures remain blocking.

set -euo pipefail

MAX_ATTEMPTS="${PLAYWRIGHT_DEPS_MAX_ATTEMPTS:-5}"
BACKOFF_SECONDS="${PLAYWRIGHT_DEPS_BACKOFF_SECONDS:-15}"
APT_SOURCES_DIR="${PLAYWRIGHT_APT_SOURCES_DIR:-/etc/apt/sources.list.d}"

case "$MAX_ATTEMPTS" in
  ''|*[!0-9]*) echo "PLAYWRIGHT_DEPS_MAX_ATTEMPTS must be an integer from 1 to 5" >&2; exit 2 ;;
esac
case "$BACKOFF_SECONDS" in
  ''|*[!0-9]*) echo "PLAYWRIGHT_DEPS_BACKOFF_SECONDS must be an integer from 0 to 60" >&2; exit 2 ;;
esac
if [ "$MAX_ATTEMPTS" -lt 1 ] || [ "$MAX_ATTEMPTS" -gt 5 ]; then
  echo "PLAYWRIGHT_DEPS_MAX_ATTEMPTS must be an integer from 1 to 5" >&2
  exit 2
fi
if [ "$BACKOFF_SECONDS" -gt 60 ]; then
  echo "PLAYWRIGHT_DEPS_BACKOFF_SECONDS must be an integer from 0 to 60" >&2
  exit 2
fi

npx playwright install chromium

# GitHub's Ubuntu images include Chrome's own repository even though
# Playwright installs bundled Chromium. A publication race in that unrelated
# index can make every `apt-get update` fail. Quarantine only source files that
# explicitly name that repository, then restore them on every exit path.
disabled_sources=()
restore_sources() {
  local source
  for source in "${disabled_sources[@]}"; do
    if [ -e "${source}.cypher65-disabled" ]; then
      sudo mv -- "${source}.cypher65-disabled" "$source"
    fi
  done
}

if [ -d "$APT_SOURCES_DIR" ]; then
  while IFS= read -r source; do
    if [ -e "${source}.cypher65-disabled" ]; then
      echo "Refusing to overwrite existing disabled APT source: ${source}.cypher65-disabled" >&2
      exit 2
    fi
    sudo mv -- "$source" "${source}.cypher65-disabled"
    disabled_sources+=("$source")
    trap restore_sources EXIT
    echo "Temporarily disabled unrelated Chrome APT source: $source"
  done < <(
    sudo grep -lF 'dl.google.com/linux/chrome-stable/deb' \
      "$APT_SOURCES_DIR"/*.list "$APT_SOURCES_DIR"/*.sources 2>/dev/null || true
  )
fi

attempt=1
while true; do
  set +e
  sudo npx playwright install-deps chromium
  status=$?
  set -e

  if [ "$status" -eq 0 ]; then
    echo "Playwright system dependencies installed on attempt ${attempt}/${MAX_ATTEMPTS}."
    break
  fi
  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "Playwright system dependencies failed after ${attempt}/${MAX_ATTEMPTS} attempts." >&2
    exit "$status"
  fi

  delay=$((BACKOFF_SECONDS * attempt))
  echo "Playwright system dependencies failed (exit ${status}); retrying in ${delay}s." >&2
  sleep "$delay"
  attempt=$((attempt + 1))
done
