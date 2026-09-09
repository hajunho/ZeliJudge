# 로그가 부른 침묵의 살인자: 동기 로깅(Sync) vs 비동기 링 버퍼(Async Ring Buffer)

> "디버깅을 위해 추가한 수많은 `logger.info()` 한 줄이,  
> 블랙프라이데이 당일 서버를 침묵 속으로 침몰시키는 가장 날카로운 비수가 된다."

---

## 1. 현실 세계 비유: 수동 톨게이트 vs 하이패스 자동 촬영

추석 연휴 고속도로 톨게이트를 상상해 보세요.

```text
❌ 수동 톨게이트 (동기식 파일 로깅):
   차가 도착할 때마다 톨게이트 직원이 두꺼운 하드커버 장부를 열어
   "12가 3456번 차량 14시 32분 통과"라고 손으로 한 줄 쓰고, 인주 묻혀 도장 찍고,
   캐비닛에 넣고 잠근 뒤에야 차단기를 올려줍니다.
   평소에는 차가 안 밀리지만, 귀성길에 초당 1,000대가 몰려오면?
   톨게이트 앞 50km까지 차량 행렬이 멈춰 서서 엔진이 터지고 도로가 마비됩니다!

✅ 하이패스 & 백그라운드 우편 발송 (비동기 링 버퍼 로깅):
   차가 지나갈 때 고속 카메라가 0.001초 만에 번호판 사진(로그 이벤트)을 찍어
   원형 컨베이어 벨트(링 버퍼)에 툭 던져두고 차단기를 즉시 열어줍니다.
   차량(사용자 HTTP 요청)은 브레이크를 밟을 필요도 없이 쌩쌩 통과합니다.
   뒤편 사무실의 백그라운드 전담 직원(Worker Thread)이 컨베이어 벨트에서
   사진 100장씩 묶음(배치 I/O)으로 꺼내어 여유롭게 장부에 기록합니다.
```

---

## 2. 왜 동기식 로깅(Sync Logging)은 서버를 질식시키는가?

컴퓨터 아키텍처에서 **메모리와 디스크의 물리적 속도 차이**는 상상을 초월합니다.

| 작업 대상 | 소요 시간 | 인간의 시간 감각으로 환산 (1초 = 10억 ns 기준) |
| :--- | :--- | :--- |
| CPU L1 캐시 참조 | 0.5 ns | 0.5초 |
| 메인 메모리 (DRAM) 접근 | 100 ns | 1.7분 |
| NVMe SSD 랜덤 I/O | 100,000 ns (0.1 ms) | **1.1일** |
| 일반 HDD / 네트워크 스토리지 (NFS/EFS) | 10,000,000 ns (10 ms) | **3.8개월** |

### 동기 로깅의 치명적 락 경합
1. 애플리케이션의 톰캣(Tomcat) 스레드가 비즈니스 로직(결제 승인, DB 조회)을 10ms 만에 마쳤습니다.
2. 마지막 줄에 `logger.info("결제 성공: userId={}", userId)`를 만납니다.
3. 동기 로거는 하나의 파일(`app.log`)에 여러 스레드가 동시에 쓸 때 글자가 깨지는 것을 막기 위해 **파일 쓰기 배타락(Synchronized / Mutex Lock)**을 겁니다.
4. 스레드 200개가 동시에 로그를 찍으려 달려들면, 1개 스레드가 디스크 I/O(OS `write()` 및 `fsync()`)를 수행하는 동안 **나머지 199개 스레드는 락을 기다리며 대기 상태(BLOCKED)**에 빠집니다.
5. 결국 톰캣의 200개 스레드 풀이 순식간에 고갈되고, 새로운 HTTP 요청은 큐에 쌓이다가 `Connection Timed Out`으로 전사 장애가 발생합니다!

---

## 3. 비동기 링 버퍼(Ring Buffer)와 LMAX Disruptor의 혁신

비동기 로깅을 구현할 때 흔히 자바의 `ArrayBlockingQueue`나 파이썬의 `Queue`를 떠올립니다.  
하지만 전통적인 큐는 멀티스레드 환경에서 내부적으로 `ReentrantLock`을 사용하여 락 경합과 컨텍스트 스위칭을 유발합니다.

이를 극복하기 위해 금융 거래 초고속 매칭 엔진에서 개발된 기술이 바로 **LMAX Disruptor 링 버퍼(Ring Buffer)**입니다. (Log4j2와 고성능 비동기 로거의 심장)

```mermaid
flowchart LR
    subgraph Producer [애플리케이션 스레드 (HTTP 요청들)]
        T1[Thread 1]
        T2[Thread 2]
        T3[Thread 3]
    end

    subgraph RingBuffer [Lock-Free 원형 링 버퍼 (고정 크기 메모리)]
        Slot0[Slot 0]
        Slot1[Slot 1]
        Slot2[Slot 2]
        Slot3[Slot 3]
        Slot4[Slot ...]
    end

    subgraph Consumer [백그라운드 전담 워커 스레드]
        Worker[Async Worker Thread]
    end

    subgraph Disk [디스크 스토리지]
        BatchIO[배치 묶음 쓰기 app.log]
    end

    T1 -->|Lock-Free CAS| Slot0
    T2 -->|Lock-Free CAS| Slot1
    T3 -->|Lock-Free CAS| Slot2
    Slot0 --> Worker
    Slot1 --> Worker
    Slot2 --> Worker
    Worker -->|한 번에 100건 배치 플러시| BatchIO
```

