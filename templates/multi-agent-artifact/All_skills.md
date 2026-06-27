## 프론트엔드

### 5개 핵심 규칙

```
1. 컴포넌트 하나당 파일 하나
2. 데이터를 직접 fetch하지 말 것 — props로만 받기
3. 버튼 onClick은 반드시 props로 받기 (내부에서 API 호출 금지)
4. useState는 최대한 위로 올리기 (페이지 레벨에서 관리)
5. 파일명 = 컴포넌트명 (BundleCard.tsx, ReviewPanel.tsx)
```

---

### 폴더 구조

```
/root
 / ... // 여기 자세히 작성
```

**담당 컴포넌트**

| 담당 | 컴포넌트 |
| --- | --- |
| PM | .. 여기 자세히 작성 |
| 아키텍트 | .. 여기 자세히 작성 |
| 공용 (누가 먼저든) | .. 여기 자세히 작성 |

공용 컴포넌트는 Week 1 안에 하나로 합의 후 시작.

---

### 절대 쓰지 말 것 (.cursorrules에 추가)

```
- any 타입
- useEffect 안에서 fetch
- 컴포넌트 안에서 router.push 직접 호출
- console.log (디버깅 후 반드시 제거)
- 인라인 스타일 (style={{ }}) — Tailwind 클래스만
- 파일 안에 타입 직접 선언 (types/index.ts에서 import)
```

---

### 올바른 컴포넌트 패턴

**잘못된 것:**

```tsx
// BundleCard.tsx
export function BundleCard({ bundleId }) {
  const [bundle, setBundle] = useState(null);

  useEffect(() => {
    fetch(`/api/bundles/${bundleId}`)   // ← API 직접 호출 금지
      .then(r => r.json())
      .then(setBundle);
  }, [bundleId]);

  return (
    <div onClick={() => fetch(`/api/bundles/${bundleId}/approve`)}>
      {bundle?.name}
    </div>
  );
}
```

**올바른 것:**

```tsx
// BundleCard.tsx — 데이터는 props, 액션은 콜백
import { Bundle } from '@/types';

type Props = {
  name: string;
  status: Bundle['status'];
  revision: string;
  isLoading: boolean;
  error: string | null;
  onClick: () => void;       // 내부에서 뭘 할지 모름, 위에서 결정
};

export function BundleCard({ name, status, revision, isLoading, error, onClick }: Props) {
  if (isLoading) return <div>로딩 중...</div>;
  if (error) return <div>{error}</div>;

  return (
    <div onClick={onClick}>
      <span>{name}</span>
      <Badge status={status} />
      <span>{revision}</span>
    </div>
  );
}
```

API 연결은 페이지 레벨에서만:

```tsx
// app/review/page.tsx — API는 여기서만
const bundles = await fetchBundles(taskId);

<BundleCard
  name={bundle.name}
  status={bundle.status}
  revision={`v${bundle.version}`}
  isLoading={isLoading}
  error={error}
  onClick={() => router.push(`/review/${bundle.id}`)}
/>
```

---

### 이벤트 핸들러 네이밍

```
컨벤션: on + 명사 + 동사

onBundleClick           ← 번들 클릭
onReviewApprove         ← 승인 버튼
onReviewRequestChanges  ← 변경 요청
onDispatchCopy          ← 복사 버튼
onCommentResolve        ← 댓글 resolve
```

---

### 로딩/에러 슬롯 — 반드시 포함

모든 컴포넌트 props에 아래 두 개 포함:

```tsx
type Props = {
  isLoading: boolean;
  error: string | null;
  // ... 나머지
};

if (isLoading) return <div>로딩 중...</div>;
if (error) return <div>{error}</div>;
```

---

### 목업 데이터 — 파일 하나로 통일

