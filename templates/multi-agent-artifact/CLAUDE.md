# CLAUDE.md

> AGENTS.md를 먼저 읽어라. 이 파일은 Claude Code-specific 추가분만 담는다.
> 워크플로우, 금지 패턴, 사이클 운영의 source of truth는 `/AGENTS.md`.

---

## Claude Code의 역할

Claude Code (Sonnet)는 cycle 안에서 **Executor**로 동작한다. 즉:

- Pass 2/4/6/... 에서 호출됨
- plan.md의 Sprint Contract를 만족하는 코드를 작성
- step 단위로 implementation 진행, step마다 Step Advisor 호출
- Codex review에서 BLOCKED 받은 경우 review-vN.md 끝에 RESOLVED 섹션 append

Claude Code는 **Planner** 또는 **Cycle Reviewer** 역할을 수행하지 않는다. 이 두 역할은 Codex가 담당.

---

## Context Discipline

Executor는 context를 **preemptive하게 채우지 않는다.** Just-in-time retrieval 원칙.
- Follow `AGENTS.md` Context Discipline, including `docs/codebase-map.md`
  creation/update rules.

### 규칙

- **No preemptive read** — CLAUDE.md/AGENTS.md 외에는 시작 시점에 어떤 파일도 미리 읽지 않는다.
- **Glob/grep first** — 파일이 필요해지면 먼저 `glob`/`rg`로 위치 파악, 그 다음 read.
- **Bounded read** — plan.md `Key Changes`의 `Files` 목록에 명시된 파일만 read. 그 외는 grep 후 필요한 부분만.
- **5-file halt rule** — 한 step 안에서 read한 파일이 5개를 초과하면 즉시 halt + report. commit unit이 너무 큰 신호.
- **25% budget** — 전체 cycle 동안 context usage가 모델 capacity의 25%를 넘으면 halt + report. (200k 모델 기준 50k 토큰, 1M 모델 기준 250k 토큰)

### 25% rule이 중요한 이유

Context Rot — context가 길어질수록 모델의 의사결정 품질이 떨어진다. 200k 윈도우가 있어도 50k부터는 정확도가 눈에 띄게 감소한다는 게 measured 결과. 큰 컨텍스트가 곧 좋은 컨텍스트가 아니다.

### Halt 시 보고 형식

```
HALT: Context budget exceeded (or 5-file rule)
- Cycle: N
- Step: <짧은 설명>
- 읽은 파일: <목록>
- 예상 원인: <commit unit 분해 필요 / plan.md Files 누락 / dependency 깊이 과다>
- 권장 조치: <plan.md amend / cycle split / step 재정의>
```

→ status.txt = `escalated`로 변경하고 사용자 개입 요청.

---

## Step Advisor 호출

### 호출 시점

| 시점 | 형식 | 의무 |
|------|------|------|
| 새 모듈/기능 작업 시작 직전 | `Approach check: [모듈명], [핵심 판단 지점 2-3개]` | 필수 |
| 작업 단위(step) 완료 직후 | `Completion check: [변경 파일], [회귀 우려 지점 2-3개]` | 필수 |
| 같은 에러 2회 재현 시 | `Loop break: [에러 시그니처], [시도한 것 3개], [근본 원인 가설]` | 자동 강제 (track-failures.sh) |

### 호출 방식

Skill("advisor") 로드 후 Agent tool로 위임:

```
Agent({
  subagent_type: "general-purpose",
  model: "opus",
  description: "Advisor check",
  prompt: "<Approach/Completion/Loop break 질문 그대로>"
})
```

응답 제약: 100단어 이내, 단계 나열 (산문 금지).

### 응답 처리

응답 받은 직후 `.review/cycle-N/advisor-feedback/step-NNN.md`에 저장. 형식은 AGENTS.md의 "Advisor Feedback Externalization" 섹션 참조.

**"무시" 결정 시 이유 명시 의무.** Communication bridge가 명시화되는 지점.

---

## Skill 로드 규칙

작업 시작 전 관련 skill 확인:

