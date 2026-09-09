# Problem #161: 대용량 요청 몇 개 받았을 뿐인데 왜 JVM 서버가 30초 동안 멈춰버려요?!: G1GC Humongous Allocation 파편화와 Old Gen 승격 실패(Promotion Failure) vs G1HeapRegionSize & 적응형 IHOP

---

## 🏢 실무 장애 시나리오

커머스 플랫폼의 주문/정산 집계 API 게이트웨이 서비스(Spring Boot 3 + Java 17, G1GC 기본 옵션 적용, 힙 메모리 2GB)는 평소 수만 건의 일반 REST API 요청(평균 30KB)을 5ms 미만의 짧은 지연 시간으로 완벽히 처리하고 있었습니다.

그러던 어느 날, 분기 마감 정산 배치 작업이 시작되면서 **1.2MB 크기의 집계 데이터 페이로드** 수십 개가 시스템으로 유입되었습니다.
잠시 후, 모니터링 대시보드에 끔찍한 알람이 울려 퍼졌습니다:

1. **지연 시간 폭증**: 정상적이던 API 응답 시간이 갑자기 20,000ms(20초) 이상으로 치솟았습니다.
2. **CPU 100% & STW 지옥**: 전체 애플리케이션 스레드가 완전히 멈춘 상태(Stop-The-World)에서 JVM 가비지 컬렉션 스레드가 CPU 100%를 독점했습니다.
3. **쿠버네티스 파드 연쇄 사망**: K8s Liveness Probe 헬스체크(3초 타임아웃)가 연이어 실패하면서 kubelet이 파드를 강제 종료(`SIGKILL`)하고 재시작했습니다. 남은 파드로 트래픽이 집중되면서 서비스 전체가 연쇄 다운(Cascading Failure)되었습니다.

인프라 로그를 분석한 결과, GC 로그에 다음과 같은 치명적인 문구가 기록되어 있었습니다:
```text
[GC concurrent-mark-start]
[GC (Allocation Failure) (To-space Exhausted) [Eden: 0.0B(100.0M)->0.0B(100.0M) Survivors: 0.0B->0.0B Heap: 1980.0M(2048.0M)->1980.0M(2048.0M)], 0.0152300 secs]
[Full GC (Allocation Failure) 1980M->420M(2048M), 21.4325000 secs]
```

힙 크기가 2GB나 되는데, 고작 1.2MB짜리 요청 수십 개 때문에 왜 JVM 전체가 20초 넘게 굳어버리는 Full GC 참사가 발생했을까요?
여러분이 HotSpot G1GC의 메모리 할당 및 컬렉션 엔진을 직접 시뮬레이션하여 참사의 원인을 규명하고, 인프라 튜닝(`-XX:G1HeapRegionSize`)과 애플리케이션 스트리밍 청킹을 통해 무중단 고성능 시스템으로 구원해주세요!

---

## 🎯 문제 설명

주어진 힙 메모리 크기(`heap_size_mb`), G1GC 설정(`config`), 초기 힙 리전 상태(`initial_regions`), 그리고 일련의 메모리 할당 워크로드(`workload`)를 순차적으로 시뮬레이션하여 최종 GC 통계 및 힙 상태 요약 보고서를 반환하는 `solve(input_data)` 함수를 작성하세요.

### 1. G1GC 메모리 및 리전 규칙
- 총 리전 개수: $N = \lfloor \text{heap\_size\_mb} / \text{region\_size\_mb} \rfloor$
- 리전 크기(바이트): $R_{\text{bytes}} = \text{region\_size\_mb} \times 1024 \times 1024$
- **Humongous 임계값**: $H_{\text{thresh}} = \lfloor R_{\text{bytes}} / 2 \rfloor$ (리전 크기의 50%)

### 2. 메모리 할당 규칙
- `streaming_chunk_size_kb > 0`인 경우:
  - 객체를 `streaming_chunk_size_kb * 1024` 바이트 단위의 청크로 분할하여 각각 순차 할당합니다.
- **Humongous 객체** (`size_bytes >= H_thresh`):
  - Eden을 완전히 우회하고 Old Generation에 직접 할당됩니다.
  - 필요한 연속 리전 수: $K = \lceil \text{size\_bytes} / R_{\text{bytes}} \rceil$
  - 내부 단편화 낭비량: $(K \times R_{\text{bytes}}) - \text{size\_bytes}$ 바이트
  - 연속된 빈 리전이 없으면 **`HUMONGOUS_ALLOCATION_FAILURE`**를 원인으로 즉시 **Full GC**를 수행하여 힙을 압축한 뒤 재시도합니다.
  - 마킹 진행 중 여유 리전 수가 부족하면 **`CONCURRENT_MODE_FAILURE`** Full GC가 발생합니다.