### 링 버퍼의 3대 초고속 비밀
1. **고정 크기 배열 사전 할당**: 객체를 매번 새로 `new`하지 않고 링 버퍼 슬롯을 미리 재사용하여 가비지 컬렉션(GC) 부하가 전혀 없습니다.
2. **락 프리(Lock-Free) 원자 연산**: 뮤텍스 락 대신 CPU 하드웨어 레벨의 원자적 `AtomicLong` CAS(Compare-And-Swap)로 인덱스를 전진시켜 스레드 블로킹이 없습니다.
3. **배치(Batch) I/O 집약**: 로그를 1개씩 디스크에 쓰지 않고, 링 버퍼에 쌓인 수십~수백 개의 로그를 한 번의 OS `write()` 시스템 콜로 묶어서 씁니다.

---

## 4. 실무 Logback 핵심: 지능형 드롭 정책 (`discardingThreshold`)

비동기 버퍼를 도입하더라도, 초당 수십만 건의 트래픽이 쏟아져 버퍼가 가득 차면 어떻게 해야 할까요?  
이때 백엔드 아키텍처의 생사를 가르는 핵심 설정이 Logback의 `discardingThreshold`와 `neverBlock`입니다.

```text
버퍼 용량 (queueSize = 512)
[-------------------- 80% 안전 구간 --------------------][-- 20% 위험 구간 --]
                                                           ^
                                               discardingThreshold (잔여 20%)
```

- **`discardingThreshold` (기본값: 20%)**:
  - 버퍼의 잔여 공간이 20% 미만으로 떨어지면, 시스템은 비상 모드로 전환됩니다.
  - 디버깅용 로그(`DEBUG`, `INFO`)는 **즉시 쓰레기통에 버립니다(DROP).**
  - 시스템 장애를 알리는 핵심 로그(`WARN`, `ERROR`)만 끝까지 버퍼에 담아 사수합니다.
  - "로그 좀 덜 남더라도, 메인 서비스는 살려야 한다"는 대원칙입니다.

- **`neverBlock` (기본값: false)**:
  - `neverBlock = false` (기본값): 버퍼가 100% 꽉 차면 메인 스레드가 버퍼에 자리가 날 때까지 **다시 블로킹(대기)**됩니다. (결국 동기 로깅과 똑같이 서버 멈춤!)
  - `neverBlock = true`: 버퍼가 꽉 차더라도 메인 스레드를 절대 멈추지 않고 초과 로그를 과감히 폐기하여, **어떤 폭풍 트래픽 속에서도 사용자 결제/응답 속도를 100% 보장**합니다.

---

## 5. 실무 모범 `logback-spring.xml` 설정 템플릿

```xml
<configuration>
    <!-- 1. 실제 파일에 기록하는 롤링 파일 앱렌더 -->
    <appender name="FILE" class="ch.qos.logback.core.rolling.RollingFileAppender">
        <file>logs/app.log</file>
        <rollingPolicy class="ch.qos.logback.core.rolling.TimeBasedRollingPolicy">
            <fileNamePattern>logs/app.%d{yyyy-MM-dd}.log</fileNamePattern>
            <maxHistory>30</maxHistory>
        </rollingPolicy>
        <encoder>
            <pattern>%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n</pattern>
        </encoder>
    </appender>

    <!-- 2. 비동기 링 버퍼 래퍼 (AsyncAppender) -->
    <appender name="ASYNC_FILE" class="ch.qos.logback.classic.AsyncAppender">
        <appender-ref ref="FILE" />
        <queueSize>1024</queueSize>               <!-- 버퍼 크기 -->
        <discardingThreshold>20</discardingThreshold> <!-- 20% 남으면 DEBUG/INFO 드롭 -->
        <neverBlock>true</neverBlock>             <!-- 버퍼 포화 시 메인 스레드 블로킹 금지 -->
        <includeCallerData>false</includeCallerData> <!-- 호출자 스택 트레이스 생성 비용 차단 -->
    </appender>

    <root level="INFO">
        <appender-ref ref="ASYNC_FILE" />
    </root>
</configuration>
```

---

## 6. 요약

> 1. 동기식 파일 로깅은 스레드들이 파일 쓰기 배타락을 잡기 위해 줄을 서다가 **WAS 전체가 얼어붙는 최악의 병목**을 유발한다.
> 2. 비동기 로거(Logback AsyncAppender / LMAX Disruptor)는 **Lock-Free 링 버퍼와 배치 I/O**를 통해 디스크 I/O 횟수를 70~90% 이상 격감시킨다.
> 3. 대규모 장애 상황에서는 `discardingThreshold`와 `neverBlock`을 활용해 **DEBUG/INFO 로그를 과감히 버려 메인 스레드를 지키는 것이 진정한 고가용성 엔지니어링**이다.
