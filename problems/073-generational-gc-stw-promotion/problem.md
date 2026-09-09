# Problem 073: 세대별 가비지 컬렉션(GC)과 조기 승격 방어 (Generational GC STW Pause vs Premature Promotion Defense)

## 문제 설명

대규모 트래픽을 처리하는 백엔드 결제/인증 서버를 운영하던 팀에 정기적인 서비스 지연 장애가 발생했습니다:
> "평소에는 API 응답 시간이 2~3ms로 매우 쾌적한데, 1분에 한 번꼴로 갑자기 서버 전체가 1초 동안 완전히 꽁꽁 얼어붙습니다(Stop-The-World)!  
> 그 순간 들어온 수천 건의 결제 요청이 모조리 타임아웃되고, 로드밸런서는 헬스체크 실패로 인스턴스를 강제 재부팅시켜 연쇄 장애가 터지고 있습니다!"

이 기괴한 멈춤 현상의 원인은 JVM/V8 등 런타임의 **세대별 가비지 컬렉션(Generational Garbage Collection)** 동작 메커니즘과 **조기 승격(Premature Promotion)** 안티패턴에 있었습니다:
- **약한 세대 가설(Weak Generational Hypothesis)**: 대부분의 객체는 생성된 직후 아주 잠깐 사용되고 바로 쓸모없어지며(단기 객체, short-lived), 소수의 객체(캐시, 전역 설정, 커넥션 풀 등)만이 오랫동안 살아남습니다(장기 객체, long-lived).
- **영역 분리와 GC 비용**:
  - **Young 영역 (Eden, Survivor)**: 단기 객체들을 빠르게 생성하고 가볍게 치우는 공간입니다. 이곳을 청소하는 **Minor GC**는 살아남은 소수 객체만 빠르게 복사하므로 일시정지(STW) 시간이 매우 짧습니다 (수 ms 단위).
  - **Old 영역**: 여러 번 살아남은 장기 객체들이 머무는 공간입니다. 이곳이 꽉 차면 힙 전체를 전수 조사하는 **Full GC**가 발생하여 서버의 모든 애플리케이션 스레드가 멈추는 극심한 STW 지연(수십 ms ~ 수 초)이 발생합니다.
- **조기 승격(Premature Promotion)의 비극**:
  - 만약 중간 완충 지대인 **Survivor 영역**의 크기를 너무 작게 설정해두면(`SURVIVOR_CAP_NAIVE`), Eden에서 생존한 객체들이 Survivor에 다 들어가지 못하고 곧바로 Old 영역으로 넘어가 버립니다.
  - 원래대로라면 조금 뒤 사망했을 단기 객체들이 Old 영역에 잔뜩 쌓이게 되고, 결국 Old 영역이 금세 포화되어 **빈번한 Full GC 폭풍(Full GC Storm)**을 유발합니다.

레스토랑에 비유하자면, 테이블 위 일회용 냅킨과 빈 접시는 알바생이 카트에 담아 즉시 쓰레기통에 버려야 합니다(Minor GC). 그런데 카트(Survivor)가 너무 비좁아 일회용 냅킨 더미를 지하 메인 창고(Old)로 매번 실어 나르는 바람에, 창고가 쓰레기로 가득 차 영업을 전면 중단하고 전 직원이 창고 대청소(Full GC STW)를 벌이는 셈입니다!

당신은 동일한 메모리 할당 스트림에 대해 작은 Survivor 공간을 가진 **Naive GC 엔진**과 최적화된 Survivor 공간을 가진 **Tuned GC 엔진**을 시뮬레이션하여, 조기 승격 방지와 STW 지연시간 절감 효과를 검증하는 GC 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 힙 메모리 및 세대 모델
- **Eden 영역 (`EDEN_CAP_MB`)**: 모든 신규 객체(단기 및 장기)가 최초로 할당되는 공간.
- **Survivor 영역 (`SURVIVOR_CAP_NAIVE`, `SURVIVOR_CAP_TUNED`)**: Eden에서 1회 이상 살아남은 객체가 임시 보관되는 완충 공간.
- **Old 영역 (`OLD_CAP_MB`)**: 성숙한 장기 객체가 영구 보관되는 공간.
- **Tenuring Threshold (`TENURING_THRESHOLD`)**: 객체가 Old 영역으로 정식 승격되기 위해 Survivor 영역에서 생존해야 하는 기준 나이(Age).

---

### 2. 가비지 컬렉션(GC) 메커니즘