```tsx
// mocks/index.ts
import { Bundle, Task, ReviewRequest } from '@/types';

export const mockBundle: Bundle = {
  id: 'bundle-001',
  taskId: 'task-001',
  title: '결제 실패 핸들러',
  status: 'in_review',
  createdBy: 'user-001',
  createdAt: '2026-04-14T10:00:00Z',
};

export const mockTask: Task = {
  id: 'task-001',
  projectId: 'project-001',
  title: '결제 모듈',
  assigneeId: 'user-001',
  startDate: '2026-04-14',
  endDate: '2026-04-27',
  status: 'in_progress',
};
```

컴포넌트 안에 하드코딩 금지. 무조건 이 파일에서 import.

---

### 컴포넌트 완성 기준

아래 네 개 체크 후 개발자에게 알릴 것:

```
□ props 타입 정의됨 (types/index.ts에서 import)
□ 로딩/에러 상태 처리됨
□ 목업 데이터로 렌더링 확인됨
□ .cursorrules 위반 없음
```

---

## 백엔드

### 절대 쓰지 말 것

```
- req.body 직접 DB에 넣기 (반드시 스키마 파싱 후)
- SELECT * (필요한 컬럼만 명시)
- userId를 body에서 받기 (반드시 세션에서 추출)
- 에러를 그냥 throw (반드시 표준 에러 포맷 함수로)
- 하드코딩된 workspace_id, user_id
- any 타입
```

---

### Zod 입력 검증 스키마

모든 API Route에서 반드시 파싱 후 사용:

```tsx
// schemas/bundle.ts
import { z } from 'zod';

export const CreateBundleSchema = z.object({
  taskId: z.string().uuid(),
  title: z.string().min(1).max(100),
});

export const CreateRevisionSchema = z.object({
  content: z.string().min(1),
  context: z.string().optional(),
  linkedIntentId: z.string().uuid().optional(),
});

export const DispatchSchema = z.object({
  method: z.enum(['copy', 'webhook']),
  presetId: z.string().uuid().optional(),
  destination: z.string().url().optional(),
});

export const ReviewActionSchema = z.object({
  comment: z.string().optional(),
});
```

사용법:

```tsx
// app/api/bundles/route.ts
const body = CreateBundleSchema.parse(await req.json());
// 파싱 실패 시 자동으로 400 응답
```

---

### userId는 세션에서만

```tsx
// 잘못된 것
const userId = req.body.userId;      // ← 클라이언트 조작 가능

// 올바른 것
const { data: { session } } = await supabase.auth.getSession();
const userId = session?.user.id;     // ← 서버가 검증한 값

if (!userId) return forbidden();
```

---

### 표준 응답 포맷

```tsx
// utils/response.ts
export const ok = (data: unknown) =>
  Response.json({ ok: true, data }, { status: 200 });

export const created = (data: unknown) =>
  Response.json({ ok: true, data }, { status: 201 });

export const badRequest = (message: string) =>
  Response.json({ ok: false, error: message }, { status: 400 });

export const forbidden = () =>
  Response.json({ ok: false, error: 'forbidden' }, { status: 403 });

export const notFound = () =>
  Response.json({ ok: false, error: 'not_found' }, { status: 404 });

export const serverError = () =>
  Response.json({ ok: false, error: 'server_error' }, { status: 500 });
```

응답은 이 함수들만 사용.

---

### Bundle 상태 전환 — 중앙 함수 통과 필수

```tsx
// utils/bundleStatus.ts
const VALID_TRANSITIONS: Record<string, string[]> = {
  draft:     ['in_review'],
  in_review: ['approved', 'rejected', 'draft'],
  approved:  [],          // 승인 후 변경 불가
  rejected:  ['draft'],
};

export function assertValidTransition(from: string, to: string) {
  if (!VALID_TRANSITIONS[from]?.includes(to)) {
    throw new Error(`invalid transition: ${from} → ${to}`);
  }
}
```

status 바꾸는 코드 어디서든 반드시 이 함수 먼저 호출.

---

### API Route 기본 구조

