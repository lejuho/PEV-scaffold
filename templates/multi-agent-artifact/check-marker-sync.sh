#!/bin/bash
# check-marker-sync.sh — Contract marker drift detector (CI / pre-commit)
#
# 목적: 문서 포맷 ↔ 훅 정규식의 어긋남을 커밋 단계에서 잡는다.
#   훅은 fail-open이라 마커가 어긋나도 에러 없이 조용히 죽는다. 이 테스트는 그 침묵을 깬다.
#
# 두 방향 모두 검사:
#   (1) sample ↔ regex : 문서가 규정한 canonical 예시가 regex에 매치되는가?
#                        (문서 포맷만 바꾸고 registry/훅을 안 고친 경우 검출)
#   (2) regex ↔ hook   : 그 regex의 distinctive signature가 실제 훅 소스에 있는가?
#                        (훅 정규식만 바꾸고 registry를 안 고친 경우 검출 — 예: UNRESOLVED 버그 회귀)
#
# 이건 fail-open 훅이 아니라 **테스트**다. 불일치/예상 못한 상황은 FAIL(비0 종료)로 보고한다.
# (단, 소스가 번들에 없는 훅은 SKIP — FAIL 아님)
#
# 사용:
#   bash check-marker-sync.sh
#   HOOKS_DIR=path/to/hooks bash check-marker-sync.sh

set -o pipefail

# 훅 디렉터리 결정: env override > git root의 .claude/hooks > 스크립트와 같은 디렉터리
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -n "$HOOKS_DIR" ]; then
  HD="$HOOKS_DIR"
else
  GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
  if [ -n "$GIT_ROOT" ] && [ -d "$GIT_ROOT/.claude/hooks" ]; then
    HD="$GIT_ROOT/.claude/hooks"
  else
    HD="$SCRIPT_DIR"
  fi
fi

PASS=0
FAIL=0
SKIP=0

