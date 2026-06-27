#!/bin/bash
# check-skill-loaded.sh — Stop hook
# plan.md의 "Skills:" 선언 ↔ 실제 skill 로드 일치 검증.
# fail-open 원칙: 검증 불가능한 모든 상황에서 통과.
#
# 설계 (CONTRACT_MARKERS.md M-PLAN-SKILLS / M-SKILL-LOAD):
#   - Planner가 plan.md 상단에 "Skills: <skill1>, <skill2>" 또는 "Skills: none" 선언.
#   - Executor는 각 skill 로드 직전 "[[SKILL:<name>]]" 마커를 출력한 뒤 SKILL.md를 읽는다.
#   - 이 훅이 (a) 선언된 skill이 실제 존재하는 디렉터리인지(오타/누락),
#                (b) transcript에 [[SKILL:<name>]] 로드 흔적이 있는지를 검사.
#
# 왜 SKILL.md 경로를 grep하지 않는가:
#   "skills/design-principles/SKILL.md" 같은 경로 문자열은 AGENTS.md 매핑 표에도 그대로 들어 있다.
#   그 문서가 컨텍스트에 읽히면 transcript에 섞여 "로드한 적 없는데 로드한 것처럼" 오탐이 난다
#   (M-ADVISOR-CALL과 동일한 충돌). 그래서 *설명에는 등장하지 않는* 별도 행위 마커
#   "[[SKILL:<name>]]"를 쓴다. 설명 문서의 placeholder "[[SKILL:<skill-name>]]"는
#   실제 "[[SKILL:backend-spring]]"과 매치되지 않으므로 충돌하지 않는다.

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0

STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[ "$STOP_HOOK_ACTIVE" = "true" ] && exit 0

TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)

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

PLAN="$CURRENT_CYCLE/plan.md"
[ ! -f "$PLAN" ] && exit 0

# 코드 변경이 없으면 skill 작업 안 한 세션으로 보고 통과 (save-advisor-feedback.sh와 동일 가드)
DIFF_FILES=$(git -C "$GIT_ROOT" diff --name-only HEAD 2>/dev/null)
CACHED_FILES=$(git -C "$GIT_ROOT" diff --cached --name-only 2>/dev/null)
if [ -z "$DIFF_FILES" ] && [ -z "$CACHED_FILES" ]; then
  exit 0
fi

# Skills: 선언 라인 추출 (M-PLAN-SKILLS)
SKILLS_LINE=$(grep -iE "^Skills:" "$PLAN" 2>/dev/null | head -1)

if [ -z "$SKILLS_LINE" ]; then
  cat <<EOF
{
  "decision": "block",
  "reason": "plan.md에 'Skills:' 선언 라인이 없음. 코드 변경이 있는 cycle은 어떤 도메인 skill이 필요한지(또는 'Skills: none') 명시해야 한다. plan.md 상단 Branch: 근처에 'Skills: <skill1>, <skill2>' 또는 'Skills: none' 추가. 형식: AGENTS.md 'plan.md Template' 참조. 마커 계약: CONTRACT_MARKERS.md M-PLAN-SKILLS."
}
EOF
  exit 0
fi

# 콜론 뒤 파싱, 콤마/공백 분리
DECLARED=$(echo "$SKILLS_LINE" | sed 's/^[Ss][Kk][Ii][Ll][Ll][Ss]:[[:space:]]*//' | tr ',' ' ')

# "none" → 명시적 무-skill cycle, 통과
NORM=$(echo "$DECLARED" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
[ "$NORM" = "none" ] && exit 0

# transcript tail (없으면 로드 검증 불가 → 존재 검증만)
RECENT=""
CAN_CHECK_LOAD=false
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
  RECENT=$(tail -c 200000 "$TRANSCRIPT" 2>/dev/null)
  [ -n "$RECENT" ] && CAN_CHECK_LOAD=true
fi

# skill 디렉터리 루트 (둘 다 지원)
SKILL_ROOTS=("$GIT_ROOT/.claude/skills" "$GIT_ROOT/agents/skills")

UNKNOWN_SKILL=""
MISSING_LOAD=""

for s in $DECLARED; do
  [ -z "$s" ] && continue
  # advisor는 force-advisor-check.sh가 별도 강제 — 선언돼도 여기선 검사 생략
  [ "$s" = "advisor" ] && continue

  # (a) 존재 검증 (filesystem이 source of truth)
  found_dir=false
  for root in "${SKILL_ROOTS[@]}"; do
    [ -d "$root/$s" ] && found_dir=true && break
  done
  if [ "$found_dir" = false ]; then
    UNKNOWN_SKILL="$UNKNOWN_SKILL $s"
    continue
  fi

  # (b) 로드 검증 — transcript에 [[SKILL:<name>]] (M-SKILL-LOAD)
  if [ "$CAN_CHECK_LOAD" = true ]; then
    if ! echo "$RECENT" | grep -qF "[[SKILL:${s}]]" 2>/dev/null; then
      MISSING_LOAD="$MISSING_LOAD $s"
    fi
  fi
done

REASON=""
if [ -n "$UNKNOWN_SKILL" ]; then
  REASON="존재하지 않는 skill 선언:${UNKNOWN_SKILL} (오타이거나 bundle에 skill 추가 필요 — AGENTS.md 'Prohibited Patterns' 참조). "
fi
if [ -n "$MISSING_LOAD" ]; then
  REASON="${REASON}선언했으나 로드 흔적([[SKILL:<name>]]) 없는 skill:${MISSING_LOAD} (작업 전 마커 출력 후 SKILL.md 로드, 또는 plan.md Skills:에서 제거). "
fi

[ -z "$REASON" ] && exit 0

cat <<EOF
{
  "decision": "block",
  "reason": "Skill 선언/로드 불일치. ${REASON}규칙: CLAUDE.md 'Skill 로드 규칙' / AGENTS.md 'plan.md Template'. 마커 계약: CONTRACT_MARKERS.md M-PLAN-SKILLS, M-SKILL-LOAD."
}
EOF
