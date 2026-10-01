#!/bin/bash
# One-time setup on the Mac mini. Run from the VISION folder:  bash scripts/setup.sh
set -e
cd "$(dirname "$0")/.."
command -v python3 >/dev/null || { echo "Install Python 3.12 first (brew install python@3.12)"; exit 1; }
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "Created .env (fill in your keys)"; }
mkdir -p data logs vault inbox/wealthsimple
.venv/bin/python -m vision check
echo
echo "Setup done. Start VISION now with:  .venv/bin/python -m vision"
echo "Or install auto-start with:         bash scripts/install_launchagent.sh"
