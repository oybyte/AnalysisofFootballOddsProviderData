#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="$project_root/.venv/bin/python"

if [[ ! -x "$python_path" ]]; then
  echo "项目虚拟环境不存在，请先运行 scripts/bootstrap-agent.sh" >&2
  exit 1
fi

exec "$python_path" -m odds_journal "$@"
