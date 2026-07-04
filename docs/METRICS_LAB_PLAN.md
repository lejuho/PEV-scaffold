# PEV Metrics & Self-Improvement Lab — 구현 계획

대상 구현자: Claude Sonnet (또는 동급 에이전트). 이 문서는 단독으로 읽고 구현할 수 있도록 작성됨.
선행 문서: [`docs/RUNBOOK.md`](RUNBOOK.md) (PEV 사이클 구조), [`README.md`](../README.md).

## 0. 목표

PEV 대시보드를 단순 상태 표시기에서 **관측 → 실패/예외 발견 → 자기개선**이 도는 실험실로 확장한다.

측정하려는 핵심 지표:

| 지표 | 정의 | 사용자에게 보이는 형태 |
|---|---|---|
| 절약 시간 (autonomy time) | 사이클 진행 중 사람 개입 없이 자동으로 흐른 시간 | "이번 주 12.4h 자동 진행" |
| 사이클당 비용 | Claude 트랜스크립트 usage를 API 종량제 단가로 환산 | "cycle 82: $1.83" |
| 재작업 비용 | pass-002 이후 구간의 비용 (BLOCKED로 인한 낭비) | "이번 달 재작업 $X" |
| First-pass PASS rate | review-v1에서 바로 PASS/READY_TO_MERGE가 나온 사이클 비율 | "최근 10사이클 중 8" + streak |
| 개입 횟수/사이클 | telegram_command + 대시보드 command POST 수 | 사이클 히스토리 테이블 컬럼 |
| 발견→수정 시간 | BLOCKED verdict 시각 → fix pass done.json `createdAt` | 히스토리 테이블 컬럼 |
| 오류 3분류 | 인프라 / 실행자 결함 / 시스템(스캐폴드) 결함 | 오류 피드 + 태깅 UI |

## 1. 확인된 원천 데이터 (2026-07-04 기준 실측)

구현 전 반드시 이 원천들이 존재하는지 재확인할 것.

1. **`$HERMES_ROOT/logs/hermes-events.jsonl`** — hermes-cycle-bot이 append.
   - 현재 이벤트: `state_changed` (`previous_phase`, `phase`만 있음 — **cycle 번호 없음, 이게 최우선 수정 대상**), `telegram_command`, `telegram_callback`, `loop_error`.
   - 실측: 575건 중 loop_error 309건 (전부 DNS/SSL 네트워크 오류 = 인프라 분류).
2. **`$HERMES_ROOT/.review/cycle-N/`** — 사이클 아티팩트.
   - `plan.md`, `review-vN.md` (Verdict 포함), `status.txt`, `executor/pass-NNN-done.json` (**`createdAt` ISO 타임스탬프 있음**), `advisor-feedback/`.
   - 디렉토리 mtime과 done.json `createdAt`으로 과거 사이클 시간 백필 가능.
3. **`~/.claude/projects/<flattened-project-path>/*.jsonl`** — Claude Code 세션 트랜스크립트.
   - 프로젝트 경로를 `/`→`-` 치환한 디렉토리명 (예: `/home/pi/cairn` → `-home-pi-cairn`).
   - 각 라인의 `message.usage`에 `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`, `cache_creation.ephemeral_5m_input_tokens` 존재. 각 라인에 최상위 `timestamp` 필드가 있는지 확인하고, 없으면 대체 필드를 찾아서 사용할 것 (구현 시 실제 파일 1개를 열어 스키마 확인 필수).
4. **`~/.codex/sessions/`** — Codex 세션 로그. **포맷 미확인.** Phase 2에서 실제 파일을 열어 토큰 필드가 있는지 확인 후, 없으면 Codex 비용은 "미측정"으로 명시하고 스킵 (억지로 추정하지 말 것).
5. **대시보드 command POST** — `dashboard/server.py`의 `/api/projects/<id>/command`. 현재 이벤트 로그에 기록 안 됨 (수정 대상).

## 2. 아키텍처 원칙

- **새 저장소를 만들지 말고 이벤트 로그를 확장**한다. 진실의 원천은 `hermes-events.jsonl` + `.review/` 아티팩트 + 트랜스크립트. 메트릭은 전부 이들로부터의 **파생 계산**이며, 계산 결과는 캐시일 뿐이다 (지우고 다시 계산해도 같은 값이 나와야 함).
- 파생 계산 캐시: `$HERMES_ROOT/logs/pev-metrics.json` (프로젝트별 1개). 대시보드 서버가 갱신.
- 의존성 추가 금지: 표준 라이브러리만 사용 (기존 코드와 동일 기조).
- 기존 파일 포맷은 하위 호환 유지: 이벤트에 필드를 **추가**만 하고, 기존 필드는 바꾸지 않는다.
- 모든 타임스탬프는 기존 `utc_now()` 포맷 (`...Z`) 그대로.

