# #058 배송 완료된 상품이 왜 '결제 대기'로 되돌아가요?!: 네트워크 패킷 지연과 시퀀스 번호 재정렬 버퍼 (Out-of-Order Delivery & Reordering Buffer)

---

## 1. 현실 세계 비유: 수제버거 공정의 번호표 거치대

수제버거 전문점에서 햄버거 1개를 완성하는 5단계 공정을 상상해 보세요.

```text
[정상적인 햄버거 제조 순서]
1번 상자: 빵(번) 굽기
2번 상자: 쇠고기 패티 굽고 올리기
3번 상자: 치즈와 양상추 얹기
4번 상자: 특제 소스 뿌리고 뚜껑 덮기
5번 상자: 예쁜 종이에 포장해서 손님에게 출하
```

식재료 배달 기사 5명이 각각 다른 오토바이를 타고 출발했는데, 도로 교통 체증 때문에 매장에 **1번 $\to$ 4번 $\to$ 5번 $\to$ 2번 $\to$ 3번** 순서로 뒤죽박죽 도착했습니다!

```text
❌ 멍청한 알바생 (NAIVE):
   1. 1번 상자(빵)가 오자 빵을 굽습니다. (상태: 빵 완성)
   2. 4번 상자(소스)가 오자 구운 빵 위에 소스를 들이붓습니다! (상태: 소스 투하, 패티/치즈 건너뜀)
   3. 5번 상자(포장지)가 오자 소스 묻은 빵을 포장지에 싸서 '배달 완료' 도장을 쾅 찍어버립니다! (상태: 출하 완료)
   4. 10분 뒤, 뒤늦게 2번(패티) 상자가 도착했습니다.
   5. 알바생은 이미 포장된 햄버거를 다시 뜯어 패티를 쑤셔 넣으며, 주문 상태를 "출하 완료"에서 다시 "패티 굽는 중"으로 되돌려버립니다!
   6. 결과: 햄버거는 곤죽이 되었고, 물류 시스템은 이미 배송 완료된 상품을 '결제 대기'로 되돌려 2중 발송하는 대형 사고가 터집니다!

✅ 베테랑 주방장 (BUFFERED - 재정렬 버퍼):
   1. 주방장은 번호표 거치대(Reordering Buffer)를 마련해 둡니다.
   2. 1번 상자(빵)가 오자 빵을 굽습니다. "다음은 2번 차례다!" (next_expected = 2)
   3. 4번(소스)과 5번(포장지)이 먼저 오자, "어? 2번 패티가 아직 안 왔네!" 하고 거치대 선반에 잠시 킵(BUFFERED)해 둡니다.
   4. 드디어 2번(패티) 상자가 도착합니다!
   5. 2번 패티를 올리고(next_expected = 3), 거치대를 보니 이미 3번(치즈), 4번(소스), 5번(포장지)이 기다리고 있습니다.
   6. 거치대에서 3, 4, 5번을 연속으로 꺼내(DRAIN) 0.1초 만에 완벽한 수제버거를 완성합니다!
```

---

## 2. 문제 개요

당신은 대규모 이커머스 및 분산 물류 스트리밍 시스템의 플랫폼 엔지니어입니다.  
네트워크 라우팅 지연, 멀티스레드 워커 비동기 처리, 패킷 재전송 등으로 인해 메시지 스트림이 보낸 순서대로 도착하지 않고 비순서(Out-of-Order)로 유입됩니다.

이때,
1. 들어오는 순서대로 무조건 상태를 갱신하는 **단순 수신 모델(NAIVE)**과
2. 단조 증가 시퀀스 번호와 슬라이딩 윈도우 기반 **재정렬 버퍼 모델(BUFFERED)**

두 아키텍처의 동작 과정을 시뮬레이션하고, 상태 역전(`REGRESSIONS`) 및 단계 건너뛰기(`JUMPS`) 등 데이터 이상 현상 방어율(`ANOMALIES_PREVENTED`)을 정밀 계측하세요.

---

## 3. 입력 형식

