# [락 하나 잡으려다 Redis CPU 100% 찍고 서버가 타버렸어요?!: 분산 락(Distributed Lock)과 Redisson Pub/Sub vs Spin-Lock 경합 & Watchdog 만료 시간 자동 연장]

## 1. 장애 시나리오: "선착순 100명 쿠폰 발급에 몰린 1만 명이 부른 Redis 다운과 재고 마이너스 참사"

대규모 선착순 한정 수량 쿠폰 이벤트 오픈 당일, 여러 대의 애플리케이션 서버에서 동시성 제어를 위해 Redis를 이용한 **분산 락(Distributed Lock)**을 적용했습니다.

주니어 개발자는 스프링 부트에서 가장 널리 알려진 `SETNX` (SET if Not eXists) 기반의 스핀 락(Spin Lock) 코드를 작성했습니다:
```java
public void issueCouponWithSpinLock(Long couponId) {
    String lockKey = "lock:coupon:" + couponId;
    // 락을 획득할 때까지 50ms마다 무한 반복 폴링 (Spin Lock)
    while (!redisTemplate.opsForValue().setIfAbsent(lockKey, "locked", Duration.ofSeconds(3))) {
        Thread.sleep(50);
    }
    try {
        // 실제 쿠폰 발급 비즈니스 로직 (외부 API 호출, DB 업데이트 등)
        issueCoupon(couponId);
    } finally {
        redisTemplate.delete(lockKey);
    }
}
```

이벤트 오픈 버튼이 눌리는 순간, 두 가지 치명적인 대재앙이 폭발했습니다:

### 1) 스핀 락 폴링 폭풍과 Redis CPU 100% 사망 (Spin Lock Storm)
1만 명의 유저가 동시에 진입하자, 1만 개의 애플리케이션 스레드가 50ms마다 일제히 `SETNX` 명령을 쏟아부었습니다.
- 초당 무려 **200,000건의 `SETNX` 네트워크 요청**이 단일 Redis 인스턴스로 쇄도했습니다.
- 싱글 스레드로 명령을 순차 처리하는 Redis는 폭발적인 명령 큐 적체로 CPU 사용률 100%를 찍고 응답 불가 상태에 빠졌습니다!

### 2) 작업 지연과 락 조기 만료(Premature Expiration)로 인한 재고 마이너스 참사
- 평소 100ms면 끝나던 쿠폰 발급 작업이, 트래픽 폭주로 인한 외부 PG사 지연 및 DB 락 경합으로 인해 **3,500ms(3.5초)** 동안 지연되었습니다.
- 하지만 개발자가 설정한 락 만료 시간(`leaseTime`)은 고작 3초(3,000ms)였습니다!
- 작업이 아직 덜 끝났는데 3초가 지나자 Redis에서 락이 저절로 삭제되었습니다.
- 대기 중이던 다른 서버의 스레드가 락을 낚아채 동시에 진입해 버렸고, **동일한 한정판 쿠폰이 중복 발급되어 재고가 마이너스로 뚫리는 참사**가 터졌습니다!

시니어 엔지니어의 처방:
> "무지성 `while-sleep` 스핀 락은 레디스를 죽이는 자폭 코드입니다! Redis의 **Pub/Sub 알림 기반 분산 락(Redisson)**으로 대기 부하를 제거하고, 작업이 길어질 때 락을 자동으로 연장해 주는 **워치독(Watchdog)** 타이머를 도입해야 합니다!"

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 `SPIN_LOCK` 방식과 Redisson 스타일의 `REDISSON_PUBSUB` 분산 락 메커니즘을 이산 사건 시뮬레이션으로 모델링합니다.

### (1) 락 획득 및 대기 방식
1. **`SPIN_LOCK` (스핀 락)**:
   - 락 획득 실패 시, `spin_interval_ms` 주기마다 지속적으로 `SETNX` 폴링 명령(1 Redis Command)을 전송합니다.
   - 락이 해제되는 시점에 마침 폴링을 시도한 스레드(들) 중 가장 먼저 도착한 스레드가 락을 획득합니다.