```tsx
// app/api/bundles/route.ts
import { CreateBundleSchema } from '@/schemas/bundle';
import { ok, created, badRequest, forbidden, serverError } from '@/utils/response';

export async function POST(req: Request) {
  try {
    // 1. 인증
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) return forbidden();
    const userId = session.user.id;

    // 2. 입력 검증
    const body = CreateBundleSchema.parse(await req.json());

    // 3. 비즈니스 로직
    const bundle = await createBundle({ ...body, createdBy: userId });

    // 4. 표준 응답
    return created(bundle);

  } catch (e) {
    if (e instanceof ZodError) return badRequest(e.message);
    return serverError();
  }
}
```


RLS는 코드에서 권한 체크를 빠뜨려도 DB 레벨에서 막아줍니다.


타입 파일에 없는 타입을 새로 만들지 말고 개발자에게 먼저 물어볼 것.

///////////

## 스마트 컨트랙트 (Solidity)

### 5개 핵심 규칙

```
1. 외부 컨트랙트 호출은 반드시 마지막에 (Checks-Effects-Interactions)
2. msg.sender 검증은 modifier로 분리, 함수 본문에 인라인 금지
3. 금액 계산은 uint256만, 절대 int 혼용 금지
4. 이벤트는 모든 상태 변경마다 반드시 emit
5. 컨트랙트 하나당 책임 하나 (Registry, Vault, Logic 분리)
```

---

### 절대 쓰지 말 것

```
- tx.origin (msg.sender만 사용)
- block.timestamp 단독 난수 (조작 가능)
- delegatecall (storage 레이아웃 충돌 위험)
- selfdestruct (EIP-6780 이후 의미 없음 + 위험)
- address.transfer() / address.send() (2300 gas 제한 문제)
- 루프 안에서 외부 호출
- 검증 없는 abi.encodePacked (해시 충돌 가능 — abi.encode 사용)
- unchecked 블록 남발 (overflow 의도적인 경우만)
```

---

### Checks-Effects-Interactions 패턴

**잘못된 것:**

```solidity
// 재진입 공격 가능
function withdraw(uint256 amount) external {
    require(balances[msg.sender] >= amount);

    (bool ok, ) = msg.sender.call{value: amount}("");  // ← 외부 호출 먼저
    require(ok);

    balances[msg.sender] -= amount;  // ← 상태 변경이 뒤에
}
```

**올바른 것:**

```solidity
function withdraw(uint256 amount) external nonReentrant {
    // 1. Checks
    require(balances[msg.sender] >= amount, "Insufficient balance");

    // 2. Effects
    balances[msg.sender] -= amount;

    // 3. Interactions
    (bool ok, ) = msg.sender.call{value: amount}("");
    require(ok, "Transfer failed");

    emit Withdrawn(msg.sender, amount);
}
```

`nonReentrant` modifier (OpenZeppelin ReentrancyGuard)는 외부 호출 있는 함수에 **무조건** 붙일 것.

---

### Access Control — modifier로만

**잘못된 것:**

```solidity
function registerAsset(bytes32 id, string calldata uri) external {
    require(msg.sender == owner, "Not owner");  // ← 인라인 검증
    require(msg.sender != address(0));
    _register(id, uri);
}
```

**올바른 것:**

```solidity
// modifiers만 모아두는 파일 or 상단 선언
modifier onlyOwner() {
    require(msg.sender == owner, "Not owner");
    _;
}

modifier validAddress(address addr) {
    require(addr != address(0), "Zero address");
    _;
}

function registerAsset(bytes32 id, string calldata uri)
    external
    onlyOwner
    validAddress(msg.sender)
{
    _register(id, uri);
    emit AssetRegistered(id, uri, msg.sender);
}
```

OpenZeppelin `Ownable`, `AccessControl` 쓸 경우 직접 modifier 구현 금지 — 라이브러리 상속만.

---

### 상태 전환 — 중앙 함수 통과 필수

```solidity
// 잘못된 것
function approve(bytes32 assetId) external onlyOwner {
    assets[assetId].status = Status.Approved;  // ← 직접 바꿈
}

// 올바른 것
enum Status { Pending, Approved, Revoked }

mapping(Status => Status[]) private validTransitions;

function _assertValidTransition(Status from, Status to) internal pure {
    if (from == Status.Pending && to == Status.Approved) return;
    if (from == Status.Approved && to == Status.Revoked) return;
    revert("Invalid status transition");
}

function _setStatus(bytes32 assetId, Status to) internal {
    Status from = assets[assetId].status;
    _assertValidTransition(from, to);
    assets[assetId].status = to;
    emit StatusChanged(assetId, from, to);
}
```

