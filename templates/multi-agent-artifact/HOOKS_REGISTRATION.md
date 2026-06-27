# Hook 등록 가이드

신규 hook 3개를 기존 `.claude/settings.json`과 `.codex/hooks.json`에 추가하는 방법.

## .claude/settings.json 업데이트

기존 settings.json의 `hooks` 섹션에 다음을 머지. 이미 등록된 hook은 유지하고 신규 hook만 추가.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/block-dangerous.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/track-failures.sh"
          }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/auto-format.sh"
          }
        ]
      },
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/check-context-budget.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/force-advisor-check.sh"
          },
          {
            "type": "command",
            "command": ".claude/hooks/save-advisor-feedback.sh"
          },
          {
            "type": "command",
            "command": ".claude/hooks/check-resolved-immutable.sh"
          },
          {
            "type": "command",
            "command": ".claude/hooks/check-skill-loaded.sh"
          },
          {
            "type": "command",
            "command": ".claude/hooks/check-cycle-cap.sh"
          }
        ]
      }
    ]
  }
}
```

### 변경점

- **PostToolUse → Read matcher 추가** — `check-context-budget.sh` 등록
- **Stop hooks 배열 확장** — 기존 1개에서 5개로 (force-advisor-check, save-advisor-feedback, check-resolved-immutable, check-skill-loaded, check-cycle-cap)

### Stop hook 실행 순서

배열 순서대로 직렬 실행. 한 hook이 block하면 나머지는 실행 안 됨. 의도된 우선순위:

1. `force-advisor-check.sh` — Completion check 호출 여부 (필수 invariant)
2. `save-advisor-feedback.sh` — 호출했다면 저장도 했는지 (Communication bridge)
3. `check-resolved-immutable.sh` — review-vN.md Codex 본문 변조 여부 (review 파일 무결성)
4. `check-skill-loaded.sh` — plan.md Skills: 선언 ↔ 실제 로드 일치 (작업 정합성)
5. `check-cycle-cap.sh` — 무한 cycle 방지 (escalation 메커니즘)

이 순서가 깨지면 안 되는 이유: Completion check 자체를 안 했으면 save 검증은 의미 없고, save가 누락된 채로 cycle cap을 평가하면 평가 자체가 부정확. 그리고 `check-cycle-cap.sh`는 review-vN.md를 파싱해 ISSUE 상태를 읽으므로, 그 직전에 review 파일이 변조되지 않았음을 `check-resolved-immutable.sh`가 먼저 보장해야 cap 평가가 신뢰 가능하다. `check-skill-loaded.sh`는 review 무결성 다음, cap 평가 앞에 둔다(작업 정합성 위반이 escalation보다 먼저 잡혀야 함).

## .codex/hooks.json 업데이트

Codex는 Executor 역할이 아니라 Planner/Cycle Reviewer 역할이므로 신규 hook 일부는 적용 안 함:

- ✅ `check-cycle-cap.sh` 적용 — Codex review 후에도 cap 검증
- ❌ `save-advisor-feedback.sh` 미적용 — Advisor 호출은 Claude Code만
- ❌ `check-resolved-immutable.sh` 미적용 — RESOLVED append는 Executor(Claude)만. Codex는 새 review-v(N+1).md를 새로 쓸 뿐 기존 파일을 수정하지 않음.
- ❌ `check-skill-loaded.sh` 미적용 — skill 로드는 Executor(Claude)만. Codex는 plan/review 단계.
- ❌ `check-context-budget.sh` 미적용 — Codex는 plan/review 단계라 다른 패턴

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "'c:\\<PROJECT_PATH>\\.codex\\hooks\\block-dangerous.sh'"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "'c:\\<PROJECT_PATH>\\.codex\\hooks\\track-failures.sh'"
          }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "'c:\\<PROJECT_PATH>\\.codex\\hooks\\auto-format.sh'"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "'c:\\<PROJECT_PATH>\\.codex\\hooks\\force-advisor-check.sh'"
          },
          {
            "type": "command",
            "command": "'c:\\<PROJECT_PATH>\\.codex\\hooks\\check-cycle-cap.sh'"
          }
        ]
      }
    ]
  }
}
```

## 파일 배치

```
.claude/hooks/
├── block-dangerous.sh          (기존)
├── force-advisor-check.sh      (기존)
├── track-failures.sh           (기존)
├── auto-format.sh              (기존)
├── save-advisor-feedback.sh    ← 신규
├── check-cycle-cap.sh          ← 신규
├── check-context-budget.sh     ← 신규
├── check-resolved-immutable.sh ← 신규 (RESOLVED 경계 무결성)
├── check-skill-loaded.sh       ← 신규 (Skills: 선언 ↔ 로드 검증)
└── check-marker-sync.sh        ← 신규 (마커 드리프트 검사 — Stop hook 아님, pre-commit/CI용)

.codex/hooks/
├── block-dangerous.sh          (기존)
├── force-advisor-check.sh      (기존)
├── track-failures.sh           (기존)
├── auto-format.sh              (기존)
└── check-cycle-cap.sh          ← 신규 (save-advisor-feedback, check-context-budget, check-resolved-immutable은 미적용)
```

> `check-marker-sync.sh`는 Claude Code Stop hook이 아니라 **pre-commit/CI 검사기**다. `settings.json` Stop 배열에 넣지 말 것. 등록 방법은 `CONTRACT_MARKERS.md`의 "pre-commit 연동" 참조.

## 적용 후 확인

1. 모든 hook에 실행 권한 부여:
   ```bash
   chmod +x .claude/hooks/*.sh .codex/hooks/*.sh
   ```

2. 신규 hook smoke test (각 hook을 빈 입력으로 호출, 통과해야 정상):
   ```bash
   echo '{}' | .claude/hooks/save-advisor-feedback.sh
   echo '{}' | .claude/hooks/check-cycle-cap.sh
   echo '{}' | .claude/hooks/check-context-budget.sh
   echo '{}' | .claude/hooks/check-resolved-immutable.sh
   echo '{}' | .claude/hooks/check-skill-loaded.sh
   echo "exit=$?"  # 0이면 정상 (fail-open 통과)
   ```

   마커 드리프트 검사 (Stop hook 아님, 별도 실행):
   ```bash
   bash .claude/hooks/check-marker-sync.sh   # 모든 마커 동기화 시 exit 0, 드리프트 시 exit 1
   ```

3. `.review/cycle-N/` 디렉터리 없는 상태에서도 hook이 통과하는지 확인 (cycle 시스템 미사용 세션 호환성).

## 환경 변수 override

운영하면서 threshold 조정 필요 시 `.claude/settings.json`이나 shell rc에:

```bash
export CYCLE_STAGNATION_LIMIT=3       # Same-Issue Stagnation 임계 (기본 3)
export CYCLE_VELOCITY_PASS_WINDOW=5   # New-Issue Velocity 윈도우 (기본 5)
export CYCLE_VELOCITY_ISSUE_LIMIT=3   # 윈도우 내 신규 issue 임계 (기본 3)
export CYCLE_FILE_LIMIT=25            # cycle 단위 read 파일 수 (기본 25)
```
