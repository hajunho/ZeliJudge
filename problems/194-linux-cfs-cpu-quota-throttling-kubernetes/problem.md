# Problem 194: 리눅스 CFS CPU 대역폭 스로틀링: cfs_quota_us vs cfs_period_us와 쿠버네티스 멀티스레드 거짓 스로틀링(False Throttling) 방어

## 문제 설명

대규모 쿠버네티스(Kubernetes, K8s) 클러스터에서 마이크로서비스(Java Spring Boot, Go, Node.js)를 운영하는 플랫폼 SRE 엔지니어링 팀은 심각한 미스터리에 직면했습니다.

분명 노드의 실제 CPU 사용률은 20~30%에 불과하고 컨테이너에 할당된 CPU Limit(예: 2 Cores)도 여유가 넘치는데, 컨테이너 내부의 API p99 응답 지연 시간이 평소 5ms에서 **갑자기 80~100ms로 폭발적으로 치솟는 지연 스파이크**가 상시 발생하는 것이었습니다.

`/sys/fs/cgroup/cpu/cpu.stat` 및 프로메테우스 메트릭(`container_cpu_cfs_throttled_periods_total`)을 분석한 결과, 컨테이너가 매 100ms 주기마다 수십 ms씩 얼어붙는 **리눅스 CFS 대역폭 제어기(CFS Bandwidth Controller)의 거짓 스로틀링(False Throttling)**에 걸려 있었습니다.

---

## 핵심 시스템 배경 및 원리

### 1. 리눅스 CFS 대역폭 제어기 (CFS Bandwidth Controller)
쿠버네티스에서 `resources.limits.cpu`를 설정하면, 리눅스 커널의 cgroup cpu 서브시스템에 다음 두 파라미터가 설정됩니다:
- **`cpu.cfs_period_us`**: 기본값 100,000µs (100ms). CPU 할당 주기의 기준 윈도우.
- **`cpu.cfs_quota_us`**: 한 주기 동안 컨테이너가 사용할 수 있는 누적 CPU 시간.
  - 예: `limits.cpu = 2`인 경우, `cfs_quota_us = 200,000µs` (100ms 동안 총 200ms 분량의 CPU 실행 허용).

### 2. 멀티스레드 오버서브스크립션과 거짓 스로틀링 (False Throttling Disaster)
- 호스트 노드가 16코어 또는 32코어 머신일 때, 컨테이너 런타임이나 JVM/Go 런타임(`Runtime.getRuntime().availableProcessors()`)은 컨테이너 Limit이 2코어임에도 불구하고 **호스트의 32개 코어를 인식하여 32개의 워커 스레드**를 생성합니다.
- 신규 요청이나 짧은 배치가 유입되면 8~32개의 스레드가 동시에 실행됩니다.
- 8개 스레드가 단 **25ms** 동안만 병렬 실행되어도:
  $$\text{소비된 누적 CPU 시간} = 8 \text{ threads} \times 25\,\text{ms} = 200\,\text{ms}$$
- 100ms 주기가 시작된 지 불과 **25ms 만에 쿼터(200ms)가 완전히 고갈**됩니다!
- 커널은 컨테이너의 모든 스레드를 **남은 75ms 동안 강제로 일시 정지(Throttled, Uninterruptible Sleep)**시킵니다.
- 실제 현실 시간으로는 1초 중 25%만 일했음에도 불구하고, 멀티스레드 순간 집중에 의해 75ms 동안 서비스가 굳어버리는 참극이 발생합니다(`CFS_FALSE_THROTTLING_LATENCY_SPIKE_DISASTER`).

### 3. 해결책 및 프로덕션 엔지니어링 튜닝
1. **런타임 스레드 풀 정합 (`uber-go/automaxprocs` 등)**:
   - 애플리케이션의 활성 워커 스레드 수를 호스트 코어 수가 아닌 **CFS Quota / Period (할당된 코어 수)에 맞춰 제한**합니다.
   - 2코어 할당 시 2개 스레드만 실행되므로, 쿼터를 순간 조기 소진하지 않고 100ms 전체에 걸쳐 균등하게 실행되어 스톨이 0건으로 사라집니다.
2. **리눅스 5.14+ CFS Burst (`cpu.cfs_burst_us`)**:
   - 이전 주기에서 다 쓰지 않고 남은 쿼터를 버퍼로 저축하여 다음 주기의 일시적 서지 스파이크 시 무스로틀링으로 흡수합니다.
3. **`cfs_period_us` 주기 단축**:
   - 주기를 100ms에서 10ms(`cfs_period_us = 10000`, `cfs_quota_us = 20000`)로 줄여 스로틀링이 걸리더라도 최대 지연 시간을 7~8ms 이내로 억제합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "system": {
    "cfs_period_us": 100000,
    "cfs_quota_us": 200000,
    "cfs_burst_us": 0,
    "app_thread_count": 8,
    "automaxprocs_enabled": true
  },
  "workload": [
    {
      "timestamp_us": 0.0,
      "request_id": "r1",
      "cpu_work_us": 100000
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 형식 결과를 출력합니다.

```json
{
  "status": "SUCCESS",
  "system_config": {
    "cfs_period_us": 100000,
    "cfs_quota_us": 200000,
    "cfs_burst_us": 0,
    "active_threads": 2,
    "automaxprocs_enabled": true
  },
  "metrics": {
    "total_requests": 1,
    "completed_requests": 1,
    "throttled_periods_count": 0,
    "total_throttled_time_us": 0.0,
    "max_request_latency_us": 50000.0,
    "verdict": "OPTIMAL_CFS_AUTOMAXPROCS_TUNED"
  },
  "events_log": [
    {
      "time_us": 50000.0,
      "event": "REQUEST_COMPLETED",
      "request_id": "r1",
      "latency_us": 50000.0,
      "throttled_us": 0.0
    }
  ]
}
```

### 판정 규칙 (Verdict Rules)
1. `throttled_periods_count > 0`이고 `automaxprocs_enabled == false` 및 `cfs_burst_us == 0`:
   - `status = "FAILED"`, `verdict = "CFS_FALSE_THROTTLING_LATENCY_SPIKE_DISASTER"`
2. 스로틀링 스톨이 없거나 automaxprocs / burst 튜닝을 통해 제어된 경우:
   - `status = "SUCCESS"`, `verdict = "OPTIMAL_CFS_AUTOMAXPROCS_TUNED"`
