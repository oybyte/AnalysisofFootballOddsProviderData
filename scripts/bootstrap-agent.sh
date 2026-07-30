#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_python="$project_root/.venv/bin/python"
install_skills="${1:-}"

if [[ ! -x "$venv_python" ]]; then
  python3.11 -m venv "$project_root/.venv"
fi
"$venv_python" -m pip install -e "$project_root[dev]"
"$venv_python" -m odds_journal build-index

if [[ "$install_skills" == "--install-skills" ]]; then
  skill_source="$project_root/integrations/skills/football-odds-journal"
  codex_root="${CODEX_HOME:-$HOME/.codex}/skills/football-odds-journal"
  if [[ -d "$HOME/.workbuddy/skills" ]]; then
    workbuddy_root="$HOME/.workbuddy/skills/football-odds-journal"
  else
    workbuddy_root="$HOME/.codebuddy/skills/football-odds-journal"
  fi
  mkdir -p "$codex_root" "$workbuddy_root" "$project_root/dist"
  cp -R "$skill_source/." "$codex_root/"
  cp -R "$skill_source/." "$workbuddy_root/"
  (
    cd "$skill_source"
    zip -qr "$project_root/dist/football-odds-journal.skill" .
  )
  echo "telosWork Skill 安装包：$project_root/dist/football-odds-journal.skill"
fi

"$venv_python" -m odds_journal agent doctor