## 3. Phase 1 — 이벤트 계측 강화 (기반 작업, 최우선)

### 3.1 `scripts/hermes-cycle-bot.py`

- `log_event()` 정의: `hermes-cycle-bot.py:393`. 수정 불필요.
- **`state_changed` 이벤트 강화** (`hermes-cycle-bot.py:1188`): 현재 `previous_phase`, `phase`만 기록. 여기에 `cycle`, `status`, `verdict`, `latest_review`, `pass`(latest_review 파일명의 vN 또는 done 파일의 pass 번호) 를 추가한다. `CycleState`에 이미 해당 필드가 있음 (`format_status()` 참고).
- **새 이벤트 3종 추가** — 기존 감지 로직이 있는 지점에서 호출:
  - `cycle_started`: 새 cycle 디렉토리가 처음 관측될 때. `{"cycle": N}`.
  - `pass_done`: done.json이 처리될 때 (flow의 processed_done_files에 추가되는 지점). `{"cycle": N, "pass": M, "kind": "implement"|"fix", "done_path": rel, "created_at": done의 createdAt}`.
  - `verdict`: review-vN.md에서 verdict가 새로 관측되거나 바뀔 때. `{"cycle": N, "review": rel, "verdict": "..."}`.
- 중복 방지: flow state에 마지막으로 기록한 키를 저장하는 기존 패턴 (`last_action_key`, `last_notice_key`)을 따라 `last_metric_keys` 같은 dict를 두어 같은 이벤트를 두 번 쓰지 않게 한다.

### 3.2 `dashboard/server.py`

- **command POST를 이벤트로 기록**: `run_project_command()` 성공/실패 시 `$HERMES_ROOT/logs/hermes-events.jsonl`에 `{"event": "dashboard_command", "command": ..., "returncode": ...}` append. (사람 개입 카운트의 절반이 여기서 나옴. `create_done`도 `dashboard_done` 이벤트로 기록.)
- 이벤트 파일 경로는 프로젝트 root 기준 `logs/hermes-events.jsonl`로 하드코딩하지 말고, 쓰기 실패는 조용히 무시 (대시보드 동작을 막으면 안 됨).

### Phase 1 검증

```bash
python3 -m py_compile scripts/hermes-cycle-bot.py dashboard/server.py
# 실제 사이클 1회 또는 수동 상태 변화 후:
tail -5 $HERMES_ROOT/logs/hermes-events.jsonl   # cycle 필드가 붙은 state_changed 확인
```

## 4. Phase 2 — 백필 + 메트릭 계산기

### 4.1 새 파일 `dashboard/metrics.py`

순수 계산 모듈 (HTTP 무관, import 가능 + CLI 실행 가능). 입력: 프로젝트 root, 트랜스크립트 디렉토리. 출력: 아래 스키마의 dict.

```json
{
  "generatedAt": "...Z",
  "cycles": [
    {
      "cycle": 82,
      "startedAt": "...Z",          // cycle 디렉토리 birth/mtime 또는 cycle_started 이벤트
      "endedAt": "...Z",            // ready_to_merge 도달 또는 다음 cycle 시작
      "durationSec": 3600,
      "passes": 1,                   // executor/pass-*.json 개수
      "firstPass": true,             // review-v1 verdict가 PASS/READY_TO_MERGE
      "finalVerdict": "READY_TO_MERGE",
      "interventions": 2,            // 구간 내 telegram_command + telegram_callback + dashboard_command 수
      "autonomySec": 3400,           // durationSec - (개입 시각 주변은 단순화: 개입 자체는 순간으로 취급, 아래 정의 참조)
      "blockedToFixSec": null,       // BLOCKED verdict ts → 다음 pass done createdAt (재작업 없으면 null)
      "tokens": {"input": 0, "output": 0, "cacheWrite5m": 0, "cacheWrite1h": 0, "cacheRead": 0},
      "costUsd": 1.83,
      "reworkCostUsd": 0.0,          // pass-001 done 이후 구간의 비용
      "failureTag": null             // Phase 3에서 사람이 확정, "executor"|"plan"|"reviewer"|"infra"|null
    }
  ],
  "totals": {"cycles": 82, "firstPassRate": 0.78, "autonomyHours": 41.2, "costUsd": 92.1, "reworkCostUsd": 8.4},
  "errors": [
    {"kind": "infra", "firstTs": "...Z", "lastTs": "...Z", "count": 5, "sample": "urlopen error ..."}
  ]
}
```

