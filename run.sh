#!/usr/bin/env bash
# One command to run CareRelay: creates the venv if needed, installs, launches the patient-portal demo.
#   ./run.sh            # James's Shiny UI (agent course + results) on http://localhost:8501
#   ./run.sh portal     # the Streamlit drag-and-drop portal page instead (alias: streamlit)
#   ./run.sh test       # run the test suites
#   ./run.sh case_001   # run one bundled case in the terminal (no UI)
set -euo pipefail
cd "$(dirname "$0")"

# Load .env if present (copy .env.example and edit). Shell exports still win over the file.
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "creating .venv"
  if command -v uv >/dev/null; then uv venv .venv -q; else python3 -m venv .venv; fi
fi
if ! .venv/bin/python -c "import carerelay, streamlit, pypdf, shiny" >/dev/null 2>&1; then
  echo "installing dependencies"
  if command -v uv >/dev/null; then uv pip install -q --python .venv/bin/python -e ".[dev,ui]"; else .venv/bin/pip install -q -e ".[dev,ui]"; fi
fi

export AWS_REGION="${AWS_REGION:-us-east-1}"
case "${1:-ui}" in
  test)   exec .venv/bin/python -m pytest -q tests data/tests ;;
  case_*) exec .venv/bin/python -c "from carerelay import service; import json; r=service.handle({'scenario':'$1'}); print(r['report']['markdown'])" ;;
  portal|streamlit)
    echo "CareRelay Streamlit portal -> http://localhost:${PORT:-8501}   (Bedrock on: CARERELAY_USE_AWS=${CARERELAY_USE_AWS:-0})"
    exec .venv/bin/python -m streamlit run aws/streamlit/portal.py --server.port "${PORT:-8501}" --server.headless true --browser.gatherUsageStats false ;;
  ui|*)
    echo "CareRelay UI (Shiny, agent course) -> http://localhost:${PORT:-8501}   (Bedrock on: CARERELAY_USE_AWS=${CARERELAY_USE_AWS:-0})"
    exec .venv/bin/shiny run src/carerelay/ui/app.py --host 0.0.0.0 --port "${PORT:-8501}" ;;
esac