#### 1) Minor GC 동작 조건 및 절차
- 신규 트래픽 할당(`ALLOC_TRAFFIC short_mb long_mb`) 시 `Eden_used + short_mb + long_mb > EDEN_CAP_MB`인 경우 즉시 **Minor GC**가 트리거됩니다.
- Minor GC 수행 절차:
  1. `minor_gc_count += 1`, `total_stw_ms += MINOR_GC_STW_MS`
  2. **사망 판정 및 나이 증가**:
     - Eden의 단기 객체(`is_long == False`)는 즉시 사망(소멸).
     - Eden의 장기 객체(`is_long == True`)는 생존하며 `age += 1`.
     - Survivor의 객체들은 `age += 1`. 단기 객체 중 이미 Survivor에 머물렀던 객체(`age >= 2`)는 사망(소멸).
  3. **정식 승격 (Natural Promotion)**:
     - 생존 객체 중 `age >= TENURING_THRESHOLD`인 객체는 Old 영역으로 이동.
  4. **Survivor 수용 및 조기 승격 (Premature Promotion)**:
     - 미승격 생존 객체들을 순서대로 Survivor 영역에 배치.
     - Survivor 잔여 용량(`SURVIVOR_CAP`)을 초과하는 객체는 Old 영역으로 **조기 승격(Premature Promotion)**되며, 초과된 크기만큼 `premature_promoted_mb` 누적.
  5. Eden 영역은 0MB로 완전히 비워집니다.
  6. Minor GC 후 Old 영역 사용량이 `OLD_CAP_MB`를 초과하면 즉시 **Full GC**가 연쇄 트리거됩니다.

#### 2) Full GC 동작 조건 및 절차
- Old 영역 사용량이 `OLD_CAP_MB`를 초과하거나 수동 명령(`FORCE_FULL_GC`) 수신 시 트리거됩니다.
- Full GC 수행 절차:
  1. `full_gc_count += 1`, `total_stw_ms += FULL_GC_STW_MS`
  2. Old 영역 전수 조사: Old 영역에 잘못 들어온 모든 단기 객체(`is_long == False`)를 메모리에서 즉시 소멸/회수. 장기 객체만 Old에 잔류.

---

### 3. 액션 명세

#### 1) `ALLOC_TRAFFIC <cycle_id> <short_mb> <long_mb>`
- 신규 트래픽 객체 할당.
- 필요시 Minor GC (및 연쇄 Full GC) 실행 후 Eden에 객체 할당.
- 출력 (3줄):
  ```text
  ACT <idx> ALLOC_TRAFFIC CYCLE:<cycle_id> SHORT:<short_mb>MB LONG:<long_mb>MB
    NAIVE: EDEN:<eden>MB SURV:<surv>MB/<surv_cap>MB OLD:<old>MB/<old_cap>MB [이벤트...]
    TUNED: EDEN:<eden>MB SURV:<surv>MB/<surv_cap>MB OLD:<old>MB/<old_cap>MB [이벤트...]
  ```
  *(단, 해당 엔진에서 GC나 조기 승격 이벤트가 발생한 경우에만 대괄호 안에 `MINOR_GC:<cnt>`, `FULL_GC:<cnt>`, `PREMATURE_PROMOTED:<mb>MB` 형태로 공백 구분하여 표시)*

#### 2) `FORCE_FULL_GC`
- 수동 Full GC 실행.
- 출력 (3줄):
  ```text
  ACT <idx> FORCE_FULL_GC
    NAIVE: FULL_GC_EXECUTED OLD_USED:<old_used>MB/<old_cap>MB
    TUNED: FULL_GC_EXECUTED OLD_USED:<old_used>MB/<old_cap>MB
  ```

#### 3) `CHECK_GC_METRICS`
- 현재 시점의 GC 누적 지표 점검.
- 상태(STATUS) 판정:
  - `old_used > old_cap`인 경우: `OOM`
  - Naive 엔진에서 `full_gc_count >= 3`인 경우: `FULL_GC_STORM`
  - 그 외: `HEALTHY`
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_GC_METRICS
    NAIVE: MINOR_GC:<cnt> FULL_GC:<cnt> TOTAL_STW:<stw>ms PROMOTED_MB:<mb>MB STATUS:<status>
    TUNED: MINOR_GC:<cnt> FULL_GC:<cnt> TOTAL_STW:<stw>ms PROMOTED_MB:<mb>MB STATUS:<status>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