status 바꾸는 코드 어디서든 반드시 `_setStatus` 통과.

---

### 이벤트 — 모든 상태 변경마다 필수

```solidity
// 이벤트 선언 (컨트랙트 상단)
event AssetRegistered(bytes32 indexed id, string uri, address indexed registrant);
event StatusChanged(bytes32 indexed id, Status from, Status to);
event OwnershipTransferred(address indexed from, address indexed to);

// emit 누락 시 오프체인 인덱싱 불가 — 반드시 포함
function registerAsset(bytes32 id, string calldata uri) external onlyOwner {
    assets[id] = Asset({ uri: uri, status: Status.Pending, registrant: msg.sender });
    emit AssetRegistered(id, uri, msg.sender);  // ← 필수
}
```

indexed 키워드: 필터링에 쓸 필드 (id, address 류)에 반드시 붙일 것. 최대 3개.

---

### 입력 검증 — require 위치

```solidity
// 모든 public/external 함수 최상단에서 검증
function registerAsset(bytes32 id, string calldata uri) external onlyOwner {
    require(id != bytes32(0), "Empty id");
    require(bytes(uri).length > 0, "Empty URI");
    require(bytes(uri).length <= 2048, "URI too long");
    require(assets[id].registrant == address(0), "Already registered");

    // 검증 통과 후 로직
    _register(id, uri);
}
```

에러 메시지는 반드시 포함. Custom Error 쓸 경우:

```solidity
error AlreadyRegistered(bytes32 id);
error Unauthorized(address caller);

// revert AlreadyRegistered(id); — gas 효율적
```

---

### 크로스체인 수신 함수 (Axelar GMP 연동 시)

```solidity
// 잘못된 것 — 누구나 호출 가능
function _execute(
    string calldata sourceChain,
    string calldata sourceAddress,
    bytes calldata payload
) internal override {
    (address recipient, uint256 amount) = abi.decode(payload, (address, uint256));
    token.transfer(recipient, amount);  // ← sender 검증 없음
}

// 올바른 것
string public trustedSourceChain;
string public trustedSourceAddress;

function _execute(
    string calldata sourceChain,
    string calldata sourceAddress,
    bytes calldata payload
) internal override {
    require(
        keccak256(bytes(sourceChain)) == keccak256(bytes(trustedSourceChain)),
        "Untrusted chain"
    );
    require(
        keccak256(bytes(sourceAddress)) == keccak256(bytes(trustedSourceAddress)),
        "Untrusted sender"
    );

    (address recipient, uint256 amount) = abi.decode(payload, (address, uint256));
    require(recipient != address(0), "Zero recipient");

    token.transfer(recipient, amount);
    emit CrossChainExecuted(sourceChain, recipient, amount);
}
```

---

### 금액 계산

```solidity
// 절대 금지
uint256 fee = amount * 3 / 100;        // ← 정밀도 손실 (먼저 나눔)

// 올바른 것
uint256 fee = (amount * 3) / 100;      // ← 곱셈 먼저

// 퍼센트 계산은 BASIS_POINTS 패턴 권장
uint256 constant BASIS_POINTS = 10_000;
uint256 FEE_BPS = 30;  // 0.3%

uint256 fee = (amount * FEE_BPS) / BASIS_POINTS;
```

---

### 공용 타입 / 상수 파일

```solidity
// types/AssetTypes.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

library AssetTypes {
    enum Status { Pending, Approved, Revoked }
    enum AssetClass { Gold, Diamond, Watch }

    struct Asset {
        bytes32 id;
        string uri;
        address registrant;
        Status status;
        AssetClass class;
        uint256 registeredAt;
    }
}
```

컨트랙트 안에 struct/enum 직접 선언 금지 — 반드시 이 파일에서 import.