계산 규칙 (단순하게 시작, 과도한 정밀화 금지):

- **사이클 시간 구간**: `cycle_started` 이벤트가 있으면 그것, 없으면(과거 백필) cycle 디렉토리 안 가장 이른 파일 mtime. 종료는 verdict가 PASS/READY_TO_MERGE가 된 시각(review 파일 mtime) 또는 다음 사이클 시작 시각 중 이른 것.
- **autonomySec**: 사이클 구간 길이에서, "개입 후 다음 자동 액션까지" 같은 정교한 모델링은 하지 않는다. v1 정의 = `durationSec` (사이클이 돈 시간 전체가 곧 사람이 직접 안 한 시간). 단, `interventions` 카운트를 함께 보여줘서 해석을 맡긴다. 이 단순화를 metrics.py 주석과 대시보드 툴팁에 명시.
- **토큰→사이클 귀속**: 트랜스크립트 각 라인의 타임스탬프가 사이클 구간 `[startedAt, endedAt)`에 들어가면 그 사이클로 귀속. 어느 구간에도 안 들어가면 `unattributed` 버킷에 합산해 totals에 표시 (버리지 말 것).
- **단가**: 하드코딩 금지. `dashboard/pricing.json` (예시 파일 `pricing.example.json`을 repo에 커밋, 실제 파일은 gitignore 대상 아님 — 비밀 아님, 커밋해도 됨)

```json
{
  "models": {
    "default": {"inputPerMTok": 3.0, "outputPerMTok": 15.0, "cacheWrite5mPerMTok": 3.75, "cacheWrite1hPerMTok": 6.0, "cacheReadPerMTok": 0.3}
  },
  "note": "USD per million tokens. 값은 예시 — 사용 모델의 실제 단가로 수정할 것."
}
```

  트랜스크립트에 model id가 있으면 model별 매칭, 없으면 `default` 사용.
- **오류 그룹핑**: `loop_error`를 30분 gap 기준으로 클러스터링해 `errors[]`에 넣는다. 분류 v1은 규칙 기반: `urlopen|ssl|timeout|resolution` → `infra`, 그 외 → `unknown`.

CLI 모드: `python3 dashboard/metrics.py --root $HERMES_ROOT --write` → `$HERMES_ROOT/logs/pev-metrics.json` 생성. `--write` 없으면 stdout 출력.

### 4.2 `dashboard/server.py` API 추가

- `GET /api/projects/<id>/metrics`: 캐시 파일(`logs/pev-metrics.json`)이 있고 60초 이내면 그대로 반환, 아니면 metrics.py로 재계산 후 저장·반환. 트랜스크립트 스캔이 느릴 수 있으므로 재계산은 요청 스레드에서 하되 timeout 개념으로 트랜스크립트 파일당 크기 상한(예: 50MB 초과 파일은 skip하고 응답에 `skipped` 표시).
- `GET /api/metrics/summary`: 전 프로젝트 totals 합산.

### Phase 2 검증

```bash
python3 dashboard/metrics.py --root /home/pi/cairn          # 82사이클 백필 결과 눈으로 확인
python3 -m py_compile dashboard/metrics.py dashboard/server.py
curl -sS http://127.0.0.1:8765/api/projects/<id>/metrics | python3 -m json.tool | head -50
```

sanity check: cycle 77·78은 passes=2 (재작업), 79~82는 passes=1이어야 함 (flow.json processed_done_files 실측과 일치).

## 5. Phase 3 — 대시보드 UI

`dashboard/static/` (index.html, app.js, style.css — 프레임워크 없는 바닐라 JS, 기존 스타일 유지. 기존 한국어 토글 패턴 따를 것).