EDEN_CAP_MB <eden_cap>
SURVIVOR_CAP_NAIVE <s_naive>
SURVIVOR_CAP_TUNED <s_tuned>
OLD_CAP_MB <old_cap>
TENURING_THRESHOLD <threshold>
MINOR_GC_STW_MS <minor_ms>
FULL_GC_STW_MS <full_ms>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_TRAFFIC_CYCLES:<total_cycles>
SUMMARY NAIVE TOTAL_STW_PAUSE:<tot_stw>ms (MINOR_GC:<min_cnt>, FULL_GC:<full_cnt>) PREMATURE_PROMOTED:<prom_mb>MB
SUMMARY TUNED TOTAL_STW_PAUSE:<tot_stw>ms (MINOR_GC:<min_cnt>, FULL_GC:<full_cnt>) PREMATURE_PROMOTED:<prom_mb>MB
SUMMARY STW_LATENCY_SAVED:<saved_ms>ms (PAUSE_REDUCTION:<pct:.2f>%)
SUMMARY TUNING_VERDICT: TUNED_PREVENTS_STW_STORM
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
EDEN_CAP_MB 100
SURVIVOR_CAP_NAIVE 20
SURVIVOR_CAP_TUNED 80
OLD_CAP_MB 200
TENURING_THRESHOLD 3
MINOR_GC_STW_MS 2
FULL_GC_STW_MS 50

ACTIONS
ALLOC_TRAFFIC T1 60 10
ALLOC_TRAFFIC T2 50 10
ALLOC_TRAFFIC T3 60 10
ALLOC_TRAFFIC T4 50 10
ALLOC_TRAFFIC T5 60 10
CHECK_GC_METRICS
```

**출력:**
```text
ACT 1 ALLOC_TRAFFIC CYCLE:T1 SHORT:60MB LONG:10MB
  NAIVE: EDEN:70MB SURV:0MB/20MB OLD:0MB/200MB
  TUNED: EDEN:70MB SURV:0MB/80MB OLD:0MB/200MB
ACT 2 ALLOC_TRAFFIC CYCLE:T2 SHORT:50MB LONG:10MB
  NAIVE: EDEN:60MB SURV:10MB/20MB OLD:0MB/200MB [MINOR_GC:1]
  TUNED: EDEN:60MB SURV:10MB/80MB OLD:0MB/200MB [MINOR_GC:1]
ACT 3 ALLOC_TRAFFIC CYCLE:T3 SHORT:60MB LONG:10MB
  NAIVE: EDEN:70MB SURV:10MB/20MB OLD:0MB/200MB [MINOR_GC:1]
  TUNED: EDEN:70MB SURV:20MB/80MB OLD:0MB/200MB [MINOR_GC:1]
ACT 4 ALLOC_TRAFFIC CYCLE:T4 SHORT:50MB LONG:10MB
  NAIVE: EDEN:60MB SURV:10MB/20MB OLD:10MB/200MB [MINOR_GC:1 PREMATURE_PROMOTED:10MB]
  TUNED: EDEN:60MB SURV:30MB/80MB OLD:0MB/200MB [MINOR_GC:1]
ACT 5 ALLOC_TRAFFIC CYCLE:T5 SHORT:60MB LONG:10MB
  NAIVE: EDEN:70MB SURV:10MB/20MB OLD:10MB/200MB [MINOR_GC:1]
  TUNED: EDEN:70MB SURV:30MB/80MB OLD:10MB/200MB [MINOR_GC:1]
ACT 6 CHECK_GC_METRICS
  NAIVE: MINOR_GC:4 FULL_GC:0 TOTAL_STW:8ms PROMOTED_MB:10MB STATUS:HEALTHY
  TUNED: MINOR_GC:4 FULL_GC:0 TOTAL_STW:8ms PROMOTED_MB:0MB STATUS:HEALTHY
SUMMARY TOTAL_TRAFFIC_CYCLES:5
SUMMARY NAIVE TOTAL_STW_PAUSE:8ms (MINOR_GC:4, FULL_GC:0) PREMATURE_PROMOTED:10MB
SUMMARY TUNED TOTAL_STW_PAUSE:8ms (MINOR_GC:4, FULL_GC:0) PREMATURE_PROMOTED:0MB
SUMMARY STW_LATENCY_SAVED:0ms (PAUSE_REDUCTION:0.00%)
SUMMARY TUNING_VERDICT: TUNED_PREVENTS_STW_STORM
```
