# [분산 락(Distributed Lock) 아키텍처: Redis Spin-Lock의 한계와 Redisson Pub/Sub & Watchdog 메커니즘]

## 1. 분산 환경에서의 상호 배제(Mutual Exclusion)

단일 JVM 애플리케이션에서는 `synchronized`, `ReentrantLock` 등의 언어 레벨 메모리 락으로 스레드 간 동기화를 보장할 수 있습니다.
하지만 클라우드 기반 MSA 환경에서는 애플리케이션 인스턴스가 여러 대(서버 A, B, C)로 스케일아웃되므로, 프로세스 메모리를 벗어난 **중앙 집중식 분산 락(Distributed Lock)**이 필수적입니다.

분산 락의 대표적인 저장소로 초고속 인메모리 NoSQL인 **Redis**가 널리 사용됩니다.

---

## 2. 안티 패턴: 단순 `SETNX` 기반 스핀 락(Spin Lock)의 비극

초보 개발자가 분산 락을 구현할 때 가장 흔히 범하는 실수는 `SETNX` 명령을 루프(`while-sleep`)로 돌리는 스핀 락 방식입니다.

### 스핀 락의 3대 치명적 한계:
1. **Redis CPU 고갈 (Busy-Waiting Thundering Herd)**:
   - 락을 기다리는 수천 개의 스레드가 50ms마다 일제히 `SETNX`를 날립니다.
   - 단일 스레드로 모든 커맨드를 직렬 처리하는 Redis 브로커에 초당 수십만 건의 무의미한 조회가 누적되어 CPU 사용률이 100%로 치솟고, 일반 캐시 조회까지 모조리 타임아웃을 유발합니다.
2. **원자성 결여 (Non-atomic Lock & TTL)**:
   - `SETNX`를 성공한 뒤 `EXPIRE` 명령을 보내기 직전에 서버가 크래시나면, 해당 락은 영원히 지워지지 않는 데드락(Deadlock)에 빠집니다. (현재는 `SET key value NX PX milliseconds`로 원자적 설정이 가능하지만, 스핀 락의 본질적 문제는 해결되지 않습니다.)
3. **타인의 락을 해제하는 위험 (Stolen Lock Release)**:
   - 스레드 A가 작업 지연으로 락이 만료된 후, 스레드 B가 새 락을 쥐었을 때, 뒤늦게 작업이 끝난 스레드 A가 `DEL`을 호출하여 스레드 B의 멀쩡한 락을 지워버리는 레이스 컨디션이 발생합니다.

---

## 3. Redisson의 혁신: Pub/Sub 기반 이벤트 드리븐 락

Java 진영의 표준 Redis 클라이언트인 **Redisson**은 스핀 락의 비효율성을 완벽히 해결하기 위해 **Redis Pub/Sub** 메커니즘을 사용합니다.

```text
[Thread A (락 보유 중)]           [Redis Broker]              [Thread B (대기자)]
        |                               |                            |
        |                               | <--- 1. 락 획득 실패 ------- |
        |                               | <--- 2. SUBSCRIBE 채널 ---- | (Sleep 대기!)
        |                               |                            : (CPU 0% 무부하)
        | --- 3. 작업 완료 (UNLOCK) ---> |                            :
        |        (DEL & PUBLISH)        |                            :
        |                               | --- 4. 락 해제 알림 전송 --> | (Wake Up!)
        |                               | <--- 5. 락 획득 성공 ------- |
```

### 핵심 동작 원리:
1. **구독 후 블로킹 (No Busy-Waiting)**:
   - 락 획득에 실패한 스레드는 `SUBSCRIBE redisson_lock__channel:{resource}` 명령을 통해 세마포어/동기화 락 객체에서 대기합니다.
   - 락이 풀리기 전까지 Redis로 단 1건의 네트워크 요청도 보내지 않습니다.
2. **Lua 스크립트를 통한 원자적 릴리즈 & 발행**:
   ```lua
   if (redis.call('hexists', KEYS[1], ARGV[2]) == 0) then
       return nil;
   end;
   local counter = redis.call('hincrby', KEYS[1], ARGV[2], -1);
   if (counter > 0) then
       redis.call('pexpire', KEYS[1], ARGV[1]);
       return 0;
   else
       redis.call('del', KEYS[1]);
       redis.call('publish', KEYS[2], ARGV[3]);
       return 1;
   end;
   ```
   - 락을 소유한 본인만 해제할 수 있도록 식별자를 검증하고, 락 삭제와 동시에 채널로 알림 메시지를 단일 트랜잭션으로 발행합니다.

---

## 4. 슬로우 쿼리 방어의 수호신: Watchdog(워치독)

분산 락을 걸 때 가장 까다로운 질문은 **"만료 시간(Lease Time)을 몇 초로 줘야 하는가?"**입니다.
- 너무 길게 주면: 서버가 죽었을 때 락이 풀리지 않아 서비스가 오랫동안 멈춥니다.
- 너무 짧게 주면: 네트워크 지연, GC 일시정지, DB 락 경합 등으로 작업이 길어질 때 락이 제멋대로 풀려 다른 스레드가 침범합니다 (재고 마이너스 참사!).

### Redisson Watchdog의 자동 갱신 원리:
1. 개발자가 만료 시간을 명시하지 않으면 기본 30초(`lockWatchdogTimeout`)로 설정됩니다.
2. 백그라운드 타이머 스레드(Netty Timeout)가 구동되어, **만료 시간의 1/3 주기(30초의 경우 매 10초마다)** 현재 작업 스레드가 살아있는지 확인합니다.
3. 작업이 아직 실행 중이라면 Redis로 `PEXPIRE` 명령을 보내 락의 TTL을 다시 30초로 원상 복구 연장합니다.
4. 작업이 정상 종료되어 `unlock()`이 호출되거나, 서버 인스턴스가 물리적으로 다운되어 프로세스가 죽으면 워치독도 함께 소멸하므로, 최대 30초 뒤 락이 자동으로 자연 소멸하여 안전성이 보장됩니다.
