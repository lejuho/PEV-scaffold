#!/bin/bash
# PostToolUse(Read) hook — Cycle 단위 file-read 카운터
# fail-open + soft enforcement
#
# 한계:
#   5-file rule은 원래 step 단위 규칙인데, hook은 step 경계를 정확히 알 수 없음.
#   대신 cycle 단위 누적 카운트로 근사. 너무 많은 파일을 읽으면 신호.
#
# 기본값:
#   CYCLE_FILE_LIMIT=25 (한 cycle 동안 25개 unique 파일 read 허용)
#   필요 시 환경 변수로 override
#
# 제외 대상:
#   AGENTS.md, CLAUDE.md, .review/ 안의 메타 파일은 카운트 안 함
#   skill 파일 (.claude/skills/, agents/skills/)도 카운트 안 함

INPUT=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

# Read 도구 외에는 통과
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$TOOL_NAME" != "Read" ] && exit 0

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$FILE_PATH" ] && exit 0

# 메타 파일 제외 (case insensitive를 위해 lowercase 비교)
LOWER_PATH=$(echo "$FILE_PATH" | tr '[:upper:]' '[:lower:]')
case "$LOWER_PATH" in
  */agents.md|*/claude.md) exit 0 ;;
  */.review/*) exit 0 ;;
  */.claude/skills/*|*/agents/skills/*) exit 0 ;;
  */.claude/hooks/*|*/.codex/hooks/*) exit 0 ;;
esac

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && exit 0

# 현재 진행 중인 cycle 찾기
CURRENT_CYCLE=""
for status_file in "$GIT_ROOT"/.review/cycle-*/status.txt; do
  [ ! -f "$status_file" ] && continue
  if grep -q "in_progress" "$status_file" 2>/dev/null; then
    CURRENT_CYCLE=$(dirname "$status_file")
    break
  fi
done

# 진행 중 cycle 없으면 통과
[ -z "$CURRENT_CYCLE" ] && exit 0

COUNTER="$CURRENT_CYCLE/.read-counter"
FILE_LIMIT=${CYCLE_FILE_LIMIT:-25}

# 이미 카운트된 파일이면 통과 (중복 read 허용)
if [ -f "$COUNTER" ] && grep -qFx "$FILE_PATH" "$COUNTER" 2>/dev/null; then
  exit 0
fi

# 새 파일 추가
echo "$FILE_PATH" >> "$COUNTER"
CURRENT_COUNT=$(wc -l < "$COUNTER" 2>/dev/null | tr -d ' ')
CURRENT_COUNT=${CURRENT_COUNT:-0}

# 한도 이내면 통과
if [ "$CURRENT_COUNT" -le "$FILE_LIMIT" ]; then
  exit 0
fi

# 초과 — block
cat <<EOF
{
  "decision": "block",
  "reason": "Context budget 초과. 이번 cycle에서 read한 unique 파일 ${CURRENT_COUNT}개로 limit ${FILE_LIMIT}개 초과. just-in-time retrieval 원칙 위반 가능성. halt + report 후 다음 중 하나를 결정: (1) plan.md amend (Key Changes 추가 누락), (2) cycle split, (3) step 재정의. CLAUDE.md 'Context Discipline' 섹션 참조. counter 위치: ${COUNTER}"
}
EOF
