#!/bin/bash
# force-advisor-check.sh — Stop hook
# 코드 변경이 있는 cycle에서 "Completion check:" Advisor 호출이 있었는지 강제.
# fail-open 원칙: 검증 불가능한 모든 상황에서 통과.
#
# 마커: M-ADVISOR-CALL (CONTRACT_MARKERS.md). 가드 정규식은 save-advisor-feedback.sh와 동일 —
#   콜론 뒤 첫 실문자가 '['/공백/백틱이면 제외(CLAUDE.md 템플릿 행 카운트 방지).

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0

STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[ "$STOP_HOOK_ACTIVE" = "true" ] && exit 0

TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && exit 0

REVIEW_DIR="$GIT_ROOT/.review"
[ ! -d "$REVIEW_DIR" ] && exit 0

# 진행 중 cycle 찾기 (M-STATUS)
CURRENT_CYCLE=""
for status_file in "$REVIEW_DIR"/cycle-*/status.txt; do
  [ ! -f "$status_file" ] && continue
  if grep -q "in_progress" "$status_file" 2>/dev/null; then
    CURRENT_CYCLE=$(dirname "$status_file")
    break
  fi
done
[ -z "$CURRENT_CYCLE" ] && exit 0

# 코드 변경 없으면 통과
DIFF_FILES=$(git -C "$GIT_ROOT" diff --name-only HEAD 2>/dev/null)
CACHED_FILES=$(git -C "$GIT_ROOT" diff --cached --name-only 2>/dev/null)
if [ -z "$DIFF_FILES" ] && [ -z "$CACHED_FILES" ]; then
  exit 0
fi

RECENT=$(tail -c 200000 "$TRANSCRIPT" 2>/dev/null) || exit 0

COMPLETION_CHECKS=$(echo "$RECENT" | grep -cE "Completion check:[[:space:]]*[^[:space:]\`[]" 2>/dev/null)
COMPLETION_CHECKS=${COMPLETION_CHECKS:-0}

[ "$COMPLETION_CHECKS" -gt 0 ] && exit 0

cat <<EOF
{
  "decision": "block",
  "reason": "Completion check 누락. 코드 변경이 감지됐지만 이번 세션에서 'Completion check:' Advisor 호출이 없음. step 완료 후 반드시 Completion check를 Advisor(Opus)에 위임하고 step-NNN.md에 저장할 것. CLAUDE.md 'Step Advisor 호출' 섹션 참조."
}
EOF
