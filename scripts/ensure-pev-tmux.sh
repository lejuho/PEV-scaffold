#!/usr/bin/env bash
set -euo pipefail

ROOT="${HERMES_ROOT:-/home/pi/cairn}"
CLAUDE_SESSION="${PEV_CLAUDE_SESSION:-cairn-claude}"
CODEX_SESSION="${PEV_CODEX_SESSION:-codex-hermes}"
CLAUDE_BIN="${PEV_CLAUDE_BIN:-/home/pi/.local/bin/claude}"
CODEX_BIN="${PEV_CODEX_BIN:-/mnt/data/pi_storage/.npm-global/bin/codex}"
CLAUDE_ARGS="${PEV_CLAUDE_ARGS:---continue --dangerously-skip-permissions}"
CODEX_ARGS="${PEV_CODEX_ARGS:---no-alt-screen --dangerously-bypass-approvals-and-sandbox}"

export HOME="${HOME:-/home/pi}"
export TERM="${TERM:-xterm-256color}"
export PATH="/home/pi/.local/bin:/mnt/data/pi_storage/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

ensure_session() {
  local session="$1"
  local command="$2"

  if tmux has-session -t "${session}" 2>/dev/null; then
    return 0
  fi

  tmux new-session -d -s "${session}" -c "${ROOT}" "bash -lc ${command@Q}"
}

ensure_session "${CLAUDE_SESSION}" "${CLAUDE_BIN} ${CLAUDE_ARGS}; exec bash -l"
ensure_session "${CODEX_SESSION}" "${CODEX_BIN} ${CODEX_ARGS}; exec bash -l"
