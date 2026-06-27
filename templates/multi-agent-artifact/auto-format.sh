#!/bin/bash
# auto-format.sh — PostToolUse(Edit|Write) hook
# Edit/Write 후 Python 파일을 ruff format(우선) 또는 black으로 포맷.
# fail-open 원칙: 도구 없음/파싱 실패/포맷 실패 시 통과. 절대 block하지 않는다.

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
case "$TOOL_NAME" in
  Edit|Write) ;;
  *) exit 0 ;;
esac

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

EXT=$(echo "${FILE_PATH##*.}" | tr '[:upper:]' '[:lower:]')

if [ "$EXT" = "py" ]; then
  # ruff format 우선, 없으면 black. 둘 다 없거나 실패해도 fail-open.
  if command -v ruff >/dev/null 2>&1; then
    ruff format "$FILE_PATH" >/dev/null 2>&1 || true
  elif command -v black >/dev/null 2>&1; then
    black --quiet "$FILE_PATH" >/dev/null 2>&1 || true
  fi
fi

exit 0
