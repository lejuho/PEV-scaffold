#!/bin/bash
# check-resolved-immutable.sh — Stop hook
# review-vN.md의 Codex 본문(센티넬 위)이 변조되지 않았는지 강제.
# fail-open 원칙: 검증 불가능한 모든 상황에서 통과.
#
# 배경:
#   "Codex review 본문 절대 수정 금지, RESOLVED는 파일 끝 append만"은 지금까지 순수 명예제였다.
#   훅이 강제하지 못했다. 이 훅이 그 invariant를 enforce한다.
#
# 센티넬 (M-RESOLVED-BOUNDARY, CONTRACT_MARKERS.md 참조):
#   review-vN.md 안에서 'RESOLVED-BOUNDARY'를 포함한 주석 라인.
#   그 라인 위 = Codex immutable / 아래 = Executor append-only.
#
# 검증 로직 (현재 진행 중 cycle의 모든 review-v*.md 대상):
#   1. 센티넬 없음 → SKIP (센티넬 도입 전 파일 호환)
#   2. 센티넬 위 영역에 '## RESOLVED' 출현 → BLOCK (RESOLVED를 경계 위에 작성한 구조 위반)
#   3. 센티넬 위 영역이 git HEAD 버전과 다름 → BLOCK (Codex 본문 변조)
#      - 파일이 HEAD에 없음(미커밋 신규 review) → 비교 불가 → SKIP (fail-open)

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

# 진행 중 cycle 찾기 (status.txt == in_progress) — M-STATUS
CURRENT_CYCLE=""
for status_file in "$REVIEW_DIR"/cycle-*/status.txt; do
  [ ! -f "$status_file" ] && continue
  if grep -q "in_progress" "$status_file" 2>/dev/null; then
    CURRENT_CYCLE=$(dirname "$status_file")
    break
  fi
done

[ -z "$CURRENT_CYCLE" ] && exit 0

# 센티넬 위 영역만 출력 (센티넬 라인 자체와 그 아래는 제외)
above_sentinel() {
  awk '/RESOLVED-BOUNDARY/{exit} {print}' "$1" 2>/dev/null
}
above_sentinel_stdin() {
  awk '/RESOLVED-BOUNDARY/{exit} {print}' 2>/dev/null
}

VIOLATION=""

for f in "$CURRENT_CYCLE"/review-v*.md; do
  [ ! -f "$f" ] && continue

  # 1. 센티넬 없으면 검증 불가 → SKIP
  if ! grep -q "RESOLVED-BOUNDARY" "$f" 2>/dev/null; then
    continue
  fi

  WORK_ABOVE=$(above_sentinel "$f")

  # 2. 구조 위반: 센티넬 위에 '## RESOLVED' 출현
  if echo "$WORK_ABOVE" | grep -qE "^## RESOLVED" 2>/dev/null; then
    VIOLATION="${f##*/}: '## RESOLVED' 섹션이 RESOLVED-BOUNDARY 센티넬 *위*(Codex immutable 영역)에 있음. 센티넬 아래로 옮길 것."
    break
  fi

  # 3. 변조 검사: 센티넬 위 영역 vs git HEAD
  REL="${f#$GIT_ROOT/}"
  HEAD_CONTENT=$(git -C "$GIT_ROOT" show "HEAD:$REL" 2>/dev/null)
  # 파일이 HEAD에 없으면(미커밋 신규 review) 비교 불가 → SKIP
  [ -z "$HEAD_CONTENT" ] && continue

  HEAD_ABOVE=$(echo "$HEAD_CONTENT" | above_sentinel_stdin)

  if [ "$WORK_ABOVE" != "$HEAD_ABOVE" ]; then
    VIOLATION="${f##*/}: RESOLVED-BOUNDARY 센티넬 위 Codex 본문이 커밋된 버전과 다름. Codex review 본문은 immutable. 변경을 되돌리고 RESOLVED는 센티넬 아래에만 append할 것. (diff: git diff HEAD -- $REL)"
    break
  fi
done

# 위반 없으면 통과
[ -z "$VIOLATION" ] && exit 0

cat <<EOF
{
  "decision": "block",
  "reason": "RESOLVED 경계 invariant 위반. ${VIOLATION} 규칙: AGENTS.md 'review-vN.md Convention' / 'RESOLVED 섹션 규칙' 참조. 센티넬 계약: CONTRACT_MARKERS.md M-RESOLVED-BOUNDARY."
}
EOF
