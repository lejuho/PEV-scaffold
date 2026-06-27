#!/bin/bash
# Stop hook — Issue-velocity dual-trigger 검증
# 발동 시 status.txt = escalated로 변경하고 block
#
# Trigger 1 (Same-Issue Stagnation):
#   마지막 N개 review에서 같은 ISSUE-X가 모두 UNRESOLVED 마커로 등장하면 발동
#   기본값: 3 review 연속
#
# Trigger 2 (New-Issue Velocity):
#   최근 N개 review에서 신규 등장한 ISSUE 개수가 임계치 초과 시 발동
#   기본값: 5 review 윈도우에서 3개 이상 신규
#
# 환경 변수로 override 가능:
#   CYCLE_STAGNATION_LIMIT (default: 3)
#   CYCLE_VELOCITY_PASS_WINDOW (default: 5)
#   CYCLE_VELOCITY_ISSUE_LIMIT (default: 3)

INPUT=$(cat)

# jq 없으면 통과
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[ "$STOP_HOOK_ACTIVE" = "true" ] && exit 0

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && exit 0

REVIEW_DIR="$GIT_ROOT/.review"
[ ! -d "$REVIEW_DIR" ] && exit 0

# 진행 중 cycle 찾기
CURRENT_CYCLE=""
for status_file in "$REVIEW_DIR"/cycle-*/status.txt; do
  [ ! -f "$status_file" ] && continue
  if grep -q "in_progress" "$status_file" 2>/dev/null; then
    CURRENT_CYCLE=$(dirname "$status_file")
    break
  fi
done

[ -z "$CURRENT_CYCLE" ] && exit 0

# review-v*.md 파일 목록 (버전순 정렬)
REVIEW_FILES=$(find "$CURRENT_CYCLE" -maxdepth 1 -name "review-v*.md" -type f 2>/dev/null | sort -V)
[ -z "$REVIEW_FILES" ] && exit 0

REVIEW_COUNT=$(echo "$REVIEW_FILES" | wc -l | tr -d ' ')

# Threshold (환경 변수 override 가능)
STAGNATION_LIMIT=${CYCLE_STAGNATION_LIMIT:-3}
VELOCITY_PASS_WINDOW=${CYCLE_VELOCITY_PASS_WINDOW:-5}
VELOCITY_ISSUE_LIMIT=${CYCLE_VELOCITY_ISSUE_LIMIT:-3}

# ============================================================
# Trigger 1: Same-Issue Stagnation
# ============================================================
# 마지막 STAGNATION_LIMIT개 review에서 공통으로 UNRESOLVED인 ISSUE 찾기

STAGNANT_ISSUE=""

if [ "$REVIEW_COUNT" -ge "$STAGNATION_LIMIT" ]; then
  LAST_REVIEWS=$(echo "$REVIEW_FILES" | tail -n "$STAGNATION_LIMIT")

  COMMON_UNRESOLVED=""
  FIRST=true

  while IFS= read -r f; do
    [ -z "$f" ] && continue
    # 이 review 파일에서 UNRESOLVED/REGRESSION 상태인 ISSUE ID 추출
    # 실제 포맷: "## Previous Issue Status" 섹션의 "- ISSUE-N: UNRESOLVED|REGRESSION"
    #   (이전 버그: "UNRESOLVED ISSUE-N" 어순으로 긁어 문서 컨벤션과 영구 불일치 → Trigger 1 미발동)
    #   REGRESSION 포함 근거: 회귀도 "현재 미해결" 상태이므로 stagnation 판정에 포함.
    #   UNRESOLVED만 보고 싶으면 정규식에서 |REGRESSION 제거.
    # 마커 계약: CONTRACT_MARKERS.md (M-ISSUE-STATUS) 참조. 변경 시 그쪽도 동기화.
    CURRENT=$(grep -oE "ISSUE-[0-9]+:[[:space:]]*(UNRESOLVED|REGRESSION)" "$f" 2>/dev/null | grep -oE "ISSUE-[0-9]+" | sort -u)

    if [ "$FIRST" = "true" ]; then
      COMMON_UNRESOLVED="$CURRENT"
      FIRST=false
    else
      # intersection (둘 다 sort -u 상태)
      COMMON_UNRESOLVED=$(comm -12 <(echo "$COMMON_UNRESOLVED") <(echo "$CURRENT") 2>/dev/null)
    fi

    # 공통이 없어지면 조기 종료
    [ -z "$COMMON_UNRESOLVED" ] && break
  done <<< "$LAST_REVIEWS"

  if [ -n "$COMMON_UNRESOLVED" ]; then
    STAGNANT_ISSUE=$(echo "$COMMON_UNRESOLVED" | head -1)
  fi
