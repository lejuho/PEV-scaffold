#!/bin/bash
# block-dangerous.sh — PreToolUse(Bash) hook
# 위험 명령 패턴 감지 시 block. fail-open 원칙: 검증 불가능한 모든 상황에서 통과.
# PowerShell -match는 case-insensitive이므로 grep -iE 사용.

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$TOOL_NAME" != "Bash" ] && exit 0

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$COMMAND" ] && exit 0

PATTERNS=(
  'rm[[:space:]]+-rf[[:space:]]+[/~*]'
  'Remove-Item[[:space:]].*-Recurse.*-Force[[:space:]]+[/C-Z]:\\'
  'DROP[[:space:]]+TABLE'
  'DROP[[:space:]]+DATABASE'
  'TRUNCATE[[:space:]]+TABLE'
  'dd[[:space:]].*of=/dev/'
  'mkfs\.'
  'git[[:space:]]+push[[:space:]].*--force[^-].*\b(main|master)\b'
  'git[[:space:]]+reset[[:space:]]+--hard[[:space:]]+HEAD[^~]'
  'del[[:space:]]+/[sS][[:space:]]+/[qQ][[:space:]]+[C-Z]:\\\*'
)

for p in "${PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qiE "$p" 2>/dev/null; then
    # JSON 안전: 패턴의 역슬래시·큰따옴표 이스케이프
    ESC_P=$(printf '%s' "$p" | sed 's/\\/\\\\/g; s/"/\\"/g')
    cat <<EOF
{
  "decision": "block",
  "reason": "위험 명령 감지 (패턴: '${ESC_P}'). 실행 차단됨. 의도한 명령이 맞다면 사용자에게 직접 확인을 받고 진행할 것."
}
EOF
    exit 0
  fi
done

exit 0