| 작업 종류 | 로드할 skill 패턴 |
|----------|-----------------|
| 클래스 설계, 리팩토링, SOLID 적용 | `design-principles` |
| Backend 작업 (controller/service/repository) | `backend-*` (예: `backend-spring`, `backend-fastapi`) |
| Frontend 작업 (component/page) | `frontend-*` (예: `frontend-react`, `frontend-next`) |
| 스마트 컨트랙트 작업 | `contract-*` (예: `contract-solidity`, `contract-anchor`) |
| 아키텍처/구현 판단 | `advisor` (자동) |

여러 skill이 해당되면 모두 로드. skill 내부의 placeholder(`<Entity>`, `<parentEntityId>` 등)는 작업 컨텍스트에 맞게 치환.

bundle에 해당 skill 파일이 없으면 → cycle 진행 전에 추가. AGENTS.md "Prohibited Patterns" 섹션 참조.

### 선언 ↔ 로드 계약

skill 선택을 암묵적 판단에 맡기지 않고 **계약화**한다:

1. **선언**: Planner가 plan.md 첫 섹션 `Skills:` 라인에 이번 cycle이 쓸 도메인 skill을 명시한다 (`Skills: backend-spring, contract-solidity` 또는 `Skills: none`). `advisor`는 자동이라 적지 않아도 된다.
2. **로드 마커**: Executor는 각 skill을 로드하기 직전 **`[[SKILL:<skill-name>]]` 마커를 한 줄 출력**한 뒤 해당 SKILL.md를 읽는다. 예: `[[SKILL:backend-spring]]`.
3. **검증**: `check-skill-loaded.sh`(Stop hook)가 코드 변경이 있는 cycle에서 (a) 선언된 skill이 실제 존재하는 디렉터리인지, (b) 각 선언 skill의 `[[SKILL:...]]` 로드 마커가 transcript에 있는지 대조하고, 불일치 시 block한다.

> 왜 마커를 따로 두는가: SKILL.md 경로 문자열은 AGENTS.md 매핑 표에도 들어 있어, 문서가 컨텍스트에 읽히면 "로드한 적 없는데 로드한 것처럼" 보이는 오탐이 난다. `[[SKILL:<name>]]`는 설명 문서에 그대로 등장하지 않는 행위 전용 마커라 그 충돌을 피한다. 마커 계약: `CONTRACT_MARKERS.md` M-PLAN-SKILLS, M-SKILL-LOAD.

---

## Hook 의존성

다음 hook들이 작동 중. Claude Code 종료/에러/도구 호출 시 자동 발동:

| Hook | 시점 | 역할 |
|------|------|------|
| `force-advisor-check.sh` | Stop | Completion check 호출 확인. 누락 시 block. |
| `track-failures.sh` | PostToolUse(Bash) | 같은 에러 시그니처 2회째 발견 시 Loop break 강제. |
| `save-advisor-feedback.sh` | Stop | step-NNN.md 파일 ↔ Advisor 호출 횟수 일치 확인. |
| `check-resolved-immutable.sh` | Stop | review-vN.md의 `RESOLVED-BOUNDARY` 센티넬 위 Codex 본문 변조 시 block. |
| `check-skill-loaded.sh` | Stop | plan.md `Skills:` 선언과 실제 `[[SKILL:...]]` 로드 마커 불일치 시 block. |
| `check-cycle-cap.sh` | Stop | Issue-velocity cap 발동 시 status.txt = escalated. |

**Fail-open 원칙**: 모든 hook은 jq 없음/파일 없음/JSON 파싱 실패 시 통과. 시스템을 막지 않는다.

---

## Cycle 진입 시 첫 동작

새 cycle을 시작하거나 BLOCKED 응답을 받았을 때:

1. `.review/cycle-N/plan.md` 읽기
2. `Branch:` 라인 확인 후 `git branch --show-current`와 비교, 필요시 `git switch`
3. `Skills:` 라인 확인. `none`이 아니면, 첫 implementation 진입 전에 각 skill을 `[[SKILL:<name>]]` 마커 출력 후 로드. (선언 누락/오타/미로드는 Stop 시 `check-skill-loaded.sh`가 block)
4. `.review/cycle-N/` 안의 모든 review-v*.md 읽기 (최신 v 기준 RESOLVED 미적용 issue 확인)
5. 가장 최신 review-vN.md의 BLOCKED issue 목록 추출
6. **Communication Bridge** — implementation 진입 전 각 issue를 plan.md와 대조:
   - 이 issue가 plan.md의 Summary/Sprint Contract와 정합하는가?
   - user intent와 충돌하지 않는가? (예: scope 확장 요구)
   - 다른 issue 해결과 충돌하지 않는가?
   - 결과로 각 issue를 **APPLY / DEFER / REJECT** 중 하나로 분류