fi

# ============================================================
# Trigger 2: New-Issue Velocity
# ============================================================
# 윈도우 이전 review와 윈도우 내 review의 ISSUE 차집합 = 신규 issue 카운트

NEW_ISSUE_COUNT=0
NEW_ISSUE_LIST=""

if [ "$REVIEW_COUNT" -ge "$VELOCITY_PASS_WINDOW" ]; then
  PREV_COUNT=$((REVIEW_COUNT - VELOCITY_PASS_WINDOW))

  # 윈도우 이전 review들의 모든 ISSUE 수집
  PREV_ISSUES=""
  if [ "$PREV_COUNT" -gt 0 ]; then
    PREV_REVIEWS=$(echo "$REVIEW_FILES" | head -n "$PREV_COUNT")
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      ids=$(grep -oE "### ISSUE-[0-9]+" "$f" 2>/dev/null | grep -oE "ISSUE-[0-9]+")
      PREV_ISSUES=$(printf "%s\n%s" "$PREV_ISSUES" "$ids")
    done <<< "$PREV_REVIEWS"
    PREV_ISSUES=$(echo "$PREV_ISSUES" | sort -u | grep -v '^$')
  fi

  # 윈도우 내 review들의 ISSUE
  RECENT_REVIEWS=$(echo "$REVIEW_FILES" | tail -n "$VELOCITY_PASS_WINDOW")
  RECENT_ISSUES=""
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    ids=$(grep -oE "### ISSUE-[0-9]+" "$f" 2>/dev/null | grep -oE "ISSUE-[0-9]+")
    RECENT_ISSUES=$(printf "%s\n%s" "$RECENT_ISSUES" "$ids")
  done <<< "$RECENT_REVIEWS"
  RECENT_ISSUES=$(echo "$RECENT_ISSUES" | sort -u | grep -v '^$')

  # 차집합: 윈도우 내에는 있지만 이전엔 없는 ISSUE
  if [ -n "$RECENT_ISSUES" ]; then
    if [ -n "$PREV_ISSUES" ]; then
      NEW_ISSUE_LIST=$(comm -23 <(echo "$RECENT_ISSUES") <(echo "$PREV_ISSUES") 2>/dev/null)
    else
      NEW_ISSUE_LIST="$RECENT_ISSUES"
    fi
    NEW_ISSUE_COUNT=$(echo "$NEW_ISSUE_LIST" | grep -c '^ISSUE-' 2>/dev/null)
    NEW_ISSUE_COUNT=${NEW_ISSUE_COUNT:-0}
  fi
fi

# ============================================================
# 발동 판정
# ============================================================

TRIGGER_REASON=""

if [ -n "$STAGNANT_ISSUE" ]; then
  TRIGGER_REASON="Same-Issue Stagnation: ${STAGNANT_ISSUE}이(가) 최근 ${STAGNATION_LIMIT}개 review에서 연속 UNRESOLVED. plan amend 또는 접근 재검토 필요."
elif [ "$NEW_ISSUE_COUNT" -ge "$VELOCITY_ISSUE_LIMIT" ]; then
  ISSUE_LIST_STR=$(echo "$NEW_ISSUE_LIST" | tr '\n' ' ' | sed 's/  *$//')
  TRIGGER_REASON="New-Issue Velocity: 최근 ${VELOCITY_PASS_WINDOW}개 review에서 신규 ISSUE ${NEW_ISSUE_COUNT}건 발견 (${ISSUE_LIST_STR}). plan.md 범위 책정 오류 가능성. plan 재작성 또는 cycle split 검토."
fi

# 발동 없으면 통과
[ -z "$TRIGGER_REASON" ] && exit 0

# status.txt를 escalated로 변경
echo "escalated" > "$CURRENT_CYCLE/status.txt"

cat <<EOF
{
  "decision": "block",
  "reason": "Issue-velocity cap 발동. status.txt = escalated로 변경됨. ${TRIGGER_REASON} 사용자 개입 전까지 자동 진행 금지."
}
EOF
