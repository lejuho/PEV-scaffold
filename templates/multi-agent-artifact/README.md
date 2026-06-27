# Multi-Agent Coding Environment

> AI 코딩 에이전트(Claude Code + Codex CLI)를 위한 portable bundle.
> 새 프로젝트 루트에 복사하고 도메인 specific 부분만 갈아끼우면 즉시 작동.

---

## Table of Contents

1. [Overview](#overview)
2. [What This Bundle Contains](#what-this-bundle-contains)
3. [Apply 절차 (Adapter AI 지침)](#apply-절차-adapter-ai-지침)
4. [시스템 모델](#시스템-모델)
5. [Cycle 흐름](#cycle-흐름)
6. [상태 외재화](#상태-외재화)
7. [핵심 설계 원칙](#핵심-설계-원칙)
8. [Anti-patterns](#anti-patterns)
9. [적용 후 검증 체크리스트](#적용-후-검증-체크리스트)
10. [References](#references)

---

## Overview

이 bundle은 다음 3가지를 묶어 portable하게 만든다:

1. **4-agent 워크플로우** — Planner / Executor / Step Advisor / Cycle Reviewer
2. **상태 외재화 컨벤션** — `.review/cycle-N/` 디렉터리에 plan.md + review-vN.md collection + advisor-feedback 보존
3. **자동화 hook** — fail-open 원칙으로 invariant 검증 + escalation 메커니즘

핵심 철학: **메모리/대화 이력이 아니라 마크다운 파일이 single source of truth.** 어떤 에이전트 인스턴스든 `.review/cycle-N/` 안의 파일을 읽으면 시스템 상태를 100% 복원 가능.

### 누가 어떤 모델을 사용하나

| 역할 | 모델 | 호출 패턴 |
|------|------|----------|
| **Planner** | Codex plan mode | cycle 시작 시 1회 |
| **Executor** | Claude Code (Sonnet) | pass별 1회, step 단위 진행 |
| **Step Advisor** | Opus 4.7 (sub-agent) | step마다 hook 자동 |
| **Cycle Reviewer** | Codex | pass별 1회 |

---

## What This Bundle Contains

```
bundle/
├── README.md                          ← 이 파일 (적용 시 제외)
├── AGENTS.md                          ← Source of truth (Codex CLI 표준)
├── HOOKS_REGISTRATION.md              ← hook 등록 가이드 (적용 시 참조 후 제외)
├── .claude/
│   ├── CLAUDE.md                      ← AGENTS.md 참조 + Claude-specific
│   ├── settings.json                  ← hook 등록 (template, 절대경로 치환 필요)
│   ├── hooks/
│   │   ├── block-dangerous.sh         ← 위험 명령 차단 (기존)
│   │   ├── force-advisor-check.sh     ← Completion check 강제 (기존)
│   │   ├── track-failures.sh          ← 2-strike Andon (기존)
│   │   ├── auto-format.sh             ← Edit/Write 후 포맷 (기존)
│   │   ├── save-advisor-feedback.sh   ← Advisor 호출↔파일 일치 (신규)
│   │   ├── check-cycle-cap.sh         ← Issue-velocity dual-trigger (신규)
│   │   └── check-context-budget.sh    ← 25-file 누적 카운터 (신규)
│   └── skills/
│       ├── advisor/SKILL.md           ← Opus 위임 메타 스킬
│       ├── design-principles/SKILL.md ← SOLID, 결합도/응집도 (도메인 무관)
│       └── (도메인 specific은 프로젝트별 추가)
├── agents/
│   └── skills/                        ← .claude/skills 미러 (sub-agent용)
├── .codex/
│   ├── config.toml
│   ├── hooks.json                     ← Codex용 hook 등록
│   └── hooks/                         ← .claude/hooks 일부 미러
├── .review/
│   └── _templates/
│       └── plan-template.md           ← cycle 시작 시 복사용
└── .gitignore.fragment                ← 대상 .gitignore에 append할 라인
```

### Universal vs Project-Specific

| 영역 | Universal (그대로) | Project-Specific (갈아끼움) |
|------|-------------------|---------------------------|
| AGENTS.md | 워크플로우, prohibited universal, cycle 운영 | Architecture 섹션, prohibited domain-specific 표 |
| CLAUDE.md | 전체 | (Architecture 외 없음) |
| Skills | `advisor`, `design-principles` | `backend-*`, `frontend-*`, `contract-*` 등 |
| Hooks | 전체 | settings.json 안의 절대경로 |
| Templates | plan-template.md | (없음) |

ChainLens로 이동 시 갈아끼울 것: AGENTS.md Architecture 섹션, 도메인 skill들, settings.json 경로. 그 외 전부 그대로.

---

## Apply 절차 (Adapter AI 지침)

> 이 절차는 bundle을 새 프로젝트에 적용하는 AI가 따른다.

1. **대상 프로젝트 확인** — git repo 루트인지, 기존 `.claude/` 또는 `.codex/` 설정이 있는지 확인.

2. **파일 복사** — `README.md`와 `HOOKS_REGISTRATION.md`를 **제외**하고 모든 파일을 대상 루트에 복사. 디렉터리 구조 그대로 유지.

3. **충돌 처리** — 기존 `CLAUDE.md`, `AGENTS.md`, `.gitignore`, `settings.json`이 있으면 **임의 덮어쓰기 금지**. 사용자에게 머지 방식 확인:
   - Option A: 기존 백업 후 bundle 버전 사용
   - Option B: 섹션별 머지 (사용자 검토)
   - Option C: bundle 적용 보류

4. **Hook 실행 권한** — `chmod +x .claude/hooks/*.sh .codex/hooks/*.sh`

5. **절대경로 치환** — `.claude/settings.json`과 `.codex/hooks.json`의 hook 경로에 절대경로가 박혀 있는 경우 대상 환경에 맞게 치환:
   - Windows: `c:\<PROJECT_PATH>\.claude\hooks\...`
   - macOS/Linux: `/Users/<USER>/<PROJECT>/.claude/hooks/...`
   가능하면 상대경로로 변경 권장.

6. **`.gitignore` 머지** — `.gitignore.fragment`의 내용을 대상 `.gitignore`에 append할지 사용자에게 확인. 일반적으로 추가:
   - `.review/cycle-*/.read-counter` (hook 임시 파일)
   - `/tmp/claude-failures-*.log` 형태 (track-failures.sh 출력)

7. **Architecture 채우기** — `AGENTS.md`의 Architecture 섹션 placeholder 6개를 대상 프로젝트의 실제 stack으로 채우라고 사용자에게 알림. 비어 있는 상태로는 cycle 진행 금지.

8. **도메인 skill 확인** — 대상 프로젝트의 stack에 맞는 skill이 `.claude/skills/`에 있는지 확인. 없으면 사용자에게 알림 (예: ChainLens면 `contract-solidity` 또는 `contract-anchor`가 필요).

9. **Smoke test** — 모든 hook을 빈 입력으로 호출해 fail-open이 정상 작동하는지 확인:
   ```bash
   for h in .claude/hooks/*.sh; do
     echo '{}' | "$h"
     echo "  -> $h exit=$?"
   done
   ```
   모두 `exit=0`이어야 정상.

10. **검증 체크리스트 보고** — [적용 후 검증 체크리스트](#적용-후-검증-체크리스트) 항목을 사용자에게 보고.

---

## 시스템 모델

### Two-Frequency Validation

이 시스템의 가장 본질적 특징은 **micro와 macro 두 frequency의 validator**가 동시에 작동한다는 점.

| Validator | 주기 | 모델 | 호출 방식 | 검토 범위 |
|-----------|------|------|----------|----------|
| **Step Advisor** (micro) | step마다 | Opus 4.7 | hook으로 자동 | 방금 한 step만 |
| **Cycle Reviewer** (macro) | pass마다 | Codex | 명시적 호출 | 전체 cycle 변경 |

micro는 **빠르고 자주, 좁게** — single-step regression 방지.
macro는 **느리고 가끔, 넓게** — pass 전체 정합성, scope creep, plan.md 위배 catch.

두 layer가 잡는 버그 종류가 다르기 때문에 한쪽으로 통합하면 catch율이 떨어진다.

### Clean-Context 격리

Step Advisor와 Cycle Reviewer는 모두 **Executor의 message history를 상속받지 않는다.**

- Step Advisor — Claude Code의 Task tool로 sub-agent 호출 (sub-agent는 main session의 context를 상속받지 않음)
- Cycle Reviewer — 완전히 별도의 Codex 세션

이 격리의 핵심 이유: validator가 executor reasoning을 보면 "이미 검토된 결정"으로 받아들여 user instruction 오해까지 catch할 기회를 잃는다. **Spec에서 거꾸로 추론하도록 강제**되어야 catch 가능.

### Communication Bridge

Validator의 지적을 Executor가 무조건 받아들이면 looping/scope creep/user intent 이탈이 발생한다. 그래서 BLOCKED 응답 직후 Executor의 first action은:

각 ISSUE를 plan.md와 대조해 **APPLY / DEFER / REJECT** 중 하나로 분류, RESOLVED 섹션에 결정과 이유 명시.

이 분류 절차가 명시화되지 않으면 다음 Cycle Reviewer가 같은 issue를 또 제기하거나, executor가 silent하게 무시한 것으로 오인된다.

---

## Cycle 흐름

### 정상 흐름 (PASS 도달)

```
Cycle 시작
    ↓
[Pass 1] Planner (Codex plan mode)
    ↓ plan.md 작성 (Sprint Contract + Review Guidance 포함)
    ↓
[Pass 2] Executor (Sonnet)
    ↓ Branch verify
    ↓ ┌─ step 1 implementation ──→ Advisor hook ──→ step-001.md
    ↓ ├─ step 2 implementation ──→ Advisor hook ──→ step-002.md
    ↓ └─ ...
    ↓
[Pass 3] Cycle Reviewer (Codex)
    ↓ review-v1.md 작성
    ↓ Verdict: PASS or READY_TO_MERGE
    ↓
status.txt = ready_to_merge → PR
```

### Iteration 흐름 (BLOCKED → RESOLVED)

```
[Pass 3] Cycle Reviewer → review-v1.md (BLOCKED, ISSUE-1)
    ↓
[Pass 4] Executor
    ↓ Communication Bridge: ISSUE-1을 plan.md와 대조
    ↓   결과: APPLY
    ↓ implementation + Advisor hook (step 단위)
    ↓ review-v1.md 끝에 RESOLVED 섹션 append
    ↓
[Pass 5] Cycle Reviewer → review-v2.md
    ↓ Verdict: PASS or BLOCKED (반복)
    ↓
... ready_to_merge까지 또는 cap 발동까지
```

### Escalation 흐름 (Issue-Velocity Cap)

```
review-vN 작성 시 check-cycle-cap.sh가 자동 검증
    ↓
Trigger 1 (Same-Issue Stagnation): 같은 ISSUE가 3개 연속 review에서 UNRESOLVED
    또는
Trigger 2 (New-Issue Velocity): 최근 5 review에서 신규 ISSUE 3건 이상
    ↓
status.txt = escalated → 자동 진행 정지
    ↓
사용자 판단: plan amend / cycle split / 접근 재검토
```

---

## 상태 외재화

### `.review/cycle-N/` 디렉터리

```
.review/cycle-N/
├── plan.md                    ← Planner 작성, immutable
├── review-v1.md               ← Codex review 본문 + 끝에 Executor의 RESOLVED 섹션
├── review-v2.md               ← 다음 pass의 review + RESOLVED
├── ...
├── diff.patch                 ← 자동 생성 (현재 hook 안정화 작업 보류)
├── status.txt                 ← in_progress | ready_to_merge | escalated
├── .read-counter              ← check-context-budget.sh 임시 파일 (gitignore)
└── advisor-feedback/
    ├── step-001.md            ← step별 Advisor 응답 + Sonnet 분류 (APPLY/무시 + 이유)
    ├── step-002.md
    └── ...
```

### Append-only 파일 규칙

| 파일 | 작성 주체 | 수정 가능 |
|------|----------|----------|
| `plan.md` | Planner | escalation 후 사용자만 |
| `review-vN.md` 본문 | Cycle Reviewer | 절대 수정 금지 |
| `review-vN.md` RESOLVED 섹션 | Executor | append only |
| `step-NNN.md` | Executor | 한번 작성 후 수정 금지 |
| `status.txt` | hook 자동 또는 Cycle Reviewer | 상태 전이만 |

`grep`으로 cycle 진행 상태를 언제든 복원 가능. 이게 외재화의 본질적 가치.

### plan.md 필수 섹션

`_templates/plan-template.md` 참조. 핵심 섹션:

- Branch (1:1 매핑)
- Summary
- 입력/출력 명세
- Key Changes
- **Sprint Contract** (검증 가능한 통과 기준)
- 누락된 엣지 케이스 후보 **3개** (강제)
- 더 단순한 대안 1개
- Assumptions
- **Review Guidance** — Cycle Reviewer가 빠짐없이 확인해야 할 enumeration + 검증 방식

Review Guidance가 충실할수록 cycle 횟수가 줄어든다. cycle 효율의 가장 큰 레버.

---

## 핵심 설계 원칙

### 1. Plan ↔ Branch 1:1

각 cycle은 정확히 하나의 git branch와 매핑. plan.md 첫 섹션 `Branch:` 라인이 진실의 근원. Executor 첫 동작은 branch verify + switch.

### 2. 한 plan = 한 feature = 한 PR

Commit unit 명시적 쪼개기 강제 안 함. plan.md `Key Changes` 항목이 implicit step 역할. Key Changes 10개 초과 시 cycle split 검토.

### 3. Clean-Context Validation

Step Advisor와 Cycle Reviewer는 별도 세션/sub-agent. Executor reasoning trace 상속 금지. Spec에서 거꾸로 추론하도록 강제.

### 4. Communication Bridge

BLOCKED 응답 후 Executor의 첫 단계는 각 ISSUE를 plan.md와 대조해 **APPLY / DEFER / REJECT** 분류. RESOLVED 섹션에 결정과 이유 명시.

### 5. Two-Frequency Validation

micro(Step Advisor, Opus, hook 자동) + macro(Cycle Reviewer, Codex, 명시적). 둘은 다른 종류 버그를 잡는다.

### 6. Issue-Velocity Cap (Hard cap 대신)

- Same-Issue Stagnation: 같은 ISSUE 3 review 연속 UNRESOLVED
- New-Issue Velocity: 5 review 윈도우에 신규 ISSUE 3건 이상

둘 중 하나 발동 시 status.txt = escalated. 사용자 개입까지 자동 진행 정지.

### 7. Context Discipline

- No preemptive read (CLAUDE.md/AGENTS.md 외)
- Glob/grep first, bounded read
- 5-file halt rule (step 단위, self-discipline)
- 25-file cycle limit (hook 강제, soft enforcement)

Context Rot 회피가 본질.

### 8. Fail-Open Hook 원칙

모든 hook은 jq 없음/파일 없음/JSON 파싱 실패 시 통과. 시스템을 막지 않는다. hook 자체 버그로 작업이 멈추는 risk 회피.

### 9. Advisor Feedback Externalization

매 Advisor 호출의 응답을 `step-NNN.md`에 보존. Sonnet이 무시한 항목은 이유 명시 의무. 휘발성 응답이 Hansei 추출의 가장 큰 장애물이라 외재화.

### 10. Skill System with Placeholders

도메인 specific 규범은 `.claude/skills/*/SKILL.md`로 분리. `<Entity>`, `<parentEntityId>` 같은 placeholder로 도메인 무관 portable.

### 11. Single Source of Truth (AGENTS.md)

AGENTS.md가 워크플로우의 single source. CLAUDE.md는 reference + Claude-specific 추가분만. 중복 정의 금지.

---

## Anti-patterns

### Workflow

1. **plan.md mid-cycle 수정** — escalation 경로에서만 허용 (사용자 판단).
2. **review-vN.md 본문 수정** — Codex 작성분 절대 수정 금지. RESOLVED는 파일 끝 append.
3. **step-NNN.md 저장 누락** — Advisor 호출 후 미저장 시 hook이 차단. Communication bridge 깨짐.
4. **branch 미확인 implementation** — invariant 위반. cycle 진입 시 강제 확인.

### Architecture

5. **단일 에이전트로 fallback** — "Sonnet에게 다 시키면 됨"은 cycle quality를 무너뜨림. trivial이면 시스템 우회, non-trivial이면 cycle 통과.
6. **Validator에 executor 컨텍스트 주입** — clean-context 원칙 위반.
7. **Step Advisor와 Cycle Reviewer를 한 layer로 통합** — two-frequency catch율 손실.

### Communication

8. **Advisor 응답 silent 무시** — 무시할 수 있지만 이유 명시 의무. 이유 없는 무시 = anti-pattern.
9. **한국어 inter-agent 통신** — 토큰 비용 2-3배. plan.md/review-vN.md는 영어 권장 (점진적 전환).

### Operational

10. **trivial 작업에 cycle 풀가동** — README 한 줄 수정에 plan+review 돌리는 건 낭비.
11. **hook을 strict하게 만들기** — fail-open 원칙 위반. hook 버그로 시스템 마비될 위험.
12. **threshold를 hard-code** — `CYCLE_*` 환경 변수로 override 가능하게 유지.

---

## 적용 후 검증 체크리스트

Adapter AI가 사용자에게 보고:

### 구조 검증
- [ ] `AGENTS.md` 존재, Architecture 섹션 placeholder가 채워짐
- [ ] `.claude/CLAUDE.md` 존재, AGENTS.md 참조 라인 있음
- [ ] `.claude/hooks/*.sh` 7개 (기존 4 + 신규 3) 모두 실행 권한 부여
- [ ] `.claude/settings.json`의 hook 경로가 실제 위치와 일치
- [ ] `.codex/config.toml`, `.codex/hooks.json` 존재
- [ ] `.review/_templates/plan-template.md` 존재

### 도메인 skill 검증
- [ ] `.claude/skills/advisor/SKILL.md` 존재 (universal)
- [ ] `.claude/skills/design-principles/SKILL.md` 존재 (universal)
- [ ] 대상 프로젝트 stack에 맞는 도메인 skill 존재 또는 추가 필요 알림
- [ ] `agents/skills/` 가 `.claude/skills/` 와 동일 내용

### Hook smoke test
- [ ] `force-advisor-check.sh` 빈 입력 통과
- [ ] `save-advisor-feedback.sh` 빈 입력 통과
- [ ] `check-cycle-cap.sh` 빈 입력 통과
- [ ] `check-context-budget.sh` 빈 입력 통과
- [ ] `track-failures.sh` 빈 입력 통과

### Git 설정
- [ ] `.gitignore`에 hook 임시 파일 패턴 추가됨 (`.review/cycle-*/.read-counter` 등)
- [ ] `.review/` 디렉터리 추적 정책 결정됨 (track or partial track)

### 첫 cycle 준비
- [ ] 사용자에게 "Architecture 채워졌으면 첫 plan을 Codex plan mode로 작성 시작" 신호 가능

---

## References

이 시스템의 설계 출처:

| 출처 | 기여 |
|------|------|
| **Cognition** "Multi-Agents: What's Actually Working" (2026.4) | Clean-context reviewer, Communication bridge |
| **Anthropic** Claude Code 문서 | Sub-agent 패턴, just-in-time retrieval, 25% context rule |
| **Toyota Production System** | Andon cord (2-strike), Hansei, blameless 원칙 |
| **Karpathy CLAUDE.md** (Forrest Chang 정리, 2026.1) | 4 행동 원칙 (executor 가이드) |
| **Crack CLI** (`github.com/Royaltyprogram/Crack-CLI`) | Plan-branch 1:1 매핑 |
| **사용자 운영 경험** (cycle 2/3) | review-vN append 패턴, advisor as sub-agent, fail-open hook, Sprint Contract format, 2-strike 실제 구현 |

마지막 항목이 가장 중요. 이 bundle의 절반 이상은 추상적 best practice가 아니라 **실제 production 사이클에서 검증된 패턴**의 정리.

---

## Bundle 진화 로드맵 (선택)

향후 추가 검토 항목:

- **Hansei learnings.md 자동 추출** — step-NNN.md의 "무시 + 이유" 누적 분석으로 패턴 감지
- **diff.patch 자동 생성 hook 안정화** — cycle2에서 빈 파일 문제 해결
- **Plan-of-Plans 레이어** — plan 간 의존성 생길 때
- **Codex review prompt 강화** — Review Guidance를 더 적극적으로 활용하도록
- **agents/skills ↔ .claude/skills 자동 동기화** — sync 스크립트 또는 symlink

이 항목들은 운영하면서 필요해질 때 추가. 지금 도입하면 over-engineering.
