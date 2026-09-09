# Problem 210: 100GbE 네트워크 달아놓고 왜 브로커 전송 속도가 1Gbps도 안 나와요?!: 분산 메시징 Kafka: OS 페이지 캐시와 Linux sendfile(2) Zero-Copy vs 유저 공간 버퍼 복사 및 지연 컨슈머 캐시 스래싱 방어 (Kafka Storage: Zero-Copy sendfile vs User-Space Buffer Overhead & Page Cache Thrashing)

## 문제 배경 및 개요

대규모 실시간 데이터 스트리밍 플랫폼(Apache Kafka, Redpanda, Apache Pulsar)을 운영하는 데이터 플랫폼 엔지니어링 팀은 $100\,\text{Gbps}$ 고속 광 네트워크(100GbE NIC)와 최신 NVMe 스토리지 풀을 갖춘 카프카 브로커 클러스터를 구축했습니다.

이론상 브로커 1대가 초당 $40 \sim 80\,\text{Gbps}$($5 \sim 10\,\text{GB/s}$)의 메시지 소비 트래픽을 처리해야 하지만, 프로덕션 환경에서 다음과 같은 **치명적인 성능 붕괴 및 지연시간 폭발 재앙**이 번갈아 발생했습니다:

```
[시나리오 A: 레거시 유저 공간 버퍼링 (read + write)]
프로듀서/컨슈머 트래픽 유입 (40 Gbps 요청)
          │
          ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ 전통적인 I/O 방식: 4회 컨텍스트 스위치, 4회 데이터 복사    │
   │ Disk -> OS Page Cache (DMA) -> JVM Buffer (CPU memcpy)     │
   │ JVM Buffer -> OS Socket Buffer (CPU memcpy) -> NIC (DMA)    │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
[CPU 메모리 버스 포화 & 컨텍스트 스위칭 폭풍]
- CPU 사용률 98.5% (usr/sys 100% 포화)
- 100GbE 네트워크를 달아놓고 실제 전송 대역폭은 고작 12 Gbps로 병목! (88% 네트워크 낭비!)

---

[시나리오 B: Zero-Copy sendfile + 지연 컨슈머(Lagging Consumer)의 습격]
리눅스 sendfile(2) Zero-Copy 도입으로 40 Gbps를 CPU 4.8%로 완벽 처리 중!
그런데...
24시간 동안 멈춰 있던 배치 분석 컨슈머가 128 GB의 콜드 세그먼트 데이터를 일괄 조회 시작!
          │
          ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ 페이지 캐시 스래싱 (Page Cache Thrashing) 발생!             │
   │ 128 GB의 콜드 데이터가 64 GB Page Cache의 핫 세그먼트를 전량 밀어냄 │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
[실시간 컨슈머들의 동반 추락]
- 페이지 캐시 적중률(Hit Rate): 99.2% ───> 22.4% 로 대폭락!
- 실시간 컨슈머마저 메모리에서 못 읽고 NVMe 디스크 I/O 큐에 갇힘!
- 응답 지연시간 0.12ms ───> 48ms 로 400배 폭증!
- 프로듀서 쓰기 Ack 지연시간 동반 상승으로 클러스터 전체 연쇄 장애!
```

이 참사의 이면에는 운영체제 I/O 서브시스템과 메시지 브로커 아키텍처의 핵심 원리가 숨어 있습니다:
1. **레거시 유저 공간 버퍼 복사의 한계**: `read()`와 `write()` 시스템 콜을 사용하는 전통적인 방식은 데이터 1바이트를 전송할 때마다 4번의 컨텍스트 스위칭과 2번의 CPU 메모리 복사(`memcpy`)를 유발합니다. $100\,\text{Gbps}$ 전송 시 메모리 버스 대역폭을 $200\,\text{Gbps}$ 이상 낭비하며 CPU가 포화되어 처리량이 $12\,\text{Gbps}$ 천장에 갇힙니다 (`USER_SPACE_BUFFER_CPU_MEMCPY_BOTTLENECK`).
2. **리눅스 `sendfile(2)`과 DMA Scatter-Gather Zero-Copy**: OS 커널의 `sendfile(2)`(Java `FileChannel.transferTo()`)은 유저 공간 메모리를 전혀 거치지 않고, OS 페이지 캐시의 버퍼 디스크립터를 소켓 버퍼로 직접 전달한 뒤 네트워크 카드가 Scatter-Gather DMA로 페이지 캐시 메모리를 직접 읽어 유선으로 전송합니다. 2번의 컨텍스트 스위치와 0번의 CPU 복사로 $80\,\text{Gbps}$를 CPU $10\%$ 미만으로 처리합니다.
3. **지연 컨슈머와 페이지 캐시 스래싱 (Page Cache Thrashing)**: 그러나 Zero-Copy 브로커라도 64GB 용량의 페이지 캐시를 가진 상태에서 지연된 컨슈머가 128GB의 과거 디스크 데이터를 무분별하게 읽어들이면, 실시간 컨슈머들이 점유하고 있던 핫 파티션 헤드 캐시가 강제 축출(Eviction)되어 디스크 I/O 병목이 발생합니다 (`PAGE_CACHE_THRASHING_COLD_CONSUMER_STORM`).
4. **캐시 격리 (`POSIX_FADV_DONTNEED`) 방어**: 과거 콜드 데이터를 읽을 때 리눅스 커널에 `posix_fadvise(fd, offset, len, POSIX_FADV_DONTNEED)` 힌트를 전달하면, 디스크에서 읽어 소켓으로 보낸 즉시 해당 페이지를 페이지 캐시 LRU 리스트에서 방출하여 실시간 트래픽의 핫 캐시 적중률(99.5%)을 완벽하게 수호합니다 (`OPTIMAL_ZERO_COPY_ISOLATED_STREAMING`).

