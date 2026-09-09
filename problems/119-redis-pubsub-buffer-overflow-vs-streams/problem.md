# 119. 실시간 채팅에 Redis Pub/Sub 썼더니 왜 메시지가 몽땅 증발하고 서버가 터져요?!: Redis Pub/Sub의 소방호수 함정(Buffer Overflow) vs Redis Streams 신뢰성 큐(PEL & XACK)

## 문제 설명

실시간 채팅 및 알림 시스템을 구축하기 위해 가장 대중적으로 알려진 **Redis Pub/Sub**을 도입했습니다.  
처음에는 빠르고 가벼워서 잘 작동하는 듯 보였으나, 실제 상용 서비스 오픈 첫날 **두 가지 치명적인 재앙**이 발생했습니다:

1. **오프라인 메시지 영구 증발 (Fire-and-Forget Loss)**:  
   지하철을 타거나 와이파이가 잠깐 끊긴 사용자는 그 순간 발행된 모든 채팅 메시지를 영원히 받지 못하고 공중으로 날려버렸습니다. Redis Pub/Sub은 메시지를 메모리나 디스크에 저장하지 않는 '확성기 방송(소방호수)'이기 때문입니다.
2. **느린 소비자(Slow Consumer)의 버퍼 폭발과 강제 퇴출 (Client Eviction)**:  
   대량의 메시지가 쏟아지는 단체 채팅방에서 특정 스마트폰 클라이언트가 네트워크 지연으로 메시지를 제때 읽지 못하자, Redis 서버의 클라이언트 송신 버퍼(`client-output-buffer-limit`)가 가득 차버렸습니다. Redis는 전체 메모리 고갈을 막기 위해 **해당 클라이언트를 즉시 강제 접속 종료(Evict)**시켜 버렸고, 재접속 폭풍으로 Redis 서버까지 함께 폭사했습니다!

---

### 구원 투수: Redis Streams (Redis 5.0+)

이 문제를 근본적으로 해결하기 위해 도입된 것이 바로 **Redis Streams**입니다.  
Kafka의 장점(Append-Only Log 기반 저장, 오프셋, 컨슈머 그룹)을 Redis의 초고속 인메모리 엔진에 결합했습니다.

- **로그 기반 영구 보존**:  
  발행된 메시지는 `밀리초-순번` 형태의 고유 ID와 함께 스트림에 안전하게 기록됩니다. 수신자가 오프라인이어도 언제든 돌아와 과거 메시지를 읽을 수 있습니다.
- **PEL (Pending Entries List)과 XACK**:  
  컨슈머 그룹의 워커가 메시지를 읽어가면(`XREADGROUP`), 해당 메시지는 그룹의 **보류 목록(PEL)**에 등록됩니다. 워커가 정상적으로 처리를 완료하고 `XACK`를 전송해야만 PEL에서 안전하게 제거됩니다.
- **워커 크래시 자동 복구 (`XCLAIM`)**:  
  만약 특정 워커가 메시지를 가져간 뒤 서버가 다운되어 오랫동안 응답이 없다면, 다른 건강한 워커가 `XCLAIM` 명령을 통해 고아 메시지의 소유권을 가로채어 유실 없이 100% 재처리합니다!

