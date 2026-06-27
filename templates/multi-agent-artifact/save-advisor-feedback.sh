#!/bin/bash
# Stop hook — Advisor 호출 횟수와 step-NNN.md 파일 수 일치 검증
# fail-open 원칙: 검증 불가능한 모든 상황에서 통과
#
# 검증 로직:
#   transcript에서 "Approach check:" / "Completion check:" / "Loop break:" 카운트
#   .review/cycle-N/advisor-feedback/step-*.md 파일 수와 비교
#   호출 > 파일 수인 경우 (저장 누락) block
#   호출 == 파일 수 또는 호출 < 파일 수인 경우 통과

INPUT=$(cat)

# jq 없으면 통과
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

# JSON 파싱
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)

# 무한루프 방지
[ "$STOP_HOOK_ACTIVE" = "true" ] && exit 0

# transcript 없거나 못 읽으면 통과
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

# git root 찾기
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && exit 0

# .review 디렉터리 없으면 통과 (cycle 시스템 미사용 세션)
REVIEW_DIR="$GIT_ROOT/.review"
[ ! -d "$REVIEW_DIR" ] && exit 0

# 진행 중인 cycle 찾기 (status.txt == in_progress)
CURRENT_CYCLE=""
for status_file in "$REVIEW_DIR"/cycle-*/status.txt; do
  [ ! -f "$status_file" ] && continue
  if grep -q "in_progress" "$status_file" 2>/dev/null; then
    CURRENT_CYCLE=$(dirname "$status_file")
    break
  fi
done

# 진행 중 cycle 없으면 통과
[ -z "$CURRENT_CYCLE" ] && exit 0

# 변경된 파일이 없으면 코드 작업 안 한 세션으로 보고 통과
DIFF_FILES=$(git -C "$GIT_ROOT" diff --name-only HEAD 2>/dev/null)
CACHED_FILES=$(git -C "$GIT_ROOT" diff --cached --name-only 2>/dev/null)
if [ -z "$DIFF_FILES" ] && [ -z "$CACHED_FILES" ]; then
  exit 0
fi

# transcript에서 Advisor 호출 카운트 (최근 200KB 범위)
# 가드 ":[[:space:]]*[^[:space:]\`[]" — 콜론 뒤 첫 실문자가 '['/공백/백틱이 아니어야 카운트.
# CLAUDE.md 템플릿 행("Approach check: [모듈명]...")은 콜론 뒤가 '['라 제외됨(과대카운트 방지).
# 한계(M-ADVISOR-CALL): 실제 호출을 "[모듈명]"처럼 대괄호로 시작하면 그것도 제외돼 과소카운트.
#   → 근본 해결은 전용 토큰 "[[ADVISOR-CALL:type]]" 도입. CONTRACT_MARKERS.md M-ADVISOR-CALL 참조.
RECENT=$(tail -c 200000 "$TRANSCRIPT" 2>/dev/null) || exit 0
ADVISOR_CALLS=$(echo "$RECENT" | grep -cE "(Approach check|Completion check|Loop break):[[:space:]]*[^[:space:]\`[]" 2>/dev/null)
ADVISOR_CALLS=${ADVISOR_CALLS:-0}

# step 파일 카운트
FEEDBACK_DIR="$CURRENT_CYCLE/advisor-feedback"
if [ -d "$FEEDBACK_DIR" ]; then
  STEP_FILES=$(find "$FEEDBACK_DIR" -maxdepth 1 -name "step-*.md" -type f 2>/dev/null | wc -l)
  STEP_FILES=$(echo "$STEP_FILES" | tr -d ' ')
else
  STEP_FILES=0
fi

# Advisor 호출 0회면 force-advisor-check.sh가 잡을 영역 — 여기서는 통과
[ "$ADVISOR_CALLS" -eq 0 ] && exit 0

# 호출 ≤ 파일 수면 통과 (저장 충실 또는 이전 cycle 파일 잔존)
if [ "$ADVISOR_CALLS" -le "$STEP_FILES" ]; then
  exit 0
fi

# 호출 > 파일 수: 저장 누락
MISSING=$((ADVISOR_CALLS - STEP_FILES))

cat <<EOF
{
  "decision": "block",
  "reason": "Advisor 호출 ${ADVISOR_CALLS}회 vs step 파일 ${STEP_FILES}개. ${MISSING}개의 Advisor 피드백이 ${FEEDBACK_DIR}/step-NNN.md로 저장되지 않았음. 누락된 step 파일을 작성한 뒤 다시 종료할 것. 파일 format은 AGENTS.md 'Advisor Feedback Externalization' 섹션 참조. 무시 항목이 있으면 'Sonnet Response' 섹션에 이유 명시 필수."
}
EOF