7. APPLY 항목만 RESOLVED 대상으로 설정. DEFER/REJECT는 RESOLVED 섹션에 이유와 함께 명시
8. Approach check (Advisor) → implementation 시작

### Communication Bridge 출력 형식

review-vN.md 끝의 RESOLVED 섹션에 분류 결과를 포함:

```markdown
## RESOLVED

### Issue Classification
- ISSUE-1: APPLY
- ISSUE-2: REJECT (이유: plan.md Sprint Contract의 "단순한 대안" 채택 결정과 충돌. scope 확장.)
- ISSUE-3: DEFER (이유: 본 cycle 범위 외. 다음 cycle plan에 포함 예정.)

### Applied
RESOLVED: ISSUE-1 — <한 줄 요약>
- <변경 내용>
자동 체크: ...
```

이게 빠지면 다음 Codex review에서 같은 issue를 또 제기하거나, executor가 silent하게 무시한 것으로 오인된다. **APPLY가 아닌 분류는 반드시 이유 명시.**

---

## review-vN.md RESOLVED 작성 규칙

review-vN.md 본문(Codex 작성분)은 **절대 수정하지 않는다.** 응답은 `RESOLVED-BOUNDARY` 센티넬 아래에 append:

```markdown
<기존 Codex 본문>

<!-- RESOLVED-BOUNDARY · 위=Codex immutable, 아래=Executor append-only · check-resolved-immutable.sh가 강제 -->

## RESOLVED

RESOLVED: ISSUE-<N> — <짧은 요약>
- <적용 내용>
- <파일별 변경>
자동 체크: compileJava ✅ / test ✅ / spotlessCheck ✅
```

센티넬 위 Codex 본문을 한 글자라도 바꾸거나 `## RESOLVED`를 센티넬 위에 쓰면 `check-resolved-immutable.sh`(Stop hook)가 block한다. 센티넬 계약: `CONTRACT_MARKERS.md` M-RESOLVED-BOUNDARY.

여러 issue 동시 해결 시 RESOLVED 항목을 bullet로 나열. UNRESOLVED 상태로 두는 경우 그 이유를 별도 섹션에 명시 — 다음 Codex가 그 결정의 정당성을 verify 가능하게.

---

## Anti-patterns (Claude Code specific)

1. **Codex review 본문 수정** — review-vN.md의 Findings 섹션을 절대 수정하지 않는다. RESOLVED는 append only.
2. **Advisor 응답 부분 적용 후 step 파일 저장 누락** — `save-advisor-feedback.sh`가 block. 매 Advisor 호출 직후 저장.
3. **plan.md를 implementation 중 수정** — Issue-velocity cap → escalation 경로에서만 허용. 직접 수정 금지.
4. **branch 미확인 implementation** — Branch invariant 위반 시 commit이 엉뚱한 브랜치에 쌓임. cycle 진입 시 강제 확인.
5. **Trivial 작업에 Advisor 호출 남용** — typo 수정, comment 추가 같은 작업은 Advisor 호출 없이 진행. Hook이 차단하지 않으면 우회 가능.

---

## Implementation Style

- Add code comments only when they explain non-obvious intent, invariants,
  failure-mode boundaries, external API quirks, or why a simple-looking approach
  is intentionally avoided.
- Do not add comments that restate what the code already says.
- Prefer clear names, small functions, and tests over explanatory comments.
- If a comment is added during implementation, keep it short and tied to a
  concrete maintenance risk.
- Comment-only edits are trivial work and do not require Advisor unless they
  change behavior, scope, or architecture.

---

## 참고

이 파일에 없는 모든 규칙은 `/AGENTS.md`에서 정의됨. 충돌 시 AGENTS.md가 우선.
