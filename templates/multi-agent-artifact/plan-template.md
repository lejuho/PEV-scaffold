<!--
  Plan Template — `.review/_templates/plan-template.md`

  사용법:
  1. 새 cycle 시작 시 이 파일을 `.review/cycle-N/plan.md`로 복사
  2. 모든 <placeholder>와 N/A 자리 채우기
  3. Codex plan mode에서 작성하고 Claude Code가 비판적 리뷰 후 v2 확정
  4. 확정된 plan.md를 기준으로 Sonnet이 implementation 진입

  컨벤션 source of truth: /AGENTS.md "plan.md Template" 섹션
  -->

# <기능명> 구현 계획

Branch: <feature/...>
Cycle: <N>
Created: <YYYY-MM-DD>
Skills: <skill1, skill2 | none>
<!-- 이번 cycle이 로드해야 할 도메인 skill. 코드 변경이 있으면 필수.
     해당 도메인 skill이 없으면 "none". advisor는 자동이라 적지 않아도 됨.
     check-skill-loaded.sh가 선언 ↔ 실제 로드를 검증한다. -->


## Summary

<!-- 현재 상태 한 문단 + 이번 cycle의 목표 한 문단. 왜 이 작업이 필요한지, 무엇을 만들고 무엇은 만들지 않는지 명시. -->

<현재 상태 진단>

<이번 cycle 목표>

## 입력/출력 명세

<!-- 외부 계약 — endpoint, payload, auth, error 형식. 정상/실패를 분리해서 적는다. -->

- 입력:
  - endpoint: `<METHOD> <path>`
  - content-type: `<...>`
  - field: `<...>`
  - auth: `<...>`
- 출력:
  - 정상:
    - <응답 형식 + side effect>
  - 실패:
    - <에러 종류별 처리 방식>

## Key Changes

<!-- 파일별 변경 사항. Backend/Frontend로 나눠도 좋고, 모듈별로 나눠도 좋다. 한 항목 = 한 step 수준의 입도. -->

- Frontend
  - `<path>` — <변경 내용>
- Backend
  - `<path>` — <변경 내용>
- (Contract) — <Web3 프로젝트인 경우>

## Sprint Contract

<!-- 이 cycle이 끝났을 때 만족해야 하는 조건들. 검증 가능한 형태로 적는다. "잘 작동한다" 같은 모호한 표현 금지. -->

- 통과 기준:
  - <검증 가능한 조건 1>
  - <검증 가능한 조건 2>
  - ...
- 자동 체크:
  - Frontend: `<lint/typecheck 명령>`
  - Backend: `<build/test 명령>`
  - (Contract): `<forge test / anchor test / slither>`
- 테스트 케이스:
  - 단위/통합: <어느 모듈을 어떻게>
  - 수동 검증: <어느 시나리오를 사람이>
- gas 한도: <한도 또는 N/A>
- slither 통과: <required 또는 N/A>

## 누락된 엣지 케이스 후보 3개

<!-- range 외 입력, 동시성, 외부 의존 실패, 권한 경계 등. 3개를 강제하는 이유: 자기검열을 강제. 2개 이하로 적지 말 것. -->

- <후보 1>
- <후보 2>
- <후보 3>

## 더 단순한 대안 1개

<!-- 더 빠르지만 trade-off가 있는 접근. 채택하지 않은 이유 명시. -->

<설명> — 채택하지 않은 이유: <...>

## Assumptions

<!-- 검증 없이 전제하는 사항. DB 스키마, 외부 API 응답 형식, 인프라 상태 등. Codex review가 이걸 challenge할 수 있다. -->

- <전제 1>
- <전제 2>

## Review Guidance

<!--
  Cycle Reviewer(Codex)와 Step Advisor(Opus)가 빠짐없이 확인해야 할 가이드.
  이 섹션이 충실할수록 cycle 횟수가 줄어든다.

  반드시 두 가지를 포함:
  (a) Enumeration이 필요한 대상 — 명시적 grep/rg 명령과 함께
  (b) Sprint Contract 항목별 검증 방식 — mock으로 충분한지, 통합 테스트가 필요한지
-->

### Enumeration 필요 항목

- <대상 1> 전체 집합
  - 검색: `<grep/rg 명령>`
  - 예상 결과: <N개 / 어떤 파일들>
- <대상 2>
  - 검색: `<...>`
  - 예상 결과: <...>

### 검증 방식 가이드

- "<Sprint Contract 항목 1>":
  - <어떤 테스트 방식으로 검증 가능 / 어떤 방식으론 불충분>
- "<Sprint Contract 항목 2>":
  - <...>
