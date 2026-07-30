#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_python="$project_root/.venv/bin/python"
sync_agents="${1:-}"

if [[ ! -x "$venv_python" ]]; then
  python3.11 -m venv "$project_root/.venv"
fi
"$venv_python" -m pip install -e "$project_root[dev]"
"$venv_python" -m odds_journal build-index

if [[ "$sync_agents" == "--sync-agents" ]]; then
  approved_by="${2:-}"
  confirmation="${3:-}"
  if [[ "$approved_by" != "lcz" || "$confirmation" != "--confirm-sync" ]]; then
    echo "同步用法：bootstrap-agent.sh --sync-agents lcz --confirm-sync" >&2
    exit 2
  fi
  "$venv_python" -m odds_journal agent sync --approved-by "$approved_by" --confirm-sync
fi

"$venv_python" -m odds_journal agent doctor