green() { printf '\033[32m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }
yellow(){ printf '\033[33m%s\033[0m' "$1"; }

# assert_match <id> <sample> <regex>
assert_match() {
  local id="$1" sample="$2" regex="$3"
  if printf '%s' "$sample" | grep -qE "$regex"; then
    echo "  [$(green PASS)] $id  sample↔regex : '$sample' =~ /$regex/"
    PASS=$((PASS+1))
  else
    echo "  [$(red FAIL)] $id  sample↔regex : '$sample' !~ /$regex/  (문서 포맷과 regex 불일치)"
    FAIL=$((FAIL+1))
  fi
}

# assert_no_match <id> <sample> <regex>   (회귀 가드용 — 옛 버그 패턴이 부활하면 잡힘)
assert_no_match() {
  local id="$1" sample="$2" regex="$3"
  if printf '%s' "$sample" | grep -qE "$regex"; then
    echo "  [$(red FAIL)] $id  regression  : 옛 버그 패턴 /$regex/ 이 여전히 매치됨 — 회귀!"
    FAIL=$((FAIL+1))
  else
    echo "  [$(green PASS)] $id  regression  : 옛 버그 패턴 /$regex/ 비매치 (정상)"
    PASS=$((PASS+1))
  fi
}

# assert_in_hook <id> <hookfile> <signature>
assert_in_hook() {
  local id="$1" hook="$2" sig="$3"
  local path="$HD/$hook"
  if [ ! -f "$path" ]; then
    echo "  [$(yellow SKIP)] $id  regex↔hook  : $hook 소스 없음 (번들 미포함)"
    SKIP=$((SKIP+1))
    return
  fi
  if grep -qF "$sig" "$path"; then
    echo "  [$(green PASS)] $id  regex↔hook  : '$sig' ∈ $hook"
    PASS=$((PASS+1))
  else
    echo "  [$(red FAIL)] $id  regex↔hook  : '$sig' ∉ $hook  (훅 정규식이 registry에서 드리프트)"
    FAIL=$((FAIL+1))
  fi
}

echo "Contract marker sync — hooks dir: $HD"
echo

echo "M-ISSUE-STATUS (check-cycle-cap.sh Trigger 1)"
assert_match    "M-ISSUE-STATUS" "- ISSUE-1: UNRESOLVED" "ISSUE-[0-9]+:[[:space:]]*(UNRESOLVED|REGRESSION)"
assert_match    "M-ISSUE-STATUS" "- ISSUE-3: REGRESSION" "ISSUE-[0-9]+:[[:space:]]*(UNRESOLVED|REGRESSION)"
assert_no_match "M-ISSUE-STATUS" "- ISSUE-1: UNRESOLVED" "UNRESOLVED ISSUE-[0-9]+"
assert_in_hook  "M-ISSUE-STATUS" "check-cycle-cap.sh" 'ISSUE-[0-9]+:[[:space:]]*(UNRESOLVED|REGRESSION)'
echo

echo "M-ISSUE-HEADER (check-cycle-cap.sh Trigger 2)"
assert_match   "M-ISSUE-HEADER" "### ISSUE-1 [HIGH] FK not enforced" "### ISSUE-[0-9]+"
assert_in_hook "M-ISSUE-HEADER" "check-cycle-cap.sh" '### ISSUE-[0-9]+'
echo

echo "M-ADVISOR-CALL (save-advisor-feedback.sh)"
ADV_RE='(Approach check|Completion check|Loop break):[[:space:]]*[^[:space:]`[]'
assert_match    "M-ADVISOR-CALL" "Approach check: UserService, FK 경계" "$ADV_RE"
assert_match    "M-ADVISOR-CALL" "Completion check: Foo.java, 회귀 우려" "$ADV_RE"
assert_match    "M-ADVISOR-CALL" "Loop break: NPE at line 42, 시도 3개" "$ADV_RE"
# 충돌 가드: CLAUDE.md 템플릿 행("Approach check: [모듈명]...")은 카운트되면 안 됨
assert_no_match "M-ADVISOR-CALL" "Approach check: [모듈명], [핵심 판단 지점 2-3개]" "$ADV_RE"
assert_in_hook  "M-ADVISOR-CALL" "save-advisor-feedback.sh" '[^[:space:]\`[]'
assert_in_hook  "M-ADVISOR-CALL" "force-advisor-check.sh" '[^[:space:]\`[]'
echo

echo "M-STATUS (status.txt enum)"
assert_match   "M-STATUS" "in_progress"     "^(in_progress|ready_to_merge|escalated)$"
assert_match   "M-STATUS" "ready_to_merge"  "^(in_progress|ready_to_merge|escalated)$"
assert_match   "M-STATUS" "escalated"       "^(in_progress|ready_to_merge|escalated)$"
assert_in_hook "M-STATUS"  "check-cycle-cap.sh" "in_progress"
assert_in_hook "M-STATUS"  "check-cycle-cap.sh" "escalated"
echo

echo "M-RESOLVED-BOUNDARY / M-RESOLVED-SECTION (check-resolved-immutable.sh)"
assert_match   "M-RESOLVED-BOUNDARY" "<!-- RESOLVED-BOUNDARY · 위=immutable -->" "RESOLVED-BOUNDARY"
assert_match   "M-RESOLVED-SECTION"  "## RESOLVED" "^## RESOLVED"
assert_in_hook "M-RESOLVED-BOUNDARY" "check-resolved-immutable.sh" "RESOLVED-BOUNDARY"
echo

echo "M-PLAN-SKILLS / M-SKILL-LOAD (check-skill-loaded.sh)"
assert_match    "M-PLAN-SKILLS" "Skills: backend-spring, contract-solidity" "^Skills:"
assert_match    "M-PLAN-SKILLS" "Skills: none" "^Skills:"
assert_match    "M-SKILL-LOAD"  "[[SKILL:backend-spring]]" "\[\[SKILL:backend-spring\]\]"
# 충돌 가드: skill 경로 문자열은 [[SKILL:...]] 마커와 매치되면 안 된다 (문서 오탐 방지의 핵심)
assert_no_match "M-SKILL-LOAD"  ".claude/skills/backend-spring/SKILL.md" "\[\[SKILL:backend-spring\]\]"
assert_in_hook  "M-PLAN-SKILLS" "check-skill-loaded.sh" "^Skills:"
assert_in_hook  "M-SKILL-LOAD"  "check-skill-loaded.sh" "[[SKILL:"
echo

echo "----------------------------------------"
echo "PASS=$PASS  FAIL=$FAIL  SKIP=$SKIP"
if [ "$FAIL" -gt 0 ]; then
  echo "$(red 'DRIFT DETECTED') — 위 FAIL 항목의 문서/훅/registry를 동기화하라. CONTRACT_MARKERS.md 참조."
  exit 1
fi
echo "$(green 'all markers in sync')"
exit 0