---

### 컨트랙트 완성 기준

아래 체크 후 개발자에게 알릴 것:

```
□ 모든 public/external 함수에 입력 검증 있음
□ 외부 호출 있는 함수에 nonReentrant 붙어 있음
□ 모든 상태 변경에 event emit 있음
□ msg.sender 검증이 modifier로 분리됨
□ 크로스체인 수신 함수에 sourceChain/sourceAddress 검증 있음
□ 직접 작성한 타입이 없고 AssetTypes.sol에서 import함
```

///////////

## 설계 원칙 (SOLID & 결합도/응집도)

### 핵심 방향

```
결합도는 낮게 (모듈 간 의존 최소화)
응집도는 높게 (하나의 모듈 = 하나의 책임)
```

---

### 절대 쓰지 말 것

```
- 전역 변수로 모듈 간 상태 공유 (공통 결합)
- public 필드 직접 접근 (내용 결합)
- boolean 플래그를 함수 인자로 넘겨 내부 분기 제어 (제어 결합)
- 하나의 클래스에서 저장 + 출력 + 계산 동시 처리 (단일책임 위반)
- 부모 클래스 메서드를 자식이 throw로 막기 (리스코프 위반)
- 쓰지 않는 인터페이스 메서드를 구현 강제 (인터페이스 분리 위반)
- 고수준 모듈 안에서 저수준 구현체 직접 new (의존역전 위반)
- 새 기능 추가 시 기존 함수 내부 수정 (개방폐쇄 위반)
```

---

### 결합도 — 나쁜 것부터 좋은 것 순서

| 등급 | 이름 | 특징 | 대처 |
|---|---|---|---|
| 최악 | 내용 결합 | 다른 모듈 내부 필드 직접 수정 | private + getter/setter |
| 나쁨 | 공통 결합 | 전역 변수 공유 | 생성자 주입으로 교체 |
| 나쁨 | 제어 결합 | boolean 플래그로 흐름 제어 | 함수 분리 또는 전략 패턴 |
| 보통 | 외부 결합 | 외부 자료구조 직접 참조 | 자료 결합으로 낮추기 |
| 보통 | 스탬프 결합 | 객체 전체를 넘김 | 필요한 필드만 추출해서 넘기기 |
| 좋음 | 자료 결합 | 기본 자료형만 주고받기 | 목표 상태 |

---

### 제어 결합 — 가장 자주 실수하는 패턴

**잘못된 것:**

```java
// boolean 플래그가 함수 내부 흐름을 결정
processor.processData(data, true);  // true가 뭔지 호출부에서 알 수 없음

public void processData(int[] data, boolean isVerbose) {
    if (isVerbose) { System.out.println("started"); }
    // ...
    if (isVerbose) { System.out.println("done"); }
}
```

**올바른 것:**

```java
// 로깅은 별도 클래스가 담당
public class DataProcessor {
    public void processData(int[] data) { /* 순수 처리만 */ }
}

public class DataProcessorLogger {
    private DataProcessor processor;
    public void processWithLogging(int[] data) {
        System.out.println("started");
        processor.processData(data);
        System.out.println("done");
    }
}
```

→ **함수에 boolean 인자가 있으면 제어 결합 의심**. 함수를 두 개로 나누거나 래퍼 클래스를 만들 것.

---

### 응집도 — 낮은 것부터 높은 것 순서

| 등급 | 이름 | 특징 |
|---|---|---|
| 최악 | 우연적 | 연관 없는 기능들이 한 클래스에 |
| 나쁨 | 논리적 | switch/if로 유사한 기능 묶음 |
| 보통 | 시간적 | 초기화처럼 "같은 시점"에 실행 |
| 보통 | 절차적 | 순서대로 여러 기능 호출 |
| 좋음 | 교환적 | 같은 입력을 다른 방식으로 처리 |
| 좋음 | 순차적 | 이전 출력이 다음 입력으로 연결 |
| 최고 | 기능적 | 단 하나의 목적만 |

---