본 문제에서는 전통적인 `PUBSUB` 모드와 신뢰성 있는 `STREAMS` 모드를 모두 지원하는 가상 Redis 브로커를 구현하고 검증합니다.

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG mode=<PUBSUB|STREAMS> buffer_limit_kb=<int> ack_timeout_ms=<int>`
   - 브로커 동작 모드 및 버퍼 한도(기본 32KB), ACK 타임아웃(기본 1000ms)을 설정합니다.
   - 출력: `OK mode=<mode> buffer_limit_kb=<buffer_limit_kb> ack_timeout_ms=<ack_timeout_ms>`

2. **`PUBSUB` 모드 명령어**:
   - `SUBSCRIBE client=<id> channel=<ch>`: 클라이언트가 채널을 구독합니다.  
     출력: `SUBSCRIBED client=<id> channel=<ch>`
   - `UNSUBSCRIBE client=<id> channel=<ch>`: 채널 구독을 해제합니다.  
     출력: `UNSUBSCRIBED client=<id> channel=<ch>`
   - `PUBLISH channel=<ch> msg=<msg> size_kb=<int>`: 메시지를 발행합니다.
     - 구독자가 0명이면 영구 유실: `PUBLISHED channel=<ch> subscribers=0 delivered=0 lost=1`
     - 구독자 버퍼 초과 시 퇴출 먼저 출력: `CLIENT_EVICTED client=<id> error=CLIENT_OUTPUT_BUFFER_LIMIT_EXCEEDED current_buffer_kb=<curr> limit_kb=<limit>`
     - 전체 결과 출력: `PUBLISHED channel=<ch> subscribers=<S> delivered=<D> evicted=<E>`
   - `CONSUME client=<id> count=<int>`: 클라이언트가 버퍼에서 메시지를 소비합니다.  
     출력: `CONSUMED client=<id> count=<C> remaining_buffer_kb=<R>`

3. **`STREAMS` 모드 명령어**:
   - `XADD stream=<str> msg=<str> now=<ms>`: 스트림에 메시지 추가 (ID: `<now>-<seq>`).  
     출력: `XADD_OK stream=<str> id=<id> msg=<msg>`
   - `XGROUP_CREATE stream=<str> group=<grp>`: 컨슈머 그룹 생성.  
     출력: `XGROUP_CREATED stream=<str> group=<grp>`
   - `XREADGROUP stream=<str> group=<grp> consumer=<c> count=<n> now=<ms>`: 메시지 읽기 및 PEL 등록.  
     출력: `XREADGROUP_OK group=<grp> consumer=<c> count=<n> ids=[<id1>,...]`
   - `XACK stream=<str> group=<grp> id=<msg_id>`: 처리 완료 및 PEL 제거.  
     출력: `XACK_OK group=<grp> id=<msg_id>`
   - `XPENDING stream=<str> group=<grp>`: 미완료 보류 목록 조회.  
     출력: `XPENDING_OK group=<grp> pending_count=<P> consumers={<c1>:<cnt>,...}`
   - `XCLAIM stream=<str> group=<grp> new_consumer=<c> min_idle_ms=<ms> now=<ms>`: 장기 미처리 고아 메시지 소유권 탈취.  
     출력: `XCLAIM_OK group=<grp> new_consumer=<c> claimed_count=<cnt> ids=[<id1>,...]`

4. `STATS`: 현재 모드의 누적 통계를 출력합니다.
   - `PUBSUB`: `STATS mode=PUBSUB delivered=<D> lost=<L> evictions=<E>`
   - `STREAMS`: `STATS mode=STREAMS total_messages=<T> acked=<A> pending=<P> claimed=<C>`

5. `RESET`: 모든 상태를 초기화합니다.  
   - 출력: `OK mode=PUBSUB buffer_limit_kb=32 ack_timeout_ms=1000`

---

## 예제 입력 1 (PubSub 모드: 오프라인 유실 & 버퍼 초과 퇴출)

```text
CONFIG mode=PUBSUB buffer_limit_kb=10 ack_timeout_ms=1000
PUBLISH channel=news msg=breaking_news size_kb=2
SUBSCRIBE client=slow_worker channel=jobs
PUBLISH channel=jobs msg=job_1 size_kb=6
PUBLISH channel=jobs msg=job_2 size_kb=6
STATS
```

## 예제 출력 1

```text
OK mode=PUBSUB buffer_limit_kb=10 ack_timeout_ms=1000
PUBLISHED channel=news subscribers=0 delivered=0 lost=1
SUBSCRIBED client=slow_worker channel=jobs
PUBLISHED channel=jobs subscribers=1 delivered=1 evicted=0
CLIENT_EVICTED client=slow_worker error=CLIENT_OUTPUT_BUFFER_LIMIT_EXCEEDED current_buffer_kb=12 limit_kb=10
PUBLISHED channel=jobs subscribers=1 delivered=0 evicted=1
STATS mode=PUBSUB delivered=1 lost=1 evictions=1
```

---

## 예제 입력 2 (Streams 모드: 오프라인 보존 & XACK & XCLAIM)

```text
CONFIG mode=STREAMS buffer_limit_kb=32 ack_timeout_ms=3000
XADD stream=tasks msg=task_critical now=2000
XGROUP_CREATE stream=tasks group=task_workers
XREADGROUP stream=tasks group=task_workers consumer=crashed_worker count=1 now=2100
XPENDING stream=tasks group=task_workers
XCLAIM stream=tasks group=task_workers new_consumer=rescue_worker min_idle_ms=3000 now=5500
XACK stream=tasks group=task_workers id=2000-0
STATS
```

## 예제 출력 2

```text
OK mode=STREAMS buffer_limit_kb=32 ack_timeout_ms=3000
XADD_OK stream=tasks id=2000-0 msg=task_critical
XGROUP_CREATED stream=tasks group=task_workers
XREADGROUP_OK group=task_workers consumer=crashed_worker count=1 ids=[2000-0]
XPENDING_OK group=task_workers pending_count=1 consumers={crashed_worker:1}
XCLAIM_OK group=task_workers new_consumer=rescue_worker claimed_count=1 ids=[2000-0]
XACK_OK group=task_workers id=2000-0
STATS mode=STREAMS total_messages=1 acked=1 pending=0 claimed=1
```\n