당신은 분산 메시지 브로커의 코어 아키텍트로서, 전송 모드별 컨텍스트 스위칭, CPU 복사 오버헤드, 페이지 캐시 적중률 변동, 그리고 캐시 격리 방어 기법을 완벽히 모델링하는 벤치마크 진단 엔진을 완성해야 합니다.

---

## 핵심 전송 모드 및 캐시 제어 명세

### 1. `USER_SPACE_BUFFER` (유저 공간 버퍼링 모드)
- `read()` 호출로 커널 페이지 캐시에서 JVM 힙 버퍼로 데이터 복사(CPU Copy 1회).
- `write()` 또는 `send()` 호출로 JVM 힙 버퍼에서 소켓 버퍼로 데이터 복사(CPU Copy 2회).
- 64KB 버퍼 청크당 총 4회의 컨텍스트 스위치 발생.
- CPU 메모리 복사 병목으로 인해 실효 전송률이 최대 $12\,\text{Gbps}$로 제한되며, CPU 사용률이 $98.5\%$에 달해 성능 병목이 발생합니다.
- 평가 판정(Verdict): `USER_SPACE_BUFFER_CPU_MEMCPY_BOTTLENECK` (`status: FAILED`).

### 2. `ZERO_COPY_SENDFILE` (기본 제로카피 모드)
- `sendfile(2)` 시스템 콜을 사용하여 커널 페이지 캐시에서 NIC DMA 컨트롤러로 직접 전송 (CPU 복사 0회, 컨텍스트 스위치 2회).
- 실시간 컨슈머만 존재할 때는 캐시 적중률 $99.2\%$, CPU 사용률 $5\%$ 미만, $0.12\,\text{ms}$ 초저지연을 달성합니다 (`OPTIMAL_ZERO_COPY_REALTIME_STREAMING`).
- 그러나 캐시 용량(64GB)을 초과하는 대규모 콜드 데이터(128GB) 조회가 유입되면 페이지 캐시 스래싱이 발생하여 캐시 적중률이 $22.4\%$로 폭락하고 지연시간이 $48\,\text{ms}$로 급증합니다 (`PAGE_CACHE_THRASHING_COLD_CONSUMER_STORM`).

### 3. `ZERO_COPY_WITH_CACHE_ISOLATION` (캐시 격리 제로카피 모드)
- 제로카피 `sendfile(2)` 전송을 기본으로 하되, 콜드 데이터 조회 시 `POSIX_FADV_DONTNEED` 플래그를 적용.
- 디스크에서 읽힌 과거 데이터는 NIC로 송신된 직후 페이지 캐시 활성 세그먼트에서 즉각 해제(Drop)되므로 실시간 파티션 헤드 캐시를 오염시키지 않습니다.
- 실시간 캐시 적중률 $99.5\%$를 유지하며, NVMe 디스크 대역폭과 메모리 대역폭을 동시에 활용하는 이중 경로(Dual-Path) 스트리밍을 달성합니다.
- 평가 판정(Verdict): `OPTIMAL_ZERO_COPY_ISOLATED_STREAMING`.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "system_config": {
    "network_bandwidth_gbps": 100.0,
    "memory_bus_bandwidth_gbps": 400.0,
    "page_cache_capacity_gb": 64.0,
    "disk_read_bandwidth_gbps": 32.0
  },
  "transfer_config": {
    "mode": "ZERO_COPY_WITH_CACHE_ISOLATION",
    "fadvise_dontneed": true
  },
  "workload": {
    "realtime_consumers": {
      "data_rate_gbps": 40.0
    },
    "lagging_cold_consumers": {
      "enabled": true,
      "data_rate_gbps": 20.0,
      "total_cold_data_gb": 128.0
    }
  }
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_ZERO_COPY_ISOLATED_STREAMING",
  "transfer_mode": "ZERO_COPY_WITH_CACHE_ISOLATION",
  "metrics": {
    "requested_bandwidth_gbps": 60.0,
    "achieved_bandwidth_gbps": 60.0,
    "network_utilization_pct": 60.0,
    "cpu_usage_pct": 6.6,
    "cpu_copies_per_byte": 0,
    "context_switches_per_sec": 14305,
    "page_cache_hit_rate_pct": 99.5,
    "average_latency_ms": 0.14,
    "p99_latency_ms": 0.52,
    "cold_consumer_active": true,
    "cache_isolation_active": true
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`USER_SPACE_BUFFER_CPU_MEMCPY_BOTTLENECK`**: `mode == "USER_SPACE_BUFFER"` 상태에서 과도한 CPU 메모리 복사 및 컨텍스트 스위칭으로 인해 전송률이 12Gbps에 갇히고 CPU 98% 포화가 발생한 경우 (`status: FAILED`).
2. **`PAGE_CACHE_THRASHING_COLD_CONSUMER_STORM`**: 제로카피 모드에서 캐시 격리 없이 대규모 콜드 데이터 조회가 유입되어 페이지 캐시 적중률 폭락(`page_cache_hit_rate_pct < 50.0`) 및 지연시간 스파이크가 발생한 경우.
3. **`OPTIMAL_ZERO_COPY_REALTIME_STREAMING`**: 순수 실시간 컨슈머 환경에서 제로카피로 높은 캐시 적중률과 초저지연을 달성한 경우.
4. **`OPTIMAL_ZERO_COPY_ISOLATED_STREAMING`**: 콜드 컨슈머 유입 상황에서도 `POSIX_FADV_DONTNEED` 캐시 격리를 통해 핫 캐시 적중률 99% 이상과 대역폭 포화를 동시에 달성한 경우.