표준 입력(`sys.stdin`)으로 시스템 설정과 이벤트 스트림이 주어집니다.

```text
BUFFER_TIMEOUT_MS <timeout_ms>
MAX_BUFFER_SIZE <max_size>
EVENTS
<ev_id> <channel_id> <seq> <state> <timestamp>
<ev_id> <channel_id> <seq> <state> <timestamp>
...
```

### 파라미터 규격
- `BUFFER_TIMEOUT_MS <timeout_ms>`: 누락된 패킷을 기다리는 최대 버퍼링 대기 시간 (ms 단위 정수, 기본값 `1000`).
- `MAX_BUFFER_SIZE <max_size>`: 채널당 메모리 버퍼에 보관 가능한 최대 이벤트 수 (정수, 기본값 `100`).
- `EVENTS`: 비동기 수신된 이벤트 목록.
  - `ev_id`: 고유 이벤트 식별자 문자열 (예: `e1`, `e2`).
  - `channel_id`: 채널/주문/세션 식별자 문자열 (예: `ch1`, `ord_A`).
  - `seq`: 채널 내에서 1부터 단조 증가하는 시퀀스 번호 ($1, 2, 3, \dots$).
  - `state`: 전이될 상태 문자열 (예: `CREATED`, `PAID`, `SHIPPED`, `DELIVERED`).
  - `timestamp`: 이벤트가 서버에 도달한 시각 (ms 단위 정수, $\ge 0$).

---

## 4. 시뮬레이션 상세 규칙

모든 이벤트는 도달 시각(`timestamp`) 순서대로 처리됩니다. (시각이 같을 경우 입력 파일 등장 순서 기준).

### 모델 A: 단순 수신 모델 (NAIVE)
- 채널별로 마지막으로 처리한 시퀀스 번호 `last_seq` (초기값 0)를 유지합니다.
- 이벤트 `(seq, state)` 도착 시:
  - **`seq <= last_seq`인 경우**:
    - 이미 더 최신 번호를 처리했는데 과거 번호가 도착한 상황입니다!
    - $\to$ 상태 역전 이상 현상 발생! `naive_inversions += 1`, 상태: `REGRESSION`.
  - **`seq > last_seq + 1`인 경우**:
    - 중간 단계의 시퀀스를 건너뛰고 미래 상태로 점프한 상황입니다!
    - $\to$ 단계 건너뛰기 이상 현상 발생! `naive_jumps += 1`, 상태: `JUMPED`.
    - `last_seq = seq`로 갱신.
  - **`seq == last_seq + 1`인 경우**:
    - 완벽하게 순차 도착함.
    - $\to$ 정상 처리. `naive_processed += 1`, 상태: `PROCESSED`.
    - `last_seq = seq`로 갱신.

### 모델 B: 재정렬 버퍼 모델 (BUFFERED)
- 채널별로 다음 기대 시퀀스 `next_expected = 1`과 메모리 버퍼(`buffer`), 글로벌 타임아웃 큐를 유지합니다.
- **글로벌 타임아웃 처리**:
  - 이벤트 시각 `T`에 도달했을 때, 임의의 채널 버퍼에서 **가장 오래된 패킷의 대기 시간(`T - oldest_timestamp >= BUFFER_TIMEOUT_MS`)이 초과된 경우**:
    - 기다리던 중간 패킷이 영구 유실(Packet Loss)된 것으로 판정합니다 (Head-of-Line Blocking 방지).
    - `timeout_gaps += (버퍼_최소_seq - next_expected)`.
    - `next_expected`를 버퍼에 존재하는 가장 작은 시퀀스 번호로 강제 점프시키고, 연속된 시퀀스들을 즉시 연쇄 드레인(`drained_count += 1`)합니다.