- **일반 객체** (`size_bytes < H_thresh`):
  - Eden 영역에 할당됩니다.
  - 현재 활성 Eden 리전에 여유 공간이 있으면 즉시 배치합니다.
  - 공간이 부족하면 새로운 빈 리전을 Eden 리전으로 확보합니다. (최대 Eden 리전 수 초과 시 Young GC 트리거)
  - 빈 리전이 없거나 한도에 도달하면 **Young GC**를 수행합니다.

### 3. 가비지 컬렉션 규칙
- **Young GC**:
  - 만료된 Humongous 객체를 조기 회수(Eager Reclaim)합니다.
  - Eden 및 Survivor 영역을 회수하고, 생존 객체는 나이를 1 증가시켜 Survivor 또는 Old 리전으로 승격시킵니다.
  - 승격 시 여유 리전이 부족하면 **`TO_SPACE_EXHAUSTED`**를 원인으로 즉시 **Full GC**로 전환합니다.
  - STW 정지 시간: 기본 5.0ms + (생존 데이터 MB당 1.0ms)
  - Old Gen 점유율(Old + Humongous 리전 비율)이 `ihop_percent` 이상이면 Concurrent Mark(백그라운드 마킹)를 시작합니다.
- **Full GC**:
  - 힙 전체의 만료된 객체를 완전히 정리하고 살아있는 객체들을 힙 시작 지점부터 Old 리전에 조밀하게 압축(Compaction)합니다.
  - STW 정지 시간: 기본 2,000.0ms + (생존 데이터 MB당 10.0ms)

---

## 📥 입력 형식 (Input Format)

```json
{
  "heap_size_mb": 64,
  "config": {
    "region_size_mb": 1,
    "ihop_percent": 45,
    "max_young_percent": 30,
    "max_tenuring_threshold": 5,
    "marking_duration_ms": 200,
    "streaming_chunk_size_kb": 0
  },
  "initial_regions": [
    {
      "region_index": 0,
      "type": "OLD",
      "objects": [{"id": "cached_0", "size_bytes": 819200, "created_time": 0, "expiry_time": 100000, "age": 10}],
      "used_bytes": 819200
    }
  ],
  "workload": [
    {
      "id": "batch_0",
      "time_ms": 20,
      "size_bytes": 1258291,
      "lifetime_ms": 150
    }
  ]
}
```

---

## 📤 출력 형식 (Output Format)

```json
{
  "young_gc_count": 0,
  "full_gc_count": 1,
  "humongous_allocation_count": 40,
  "humongous_waste_bytes": 33554440,
  "total_stw_pause_ms": 2084.0,
  "max_stw_pause_ms": 2084.0,
  "gc_cause_breakdown": {
    "HUMONGOUS_ALLOCATION_FAILURE": 0,
    "TO_SPACE_EXHAUSTED": 0,
    "CONCURRENT_MODE_FAILURE": 1
  },
  "final_heap_status": {
    "total_regions": 64,
    "used_regions": 30,
    "humongous_regions": 30,
    "free_regions": 34
  }
}
```

---

## 💡 입출력 예시

### 예제 1: 정상 소형 REST 요청 (Case 1 Baseline)
- **입력**: 32MB 힙, 1MB 리전, 250개의 30KB 소형 REST API 요청.
- **결과**: 모든 객체가 512KB 미만이므로 Humongous 할당 0건, Full GC 0건. 빠른 Young GC 2회만으로 10.18ms 총 정지 시간 달성.

### 예제 2: 1.2MB 배치 페이로드 참사 (Case 2 Disaster)
- **입력**: 64MB 힙, 기본 1MB 리전, 40개의 1.2MB 페이로드 유입.
- **결과**:
  - 1.2MB 객체는 리전의 50%(512KB)를 초과하여 40건 전원 Humongous Object로 분류됨.
  - 객체당 2개 리전을 점유하며 838KB의 내부 단편화 낭비 발생 (총 33.5MB 낭비).
  - Old Gen이 폭증하여 `CONCURRENT_MODE_FAILURE` 발생, 2,084ms 동안 전체 시스템 정지(Full GC STW).

---

## ⚙️ 제약 조건 (Constraints)
- $16 \le \text{heap\_size\_mb} \le 4096$
- $\text{region\_size\_mb} \in \{1, 2, 4, 8, 16, 32\}$
- $1 \le N_{\text{workload}} \le 500$
- 모든 부동소수점 출력(`total_stw_pause_ms`, `max_stw_pause_ms`)은 소수점 둘째 자리까지 반올림(`round(x, 2)`).
