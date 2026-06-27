#!/bin/bash
# track-failures.sh — PostToolUse(Bash) hook
# 같은 에러 시그니처가 2회째 재현되면 block(2-strike Andon) → Loop break 강제.
# fail-open 원칙: 검증 불가능한 모든 상황에서 통과.

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$TOOL_NAME" != "Bash" ] && exit 0

EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exit_code // empty' 2>/dev/null)
# null 또는 0이면 실패 아님 → 통과
[ -z "$EXIT_CODE" ] && exit 0
[ "$EXIT_CODE" = "0" ] && exit 0

OUTPUT=$(echo "$INPUT" | jq -r '.tool_response.output // empty' 2>/dev/null)
[ -z "$OUTPUT" ] && exit 0

# 첫 의미 있는 에러 라인을 시그니처로
ERROR_LINE=$(echo "$OUTPUT" | grep -E "(Error|Exception|FAILED|Traceback|error:|TypeError|ValueError|ImportError)" | head -1)
[ -z "$ERROR_LINE" ] && exit 0

# 공백 정규화 + trim + 200자 제한
ERROR_SIG=$(echo "$ERROR_LINE" | sed 's/[[:space:]]\{1,\}/ /g; s/^ //; s/ $//' | cut -c1-200)
[ -z "$ERROR_SIG" ] && exit 0

# 프로젝트별 로그 파일
PROJECT_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null)
[ -z "$PROJECT_NAME" ] && PROJECT_NAME="unknown"
FAILURE_LOG="${TMPDIR:-/tmp}/claude-failures-${PROJECT_NAME}.log"

MATCH_COUNT=0
if [ -f "$FAILURE_LOG" ]; then
  MATCH_COUNT=$(grep -Fxc "$ERROR_SIG" "$FAILURE_LOG" 2>/dev/null)
  MATCH_COUNT=${MATCH_COUNT:-0}
fi

if [ "$MATCH_COUNT" -ge 1 ]; then
  # JSON 안전: 역슬래시·큰따옴표 이스케이프 (공백은 이미 단일 스페이스로 정규화돼 제어문자 없음)
  ESC_SIG=$(printf '%s' "$ERROR_SIG" | sed 's/\\/\\\\/g; s/"/\\"/g')
  cat <<EOF
{
  "decision": "block",
  "reason": "2-strike Andon: 동일 에러 시그니처가 2회 이상 재현됨. 같은 접근으로 재시도 금지. Advisor에 Loop break 호출 필수: 'Loop break: [에러 시그니처], [시도한 것 3개], [근본 원인 가설]'. 에러: ${ESC_SIG}"
}
EOF
  exit 0
fi

echo "$ERROR_SIG" >> "$FAILURE_LOG"
exit 0