- **이벤트 수신 처리**:
  - **1) `seq < next_expected` (지연 도착 패킷)**:
    - 이미 처리되었거나 타임아웃으로 건너뛴 과거 패킷입니다. 상태 오염을 방지하기 위해 안전하게 버립니다.
    - $\to$ `dropped_stale_count += 1`, 상태: `DROPPED_STALE`.
  - **2) `seq == next_expected` (정규 도착 패킷)**:
    - 기다리던 번호가 도착했습니다! `next_expected += 1`.
    - 직후 버퍼를 확인하여, 퍼즐이 맞춰진 연속된 번호(`next_expected, next_expected+1, ...`)를 버퍼에서 연속으로 꺼내어 일괄 처리(`drained_count += K`)합니다.
    - $\to$ 꺼낸 아이템이 없으면 `PROCESSED`, $K$개 꺼냈으면 `PROCESSED(DRAINED:K)`.
  - **3) `seq > next_expected` (선행 도착 패킷)**:
    - 앞선 패킷이 지연되고 있으므로 버퍼에 보관합니다.
    - 만약 버퍼에 담긴 개수가 `MAX_BUFFER_SIZE`에 도달했다면:
      - $\to$ 버퍼 초과 폐기! `overflow_dropped += 1`, 상태: `BUFFER_FULL_DROPPED`.
    - 여유가 있다면:
      - $\to$ 버퍼링 완료. `buffered_count += 1`, 상태: `BUFFERED`.

---

## 5. 출력 형식

표준 출력(`sys.stdout`)으로 각 이벤트의 판정 결과와 최종 요약 통계를 출력합니다.

```text
EVENT <ev_id> NAIVE:<naive_status> BUFFERED:<buf_status>
...
SUMMARY NAIVE PROCESSED:<naive_processed> REGRESSIONS:<naive_inversions> JUMPS:<naive_jumps>
SUMMARY BUFFERED BUFFERED:<buffered_count> DRAINED:<drained_count> DROPPED_STALE:<dropped_stale_count> TIMEOUT_GAPS:<timeout_gaps> OVERFLOW_DROPPED:<overflow_dropped>
SUMMARY ANOMALIES_PREVENTED:<naive_inversions + naive_jumps>
```

---

## 6. 입출력 예시

### 예시 입력
```text
BUFFER_TIMEOUT_MS 1000
MAX_BUFFER_SIZE 100
EVENTS
e1 ch1 1 CREATED 100
e2 ch1 3 SHIPPED 120
e3 ch1 4 DELIVERED 130
e4 ch1 2 PAID 150
```

### 예시 출력
```text
EVENT e1 NAIVE:PROCESSED BUFFERED:PROCESSED
EVENT e2 NAIVE:JUMPED BUFFERED:BUFFERED
EVENT e3 NAIVE:PROCESSED BUFFERED:BUFFERED
EVENT e4 NAIVE:REGRESSION BUFFERED:PROCESSED(DRAINED:2)
SUMMARY NAIVE PROCESSED:2 REGRESSIONS:1 JUMPS:1
SUMMARY BUFFERED BUFFERED:2 DRAINED:2 DROPPED_STALE:0 TIMEOUT_GAPS:0 OVERFLOW_DROPPED:0
SUMMARY ANOMALIES_PREVENTED:2
```

### 결과 해석
- **NAIVE 모델**:
  - `e2(seq 3)`가 2번을 건너뛰고 도착하여 `JUMPED` 발생 (중간 상태 누락).
  - `e4(seq 2)`가 뒤늦게 도착하여 배송 완료(`DELIVERED`)된 주문을 다시 결제 완료(`PAID`)로 덮어쓰는 `REGRESSION` 대형 참사 발생! (이상 현상 총 2건).
- **BUFFERED 모델**:
  - `e2`와 `e3`를 버퍼에 킵해두고 있다가, `e4(seq 2)`가 도착하자마자 순서대로 2 $\to$ 3 $\to$ 4로 연쇄 드레인하여 100% 정상 순서로 처리 완료! (상태 역전 2건 완벽 방어).

---

## 7. 제약 조건 및 복잡도 요구사항
- 총 이벤트 수 $E \le 100,000$.
- 채널 수 $C \le 1,000$.
- 우선순위 큐(힙)를 활용하여 $O(E \log E)$ 이하의 시간 복잡도로 5.0초 제한 시간 내에 통과해야 합니다.
