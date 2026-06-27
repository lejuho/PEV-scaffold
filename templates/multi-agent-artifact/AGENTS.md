# AGENTS.md

> 이 파일은 Codex CLI 및 Claude Code 양쪽의 source of truth.
> 워크플로우, 금지 패턴, 사이클 운영 규칙이 모두 여기서 정의된다.
> `.claude/CLAUDE.md`는 이 파일을 reference하고 Claude-specific 추가분만 둔다.

---

## Architecture

> **project-specific 영역** — 다른 프로젝트로 bundle을 옮길 때 이 섹션만 갈아끼운다.
> 아래 placeholder를 실제 stack으로 교체. 비어 있는 상태로는 cycle 진행 금지.

- **Type**: <Web2 | Web3 | Hybrid>
- **Backend**: <Framework + Language + Version> (예: Java Spring Boot 3.x, JDK 17)
- **Frontend**: <Framework + Runtime> (예: Expo React Native, Next.js)
- **Storage**: <DB + Object Storage> (예: PostgreSQL, R2)
- **Auth/Identity**: <Provider> (예: Supabase, Auth0, 자체 JWT)
- **외부 의존**: <주요 third-party API>
- **(Web3인 경우) Chain**: <Network + Toolchain> (예: Solana + Anchor, Base + Foundry)

---

## Conventions

<!-- 프로젝트별 컨벤션이 정해지면 여기 채운다 (네이밍, 라우팅, 응답 포맷 등) -->

---

## Commands

<!-- 자주 쓰는 빌드/테스트/배포 명령어 (./gradlew.bat test 등) -->

---

## Prohibited Patterns

### 금지 — Universal

> 모든 프로젝트에 적용. bundle을 옮겨도 변하지 않는다.

- critical한 파일 임의 수정 금지 (config, migration, lock file, CI 설정)
- 같은 에러 시그니처 2회 재현 시 같은 접근으로 재시도 금지 — Advisor 호출 필수
- plan.md에 없는 scope 추가 금지 — 필요 시 cycle 종료 후 다음 cycle plan에 포함
- Advisor 응답 무시 시 step-NNN.md에 이유 명시 의무 (이유 없는 무시는 anti-pattern)
- review-vN.md의 Codex 작성 본문 수정 금지 — RESOLVED는 파일 끝 append만

### 금지 — Domain-Specific

> 도메인별 금지 패턴은 skill 파일이 source of truth.
> Executor는 작업 종류에 맞는 skill을 로드한 뒤 진행한다.

| 작업 종류 | 참조 skill |
|----------|-----------|
| 클래스 설계, 리팩토링, SOLID | `.claude/skills/design-principles/SKILL.md` |
| Backend (Spring/FastAPI/...) | `.claude/skills/<backend-*>/SKILL.md` |
| Frontend (React/Next/...) | `.claude/skills/<frontend-*>/SKILL.md` |
| 스마트 컨트랙트 (Solidity/Anchor) | `.claude/skills/<contract-*>/SKILL.md` |

해당 skill이 bundle에 없으면 → 새 cycle 진행 전에 skill 추가. 도메인 규칙이 AGENTS.md에 직접 박히지 않는다.

---

## Testing & Verify

<!-- 자동 체크 명령 + 통과 기준. plan.md Sprint Contract에서 cycle별로 재명시. -->

---

## Past Failures → Rules (Hansei)

> 실패/의도와 다른 에러 발생 시 한 줄씩 추가. blameless 원칙 — "누가 실수했다"가 아니라 "이런 패턴이 위험하다"로 기록.

- Cloudflare Access, Tunnel, Caddy, systemd, OAuth/LLM proxy, external API,
  network, or deployment incidents that require multi-step diagnosis or recur
  must be documented in `docs/postmortems/YYYY-MM-DD-<slug>.md` before the work
  is considered complete. Create `docs/postmortems/` when the first qualifying
  incident occurs.
- Apply the same postmortem rule to code debugging when an error signature
  repeats, the same behavior needs more than one corrective patch, a regression
  reopens a fixed bug, or the root cause crosses module/API/DB boundaries.
  Before another fix attempt, search `docs/postmortems/` for the signature and
  affected boundary so an already-failed approach is not repeated.
- Each postmortem records: symptom and impact, relevant timeline/evidence, root
  cause, resolution commands or configuration changes, verification, and a
  prevention/follow-up rule. For code defects, also record the stable error
  signature, affected contract/files, prior fixes that proved insufficient,
  and the regression test added. If automation is impossible, state the exact
  manual verification and why. Keep it blameless and distinguish confirmed
  facts from hypotheses.