2. **`REDISSON_PUBSUB` (Redisson Pub/Sub)**:
   - 최초 1회 락 획득 시도(1 Command) 후 실패 시, 락 해제 알림을 받기 위해 Redis 채널에 `SUBSCRIBE`(1 Command)하고 대기 상태(Sleep)로 들어갑니다.
   - 락 보유자가 작업을 마치고 락을 해제할 때 `DEL`과 함께 대기자 채널로 `PUBLISH` 알림을 브로드캐스팅합니다 (1 Command).
   - 알림을 수신한 대기 스레드들(FIFO 순서) 중 가장 오래 대기한 스레드가 락 획득(1 Command)에 성공하고, 나머지 대기자들은 시도 실패(각 1 Command) 후 다시 알림을 기다립니다.

### (2) 락 해제 및 워치독(Watchdog) 자동 연장
1. **워치독 비활성화 (`watchdog_enabled == False`)**:
   - 락은 `lease_time_ms` 동안만 유지됩니다.
   - 작업 시간(`work_duration_ms`)이 `lease_time_ms`를 초과하면, 작업이 진행 중이더라도 **락이 강제로 조기 만료(Premature Expiration)**됩니다 (`PREMATURE_EXPIRATIONS += 1`).
   - 락이 조기 만료되면 대기 중이던 다음 스레드가 즉시 락을 획득하여 동시 실행 상태가 발생합니다.
2. **워치독 활성화 (`watchdog_enabled == True`)**:
   - 락 획득 시점부터 작업이 진행되는 동안, 매 `watchdog_interval_ms = lease_time_ms // 3` 마다 백그라운드 워치독이 `PEXPIRE` 갱신 명령(1 Command)을 실행하여 만료 시간을 계속 연장합니다.
   - 따라서 작업이 아무리 오래 걸려도 락이 조기 만료되지 않습니다 (`PREMATURE_EXPIRATIONS` = 0).

---

## 3. 입력 형식

- 첫째 줄에 4개의 파라미터가 공백으로 주어집니다:
  - `mode`: `"SPIN_LOCK"` 또는 `"REDISSON_PUBSUB"`
  - `spin_interval_ms`: 스핀 락 폴링 간격 (정수, $10 \le ms \le 500$)
  - `lease_time_ms`: 락 만료 시간 (정수, $100 \le ms \le 10,000$)
  - `watchdog_enabled`: 워치독 활성화 여부 (`true` 또는 `false`)
- 둘째 줄에 요청 수 $N$ ($1 \le N \le 1,000$)이 주어집니다.
- 셋째 줄부터 $N$개 줄에 걸쳐 각 요청의 정보가 주어집니다:
  - `req_id arrival_time_ms work_duration_ms`

## 4. 출력 형식

- 모든 요청 처리가 완료된 후 다음 4가지 지표를 공백으로 구분하여 한 줄에 출력합니다:
  - `COMPLETED: <완료요청수> REDIS_COMMANDS: <총레디스명령수> PREMATURE_EXPIRATIONS: <조기만료건수> MAX_WAIT_MS: <최대대기시간ms>`

---

## 5. 입출력 예제

### 예제 1 (`SPIN_LOCK` vs 짧은 작업)
#### 입력
```text
SPIN_LOCK 50 3000 false
3
1 0 500
2 10 200
3 20 200
```
#### 출력
```text
COMPLETED: 3 REDIS_COMMANDS: 32 PREMATURE_EXPIRATIONS: 0 MAX_WAIT_MS: 700
```

### 예제 2 (`REDISSON_PUBSUB` vs 동일 시나리오)
#### 입력
```text
REDISSON_PUBSUB 50 3000 false
3
1 0 500
2 10 200
3 20 200
```
#### 출력
```text
COMPLETED: 3 REDIS_COMMANDS: 11 PREMATURE_EXPIRATIONS: 0 MAX_WAIT_MS: 680
```
**비교 분석**:
- 스핀 락은 대기 시간 동안 주기적으로 `SETNX`를 때려 총 32회의 Redis 명령이 폭주했습니다.
- 반면 Redisson Pub/Sub은 이벤트 수신 시에만 시도하므로 명령 수가 11회로 65% 이상 절감되었습니다.