### 논리적 응집도 — switch/if가 신호

**잘못된 것:**

```java
// 새 타입 추가마다 이 함수를 수정해야 함 → 개방폐쇄 원칙 위반
public void handleMessage(String type, String message) {
    switch (type) {
        case "EMAIL": sendEmail(message); break;
        case "SMS":   sendSms(message);   break;
        case "PUSH":  sendPush(message);  break;
    }
}
```

**올바른 것:**

```java
// 타입 추가 시 새 클래스만 추가, 기존 코드 수정 없음
interface MessageSender { void send(String message); }

class EmailSender implements MessageSender { ... }
class SmsSender  implements MessageSender { ... }
class PushSender  implements MessageSender { ... }

// 호출부
MessageSender sender = new EmailSender();
sender.send(message);
```

→ **switch/if로 타입 분기 중이면 인터페이스 분리 + 전략 패턴 적용** 검토.

---

### SOLID — 위반 신호와 대처

**S — 단일 책임**

```
위반 신호: 하나의 클래스가 계산도 하고, 출력도 하고, DB 저장도 함
대처: 역할별로 클래스 분리 (TaxCalculator / InvoicePrinter / InvoiceRepository)
```

**O — 개방 폐쇄**

```
위반 신호: 새 기능 추가할 때 기존 함수 내부를 열어서 else if 추가
대처: 인터페이스 하나 만들고 새 클래스로 확장 (기존 코드 수정 없이)
```

**L — 리스코프 대체**

```
위반 신호: 자식 클래스의 오버라이드 메서드가 throw 던짐
대처: 인터페이스를 분리 (FlyingBird / Bird), 불가능한 동작은 처음부터 계약에 넣지 않기

// 잘못된 것
class Ostrich extends Bird {
    @Override
    public void fly() { throw new UnsupportedOperationException(); }
}

// 올바른 것
interface Bird { void layEggs(); }
interface FlyingBird extends Bird { void fly(); }
class Ostrich implements Bird { ... }       // fly() 없음
class Sparrow implements FlyingBird { ... } // fly() 있음
```

**I — 인터페이스 분리**

```
위반 신호: 인터페이스를 implements하고 나서 일부 메서드를 빈 구현이나 throw로 채움
대처: 인터페이스를 쪼갬. 클라이언트가 쓰는 메서드만 계약에 포함

// 잘못된 것
class RobotWorker implements Worker {
    public void eat() { throw new UnsupportedOperationException(); } // 로봇은 먹지 않음
}

// 올바른 것
interface Workable { void work(); }
interface Eatable  { void eat();  }
class RobotWorker implements Workable { ... }           // eat() 강제 없음
class HumanWorker implements Workable, Eatable { ... }
```

**D — 의존 역전**

```
위반 신호: 고수준 클래스 생성자 안에서 new 저수준구현체() 직접 생성
대처: 인터페이스에 의존하고, 구현체는 생성자 주입으로 외부에서 받기

// 잘못된 것
class Computer {
    private Keyboard keyboard = new Keyboard(); // 구현체에 직접 의존
}

// 올바른 것
class Computer {
    private InputDevice inputDevice; // 인터페이스에 의존
    public Computer(InputDevice inputDevice) { // 외부에서 주입
        this.inputDevice = inputDevice;
    }
}
```

---

### 설계 완성 기준

아래 체크 후 개발자에게 알릴 것:

```
□ 함수 인자에 boolean 플래그가 없음 (제어 결합 없음)
□ public 필드가 없음, 모든 접근은 메서드 경유 (내용 결합 없음)
□ 전역 변수 없음, 상태는 생성자 주입으로 전달 (공통 결합 없음)
□ 하나의 클래스 = 하나의 책임 (계산/출력/저장 분리됨)
□ 새 타입 추가 시 기존 함수를 수정하지 않아도 됨 (switch 분기 없음)
□ 자식 클래스 메서드가 throw를 던지지 않음
□ implements한 인터페이스의 모든 메서드를 실제로 구현함
□ 고수준 클래스 안에서 new 저수준구현체() 없음
```