- Never include secrets, full tokens, session cookies, OAuth credentials, or
  private key material. Redact identifiers when they are not needed to
  reproduce the diagnosis.
- Trivial typos, immediately corrected one-off command mistakes, and code bugs
  fixed once with an adequate regression test do not need a postmortem. Add the
  durable lesson as one line in this Hansei section; use
  `docs/codebase-map.md` only for navigation or boundary changes, not incident
  narrative.

<!-- 예: -->
<!-- - mock verify 단위 테스트로는 FK constraint violation을 검증할 수 없다. 실제 DB 통합 테스트 필수. -->

---

## Context Discipline

- Before broad repo search, check `docs/codebase-map.md` when it exists and use
  it to narrow the first search/read scope.
- If `docs/codebase-map.md` does not exist, create it before the next
  non-trivial implementation cycle that would otherwise require broad repo
  exploration.
- After implementation changes that add, remove, or move packages, routes,
  services, schemas, migrations, commands, external integrations, or major UI
  surfaces, update `docs/codebase-map.md` in the same cycle.
- Keep `docs/codebase-map.md` as a navigation catalog, not exhaustive prose:
  package responsibilities, key entry points, route/service/schema locations,
  external boundaries, and known “look here first” paths.

---

## Cycle Workflow

### 구조

한 cycle = 한 plan = 한 PR = 한 feature. 사이클 산출물은 `.review/cycle-N/`에 모인다.

> **Step은 implicit**. plan.md의 `Key Changes` 항목들이 사실상 step 역할을 하지만, 별도 commit unit 분해는 강제하지 않는다. Executor가 자연스러운 단위로 진행하며 step마다 Step Advisor를 호출한다. Plan 단위가 너무 커지면(Key Changes 항목 10개 초과) cycle split을 검토한다.

```
Pass 1  Planner (Codex plan mode)  → plan.md 작성
Pass 2  Executor (Sonnet)          → implementation
        └─ step 단위로 진행, step마다 Advisor(Opus) hook 자동 호출
        └─ Advisor 피드백은 advisor-feedback/step-NNN.md에 보존
Pass 3  Cycle Reviewer (Codex)     → review-v1.md
        verdict: BLOCKED | PASS | READY_TO_MERGE

(BLOCKED 시 반복)
Pass 4  Executor                   → review-v1.md 끝에 RESOLVED 섹션 append
Pass 5  Cycle Reviewer             → review-v2.md
...

PASS 도달 시 → status.txt = ready_to_merge
Issue-velocity cap 발동 시 → status.txt = escalated
```

### 역할별 책임 경계

| 역할 | 모델 | 호출 빈도 | 산출물 |
|------|------|----------|--------|
| Planner | Codex plan mode | cycle 시작 시 1회 | `plan.md` |
| Executor | Sonnet | pass별 1회 | 코드 변경 + RESOLVED 섹션 |
| Step Advisor | Opus 4.7 | step마다 hook 자동 | `advisor-feedback/step-NNN.md` |
| Cycle Reviewer | Codex | pass별 1회 | `review-vN.md` |

### Clean-Context Validation

Step Advisor와 Cycle Reviewer는 모두 **별도 세션/sub-agent**로 실행된다. Executor의 message history를 상속받지 않는다.

**Explicit negative instructions** (validator/reviewer 프롬프트에 명시):

- Executor의 reasoning trace, 중간 결정 사항, 시도했던 접근법을 일체 읽지 않는다.
- plan.md의 spec과 git diff(또는 변경된 파일 자체)만 본다.
- "왜 이렇게 구현했는가"가 아니라 "spec에서 거꾸로 추론할 때 이 구현이 맞는가"로 검증한다.

이 강제 격리가 핵심인 이유: validator가 executor의 reasoning을 보면 자기도 모르게 "이미 검토된 결정"으로 받아들여 user instruction의 오해까지 catch할 기회를 잃는다. Spec에서 거꾸로 추론하는 절차가 그 catch를 가능하게 한다.

### Plan-Branch 1:1 매핑

- 각 cycle은 정확히 하나의 git branch와 매핑.
- `plan.md` 첫 섹션에 `Branch:` 라인 필수.
- `plan.md` 첫 섹션에 `Skills:` 라인 필수 (도메인 skill 목록 또는 `none`). 코드 변경이 있는 cycle은 `check-skill-loaded.sh`가 이 선언과 실제 로드를 대조한다.
- Executor의 첫 동작은 현재 브랜치 확인 + 필요시 `git switch`.

### Status 파일

