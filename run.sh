#!/usr/bin/env bash
# One command to run CareRelay: creates the venv if needed, installs, launches the patient-portal demo.
#   ./run.sh            # portal UI on http://localhost:8501
#   ./run.sh test       # run the test suites
#   ./run.sh case_001   # run one bundled case in the terminal (no UI)
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "creating .venv"
  if command -v uv >/dev/null; then uv venv .venv -q; else python3 -m venv .venv; fi
fi
if ! .venv/bin/python -c "import carerelay, streamlit, pypdf" >/dev/null 2>&1; then
  echo "installing dependencies"
  if command -v uv >/dev/null; then uv pip install -q --python .venv/bin/python -e ".[dev]"; else .venv/bin/pip install -q -e ".[dev]"; fi
fi

export AWS_REGION="${AWS_REGION:-us-east-1}"
case "${1:-portal}" in
  test)   exec .venv/bin/python -m pytest -q tests data/tests ;;
  case_*) exec .venv/bin/python -c "from carerelay import service; import json; r=service.handle({'scenario':'$1'}); print(r['report']['markdown'])" ;;
  portal|*)
    echo "CareRelay portal -> http://localhost:${PORT:-8501}   (Bedrock: ${CARERELAY_USE_AWS:-0}=1 to enable)"
    exec .venv/bin/python -m streamlit run aws/streamlit/portal.py --server.port "${PORT:-8501}" --server.headless true --browser.gatherUsageStats false ;;
esac
