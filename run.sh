#!/usr/bin/env bash
set -euo pipefail
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
if [ ! -d .venv ]; then
  echo "▶ creating venv…"
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo "⇢ starting cypher65 war room"
exec python app.py