`.review/cycle-N/status.txt`는 다음 중 하나:
- `in_progress` — 사이클 진행 중
- `ready_to_merge` — Cycle Reviewer PASS, PR 가능
- `escalated` — Issue-velocity cap 발동, 사용자 개입 필요

---

## plan.md Template (필수 섹션)

```markdown
# <기능명> 구현 계획

Branch: <feature/...>
Skills: <skill1, skill2 | none>

## Summary
<현재 상태 + 이번 cycle 목표>

## 입력/출력 명세
- 입력: <endpoint, content-type, field, auth, ...>
- 출력:
  - 정상: <응답 형식 + side effect>
  - 실패: <에러 종류별 처리>

## Key Changes
- Frontend: <파일별 변경>
- Backend: <파일별 변경>

## Sprint Contract
- 통과 기준: <검증 가능한 조건들>
- 자동 체크: <test/lint/build 명령>
- 테스트 케이스: <단위/통합/수동>
- gas 한도: <Solidity인 경우, 아니면 N/A>
- slither 통과: <Solidity인 경우, 아니면 N/A>

## 누락된 엣지 케이스 후보 3개
- <range 외 입력, 동시성, 외부 의존 실패 등>

## 더 단순한 대안 1개
<더 빠르지만 trade-off가 있는 접근. 채택하지 않은 이유 명시.>

## Assumptions
<DB 스키마, 외부 API 응답 형식 등 검증 없이 전제하는 사항>

## Review Guidance
### Enumeration 필요 항목
<Cycle Reviewer가 빠짐없이 확인해야 하는 전체 집합>
- 예: User FK 참조 도메인 전체
  - 검색: `rg 'private User|JoinColumn\(name = "user_id"\)' src/main/java/.../domain`
  - 예상 도메인 수: 12개 이상

### 검증 방식 가이드
<Sprint Contract 항목별 verify 가능 수단>
- 예: "FK 에러 없이 완료"
  - mock 단위 테스트로는 **불충분** (실제 FK 제약을 안 탐)
  - `@DataJpaTest` 또는 `@SpringBootTest` 통합 테스트 필수
```

> **Review Guidance 섹션 작성 의무**: Sprint Contract의 각 항목에 대해, (a) 전체 enumeration이 필요한 대상은 명시적으로 grep/rg 명령과 함께 적고, (b) mock으로 충분한지 통합 테스트가 필요한지 항목별로 분류한다. 이게 cycle 횟수를 줄이는 가장 큰 레버.

---

## review-vN.md Convention

### 파일 명명

- v는 review 파일 카운트 (Codex가 review 작성한 횟수).
- 파일 안에서 `Pass N` 라벨은 **사용 금지**. v1/v2/v3 카운팅만.
- 한 cycle 내에서 v는 1부터 순차 증가.

### 파일 구조

```markdown
# Codex Review v<N>

## Verdict
BLOCKED | PASS | READY_TO_MERGE

## Findings
### ISSUE-<N> [HIGH|MEDIUM|LOW] <한 줄 요약>
- 위치: <파일 경로:line>
- 분석: <현재 코드/상태>
- 영향: <Sprint Contract의 어느 항목 미충족>
- 수정 방향: <구체적 가이드>

## Previous Issue Status (v2부터)
- ISSUE-1: RESOLVED | UNRESOLVED | REGRESSION

## Regression Check (v2부터)
<새 변경으로 도입된 회귀 식별>

## Sprint Contract Check
<plan.md Sprint Contract 항목별 1:1 verify>

## Automatic Checks
- <명령>: PASS | FAIL

## Changes Outside Plan
<plan.md에 없던 scope creep 식별>

<!-- RESOLVED-BOUNDARY · 위=Codex immutable, 아래=Executor append-only · check-resolved-immutable.sh가 강제 -->

## RESOLVED (Executor 응답, 파일 끝에 append)

RESOLVED: ISSUE-<N> — <한 줄 요약>
- <적용 내용 bullet>
- <파일별 변경>
자동 체크: compileJava ✅ / test ✅ / spotlessCheck ✅
```

### RESOLVED 섹션 규칙

