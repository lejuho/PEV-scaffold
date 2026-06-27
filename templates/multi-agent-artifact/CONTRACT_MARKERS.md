# CONTRACT_MARKERS.md

> **훅이 의존하는 모든 문자열의 single source of truth.**
> bash 훅은 XML 트리를 파싱하지 못한다 — `grep -oE`로 한 줄을 긁는 게 전부다.
> 그래서 이 시스템의 "기계가 읽는 경계"는 태그가 아니라 **정규화된 라인 마커(sentinel)** 다.
> 문서(마커 생산자)와 훅(마커 소비자)이 따로 진화하면 훅이 **에러 없이 조용히 죽는다**
> (fail-open). 그 드리프트를 막기 위해 마커를 여기 한 곳에 못 박고, `check-marker-sync.sh`가
> 문서 포맷 ↔ 훅 정규식의 일치를 검사한다.

## 동기화 규칙 (필수)

- 이 표의 마커를 바꾸면 **같은 PR에서** (a) 해당 훅의 정규식, (b) AGENTS.md/CLAUDE.md의
  포맷 예시를 함께 수정한다.
- 마커를 새로 추가하면 이 표 + `check-marker-sync.sh`의 테스트 케이스에 동시에 추가한다.
- `check-marker-sync.sh`를 pre-commit에 등록해 드리프트를 커밋 단계에서 차단한다 (아래 "pre-commit 연동").

## 마커 표

| ID | 마커 (정확한 형식) | 정규식 | 생산자 (문서/행위) | 소비자 (훅) |
|----|-------------------|--------|-------------------|------------|
| **M-STATUS** | `in_progress` / `ready_to_merge` / `escalated` | 원자값 (한 토큰, status.txt 전체) | `.review/cycle-N/status.txt` | check-cycle-cap.sh, check-context-budget.sh, save-advisor-feedback.sh, check-resolved-immutable.sh |
| **M-ISSUE-HEADER** | `### ISSUE-N [SEV] <요약>` | `### ISSUE-[0-9]+` | review-vN.md Findings | check-cycle-cap.sh (Trigger 2) |
| **M-ISSUE-STATUS** | `- ISSUE-N: UNRESOLVED` (또는 `RESOLVED`/`REGRESSION`) | `ISSUE-[0-9]+:[[:space:]]*(UNRESOLVED\|REGRESSION)` | review-vN.md "Previous Issue Status" | check-cycle-cap.sh (Trigger 1) |
| **M-ADVISOR-CALL** | `Approach check:` / `Completion check:` / `Loop break:` | `(Approach check\|Completion check\|Loop break):[[:space:]]*[^[:space:]\`[]` | Executor가 Advisor 호출 시 (transcript) | save-advisor-feedback.sh, force-advisor-check.sh |
| **M-STEP-FILE** | `step-NNN.md` | `step-*.md` (glob) | `.review/cycle-N/advisor-feedback/` | save-advisor-feedback.sh |
| **M-RESOLVED-BOUNDARY** | `<!-- RESOLVED-BOUNDARY ... -->` | `RESOLVED-BOUNDARY` | review-vN.md (Codex 본문 ↔ Executor RESOLVED 경계) | check-resolved-immutable.sh |
| **M-RESOLVED-SECTION** | `## RESOLVED` | `^## RESOLVED` | review-vN.md (Executor append) | check-resolved-immutable.sh (경계 위 출현 시 위반) |
| **M-PLAN-SKILLS** | `Skills: <s1, s2>` 또는 `Skills: none` | `^Skills:` (대소문자 무시) | plan.md 첫 섹션 (Planner 선언) | check-skill-loaded.sh |
| **M-SKILL-LOAD** | `[[SKILL:<name>]]` | `\[\[SKILL:<name>\]\]` (고정 문자열 grep -F) | Executor가 skill 로드 시 (transcript) | check-skill-loaded.sh |

## 알려진 충돌 — M-ADVISOR-CALL

`Approach check:` / `Completion check:` / `Loop break:` 문자열은 **CLAUDE.md 본문**("Step Advisor 호출 →
호출 시점" 표)에도 그대로 적혀 있다. CLAUDE.md가 컨텍스트에 읽혀 transcript에 그 설명 텍스트가
섞이면, `save-advisor-feedback.sh`의 호출 카운트가 부풀어 **거짓 "step 파일 누락" block**이 날 수 있다.

- **현재 완화(배포됨)**: 정규식에 `:[[:space:]]*[^[:space:]\`[]` 가드를 추가해, 콜론 뒤 첫 실문자가
  `[`인 행(CLAUDE.md 템플릿 `Approach check: [모듈명]...`)을 카운트에서 제외한다. 원본 bash의
  과대카운트(문서 텍스트까지 셈)는 이걸로 해소.
- **잔존 취약성**: 가드는 "실제 호출은 `[`로 시작하지 않는다"를 전제한다. Executor가 호출을
  `[모듈명]`처럼 대괄호로 시작하면 실제 호출도 제외돼 과소카운트(파일 누락 미검출, fail-safe 방향).
- **권장 해결(별도 작업)**: 실제 호출에만 쓰는 구별된 토큰(예: `[[ADVISOR-CALL:approach]]`)을 도입하고
  설명 문서에는 쓰지 않는다. 그러면 M-ADVISOR-CALL의 생산자가 "행위"로 한정돼 충돌이 완전히 사라진다.
  (도입 시 이 표와 save-advisor-feedback.sh / force-advisor-check.sh 정규식, CLAUDE.md 호출 형식을 동시 수정.)
  → **이 패턴의 선례**: M-SKILL-LOAD(`[[SKILL:<name>]]`)가 정확히 이 방식으로 설계됐다. skill 경로
  문자열이 AGENTS.md 매핑 표에도 있어 경로 grep은 오탐을 내므로, 설명에 등장하지 않는 행위 전용
  토큰을 썼다. M-ADVISOR-CALL도 동일하게 마이그레이션하면 된다.

## 번들 내 훅 소스 현황

이전엔 아래 훅들의 소스가 번들에 없었으나, 이제 모두 bash로 포함됨:

- `force-advisor-check.sh` — M-ADVISOR-CALL 소비 (`Completion check:` 가드 정규식). 포함 ✓
- `track-failures.sh` — 같은 에러 시그니처 2회 → Loop break 강제. 마커 계약 의존 없음(임시 로그 기반). 포함 ✓
- `block-dangerous.sh`, `auto-format.sh` — 마커 계약 의존 없음. 포함 ✓

`check-marker-sync.sh`는 파일이 있을 때 검사하고, 없으면 SKIP으로 보고한다 (FAIL 아님).

## pre-commit 연동

`.pre-commit-config.yaml`에 로컬 훅으로 추가 (이미 다른 훅이 있으면 hooks 배열에 머지):

```yaml
- repo: local
  hooks:
    - id: marker-sync
      name: contract marker sync
      entry: bash .claude/hooks/check-marker-sync.sh
      language: system
      pass_filenames: false
      always_run: true
```
