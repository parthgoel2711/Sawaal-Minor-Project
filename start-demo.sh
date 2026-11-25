#!/usr/bin/env bash
# Presentation mode:  ./start-demo.sh
# No API key needed. Answers the prepared questions, with sign-in and restricted tables switched on.
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r backend/requirements.txt
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

export DEMO_MODE=true AUTH_ENABLED=true DEMO_USERS=true RESTRICTED_TABLES=payroll,performance_reviews
echo
echo "  Sawaal demo.  Sign in as:  admin / admin-demo   analyst / analyst-demo   viewer / viewer-demo"
echo
cd backend
OPEN_BROWSER=1 exec ../.venv/bin/python -m app