- Codex 본문과 RESOLVED 사이에 **`RESOLVED-BOUNDARY` 센티넬 주석 한 줄**을 둔다 (`---` 단독 구분선 대신). 센티넬 위 = Codex immutable, 아래 = Executor append-only.
- 센티넬 위 Codex 본문은 **byte 단위로 불변**. `check-resolved-immutable.sh`(Stop hook)가 git HEAD와 대조해 변조를 block한다. `## RESOLVED`를 센티넬 위에 쓰는 것도 block.
- Executor만 센티넬 아래에 작성. Codex review 본문은 수정 금지.
- 센티넬 마커 계약은 `CONTRACT_MARKERS.md`(M-RESOLVED-BOUNDARY)에 고정. 마커 변경 시 그쪽과 훅 정규식을 함께 수정.
- 한 review-vN에는 정확히 한 번의 RESOLVED 응답.
- 다음 Codex review는 새 review-v(N+1).md에 작성.

---

## Advisor Feedback Externalization

### 디렉터리

`.review/cycle-N/advisor-feedback/step-NNN.md` — step 단위로 한 파일.

### 저장 책임

Executor (Sonnet)가 Advisor 호출 직후 직접 파일 작성. hook이 누락 검증만 수행 (Stop hook 시점에 step 카운트 ↔ 파일 개수 일치 확인).

### Format

```markdown
# Step <NNN> — <implementation 요약>

Cycle: <N>
Pass: <N>
Files Changed: <list>

## Advisor Verdict
PASS | NEEDS_REVIEW

## Advisor Feedback
<Opus 응답 그대로. 100단어 이내, 단계 나열>

## Sonnet Response
- 적용: <항목별>
- 무시: <항목> (이유: <왜 user intent/plan과 충돌하는지>)
```

### "무시 + 이유" 필드의 중요성

Communication bridge가 명시화되는 지점. Cycle Reviewer가 사후에 "Advisor가 잡았는데 Executor가 무시한 게 정당했는가"를 verify 가능. 무시 자체는 anti-pattern이 아니지만, **이유 없는 무시**는 anti-pattern.

---

## Issue-Velocity Cap

Hard cap 대신 두 가지 dynamic trigger. 둘 중 하나 발동 시 `status.txt = escalated`.

### Trigger 1: Same-Issue Stagnation

- 조건: 같은 ISSUE-N이 **3 pass 연속 UNRESOLVED**
- 의미: Executor가 동일 issue를 못 풀고 있음
- 조치: 사용자 개입 필요. plan amend 또는 접근 재검토.

### Trigger 2: New-Issue Velocity

- 조건: **5 pass 누적에서 새 issue 3건 이상** 신규 발견
- 의미: plan.md의 범위 책정 오류 가능성
- 조치: plan.md 재작성 또는 cycle split.

### 운영 메모

- 정당한 production 안정화(예: FK enumeration 추가 발견)는 trigger 1/2 모두 안 걸린다.
- threshold는 `.claude/hooks/check-cycle-cap.sh` 안에서 환경 변수로 override 가능.

---

## Cycle Completion Criteria

PR merge 가능 조건:

```
□ status.txt == ready_to_merge
□ 모든 ISSUE-N이 review-vN 최신 버전에서 RESOLVED 상태
□ 자동 체크 (test/lint/build) 전부 PASS
□ Sprint Contract 모든 항목 충족
□ Cycle Reviewer Verdict == READY_TO_MERGE
□ plan.md에 없던 변경사항(scope creep) 0건 또는 정당화 명시
```

---

## Anti-patterns

1. **plan.md mid-cycle 수정** — Issue-velocity cap 발동 후 escalation 경로에서만 허용.
2. **review-vN 본문 수정** — Codex가 작성한 부분은 절대 수정 금지. RESOLVED는 파일 끝 append만.
3. **Advisor 응답 휘발** — step 파일 저장 안 하면 Hansei 추출 불가. hook이 차단.
4. **한국어 inter-agent 통신** — 토큰 비용 2-3배. plan.md/review-vN.md/step-NNN.md는 영어 권장(현재 한국어 운영 중인 부분은 유지하되 신규 cycle부터 점진적 전환 권장).
5. **trivial 작업에 cycle 풀가동** — README 한 줄 수정 같은 작업은 cycle 시스템 우회.
6. **단일 에이전트로 fallback** — "그냥 Sonnet에게 다 시키면 되잖아"는 cycle quality를 무너뜨림. trivial이면 우회, non-trivial이면 cycle 통과.

---

## References

이 시스템의 설계 출처:

- Cognition "Multi-Agents: What's Actually Working" (2026.4.22) — clean-context reviewer
- Anthropic Claude Code 문서 — sub-agent 패턴
- Toyota Production System — Andon cord (2-strike), Hansei, blameless 원칙
- Karpathy CLAUDE.md (Forrest Chang 정리, 2026.1) — 4 행동 원칙
- Crack CLI (`github.com/Royaltyprogram/Crack-CLI`) — Plan-branch 1:1