1. **프로젝트 카드 지표 줄 추가**: `사이클 경과 1h 23m · 이번 사이클 $1.83 · first-pass streak 4 · 누적 자동 41h`. `/api/projects/<id>/metrics`를 카드 펼침 시 lazy fetch (폴링에 끼우지 말 것 — 재계산 비용).
2. **사이클 히스토리 테이블** (프로젝트 상세 안 탭): cycle / verdict / passes / duration / cost / rework cost / interventions / 발견→수정 시간 / failureTag. 최근 20개 + 더보기.
3. **오류 피드**: `errors[]`를 "네트워크 불안정 09:00–12:00 (5건)" 형태로 압축 표시.
4. **실패 태깅**: BLOCKED가 있었던 사이클 행에 태그 버튼 4개 (실행자/플랜/리뷰어오탐/인프라). `POST /api/projects/<id>/cycles/<n>/tag` → `state.json`의 project meta 아래 `cycleTags: {"77": "executor"}`로 저장. metrics.py가 이를 읽어 `failureTag`에 반영. (리뷰어 오탐 태그 비율 = 오류 판단 정확도 지표의 원천.)
5. **추세 미니 차트**: 최근 20사이클의 first-pass 여부·비용을 CSS/inline-SVG 스파크라인으로. 외부 라이브러리 금지.

## 6. Phase 4 — 메타 사이클 (자기개선 루프)

코드보다 절차가 먼저다. v1은 자동화하지 않고 **수동 트리거 + 템플릿**으로 시작:

1. 새 파일 `templates/multi-agent-artifact/meta-cycle-template.md`: N사이클마다(권장 10) PEV 자체를 대상으로 하는 회고 사이클 플랜 템플릿. 입력 = `pev-metrics.json` totals·최근 추세·failureTag 분포. 산출 = `AGENTS.md`/`plan-template.md`/훅 스크립트에 대한 구체적 개선 diff 제안 + "개선 후 비교할 지표와 목표값" 명시 (예: "first-pass rate 0.7→0.8, 10사이클 후 재측정").
2. 대시보드에 "메타 사이클 제안" 배너: `totals.cycles % 10 == 0`이고 마지막 메타 사이클 이후 10사이클 경과 시 표시. 버튼은 클립보드에 메타 사이클 프롬프트 복사만 (자동 실행 금지 — 사람이 시작).
3. `docs/RUNBOOK.md`에 메타 사이클 운영 절차 섹션 추가: 언제 돌리는지, 개선 적용 전후 비교를 어떻게 기록하는지 (`logs/meta-cycles.jsonl`에 `{"ts", "cyclesAt", "changes", "baseline": {...totals snapshot}}` append).

## 7. 비목표 (하지 말 것)

- 외부 DB/의존성 도입 (sqlite 포함 — jsonl+json 캐시로 충분).
- Codex 토큰 비용 추정치 날조 (포맷 확인 안 되면 "미측정" 표기).
- 개입 시간의 정교한 귀속 모델 (v1은 카운트만).
- 메타 사이클 자동 실행 (사람 트리거 필수).
- 기존 이벤트 필드 rename/삭제.

## 8. 구현 순서와 커밋 단위

1. `feat(metrics): enrich hermes events with cycle context` — Phase 1 전체.
2. `feat(metrics): add metrics calculator with backfill` — metrics.py + pricing.example.json + CLI.
3. `feat(dashboard): metrics API endpoints` — server.py API.
4. `feat(dashboard): cycle history and cost UI` — Phase 3의 1~3.
5. `feat(dashboard): failure tagging` — Phase 3의 4~5.
6. `docs: meta-cycle procedure and template` — Phase 4.

각 커밋 전: `python3 -m py_compile` 대상 파일 전부 + `python3 dashboard/server.py --check` + (2번 이후) `python3 dashboard/metrics.py --root /home/pi/cairn`이 예외 없이 완주해야 한다. 실데이터(cairn 82사이클)가 최고의 테스트 픽스처다 — 백필 결과의 passes 수가 flow.json과 일치하는지 반드시 대조할 것.

## 9. 리스크 메모

- 트랜스크립트 JSONL은 수십 MB일 수 있음 → 라인 단위 스트리밍 파싱, `usage` 없는 라인 즉시 skip, 파일 mtime이 사이클 범위 밖이면 파일째 skip.
- `.review/` mtime 기반 백필은 파일 복사/체크아웃으로 왜곡될 수 있음 → done.json `createdAt`을 우선 신뢰하고 mtime은 fallback.
- 대시보드는 인증 없는 로컬 서버 → 새 POST 엔드포인트(tag)도 기존과 동일하게 상태 파일 쓰기 이상의 부작용 금지 (명령 실행류 추가 금지).
- merge 직후 phase가 `unknown`으로 빠지는 기존 현상 (`state_changed: ready_to_merge → unknown` 실측) → 메트릭에서 사이클 종료 판정은 verdict 기준이므로 영향 없지만, 히스토리 테이블에서 `unknown` 구간이 다음 사이클에 붙지 않도록 endedAt 규칙(§4.1)을 따를 것.
