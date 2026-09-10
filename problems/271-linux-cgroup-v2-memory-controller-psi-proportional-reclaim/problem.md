# 리눅스 Cgroup v2 메모리 컨트롤러(memcg): memory.min/low 계층적 보호와 memory.high 비동기 스로틀링 vs memory.max OOM Killer & PSI(Pressure Stall Information) 조기 경보 엔진

## 문제 설명

대규모 멀티테넌트 쿠버네티스(Kubernetes) 클러스터나 클라우드 환경에서는 동일한 베어메탈 노드 위에 중요 데이터베이스(PostgreSQL, MySQL), 인메모리 캐시(Redis), 그리고 비정기 배치 파이프라인이 공존합니다. 과거 Cgroup v1 환경에서는 메모리 제한(`memory.limit_in_bytes`)이 단일 정적 임계값으로만 작동하여 다음과 같은 치명적인 장애들이 반복되었습니다:
1. **노이지 네이버(Noisy Neighbor)에 의한 페이지 캐시 기아**: 배치 작업이 대량의 임시 파일을 읽고 쓸 때, 커널이 데이터베이스의 핫 데이터 페이지 캐시를 맹목적으로 회수(Reclaim)하여 DB 디스크 I/O가 100%로 치솟고 쿼리 지연시간이 폭증하는 현상.
2. **급작스러운 OOM Killer 격발**: 워터마크 여유 없이 `limit`에 도달하자마자 커널이 선제적 완충 장치 없이 프로세스를 사살(OOM Kill)하여 서비스가 즉시 중단되는 참사.
3. **메모리 압박 지표 부재**: 메모리 사용률(Usage %)만으로는 실제 스레드가 메모리 할당/회수 대기로 인해 얼마나 지연되고 있는지 파악할 수 없어 선제적 오토스케일링이나 로드 셰딩이 불가능했던 한계.

리눅스 커널은 **Cgroup v2 메모리 컨트롤러(`memcg`)**와 **PSI(Pressure Stall Information)**를 도입하여 이 문제를 근본적으로 해결했습니다:

1. **계층적 메모리 보호 및 제한 모델**:
   - `memory.min` (**Hard Protection**): 이 임계값 이하의 메모리는 노드 전체에 아무리 극심한 메모리 압박이 발생하더라도 커널이 절대 회수(Reclaim)하지 않습니다.
   - `memory.low` (**Best-Effort Soft Protection**): 보호되지 않은(Unprotected) 여유 메모리가 존재하는 한 회수되지 않습니다. 단, 노드 전체 메모리가 고갈되어 보호되지 않은 메모리만으로 압박을 해소할 수 없는 비상 상황(`LOW_PROTECTION_BREACHED`)에서는 예외적으로 `memory.min`까지 비례 회수(Proportional Reclaim)가 침투합니다.
   - `memory.high` (**Throttling & Proactive Reclaim**): 프로세스가 이 수위를 초과하면, 즉시 OOM으로 죽이지 않고 유저스페이스 복귀 시점에 의도적인 스케줄링 지연(Throttling Delay)을 부과함과 동시에 파일 페이지 캐시를 선제 동기 회수하여 할당 폭증을 억제합니다.
   - `memory.max` (**Hard Limit & OOM Killer**): 직접 회수(Direct Reclaim)를 시도한 후에도 사용량이 `memory.max`를 초과하면, 즉시 OOM Killer가 격발됩니다. `oom_group = true`인 경우 컨테이너 내 모든 프로세스를 원자적으로 종료(전체 메모리 해제)하고, `oom_group = false`인 경우 메모리를 가장 많이 점유한 프로세스를 사살하여 초과분을 삭감합니다.
2. **전역 메모리 압박 비례 회수(Proportional Global Reclaim)**:
   - 노드 메모리 압박(`global_pressure_mb`) 발생 시, 각 cgroup의 `memory.low` 초과분($\text{excess} = \max(0, \text{usage} - \text{memory.low})$)의 비율에 따라 회수 대상량($R_i$)을 분배하여 파일 캐시(`file_mb`)를 회수합니다.
3. **PSI(Pressure Stall Information) 조기 경보 엔진**:
   - `some`: 적어도 하나 이상의 스레드가 메모리 할당/페이징으로 정체(Stall)된 시간 비율.
   - `full`: 모든 활성 스레드가 동시에 메모리 대기로 블로킹되어 CPU가 100% 공회전/낭비된 시간 비율.
   - 10초 윈도우 지수이동평균(EWMA, $\alpha = 1 - e^{-1/10} \approx 0.09516$):
     $$\text{avg10} = \text{round}(\alpha \cdot \text{sample} + (1 - \alpha) \cdot \text{avg10}, 2)$$
   - 임계치(`some_warn_pct`, `some_crit_pct`, `full_crit_pct`) 기반 헬스 상태(`STATUS_HEALTHY`, `STATUS_THROTTLED`, `STATUS_PRESSURE_WARNING`, `STATUS_CRITICAL_STALL`, `STATUS_OOM_KILLED`) 및 권고 조치(`NONE`, `ALLOCATION_THROTTLED`, `PROACTIVE_CACHE_TRIM`, `SCALE_REPLICAS_OR_SHED_LOAD`, `RESTART_CONTAINER`)를 실시간 평가합니다.

본 문제에서는 시스템 설정과 cgroup 초기 상태, 그리고 시계열 워크로드 이벤트가 주어졌을 때, 커널의 메모리 회수·스로틀링·OOM 및 PSI 모니터링 파이프라인을 정밀하게 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)을 통해 단일 JSON 객체가 전달됩니다:

```json
{
  "system_config": {
    "total_memory_mb": 16384,
    "psi_thresholds": {
      "some_warn_pct": 15.0,
      "some_crit_pct": 35.0,
      "full_crit_pct": 20.0
    },
    "throttle_factor_ms": 50,
    "max_throttle_ms": 1000
  },
  "cgroups": [
    {
      "id": "db_primary",
      "memory_min_mb": 2048,
      "memory_low_mb": 4096,
      "memory_high_mb": 8192,
      "memory_max_mb": 10240,
      "oom_score_adj": -500,
      "oom_group": true,
      "initial_anon_mb": 2048,
      "initial_file_mb": 2048
    }
  ],
  "events": [
    {
      "step": 1,
      "cgroup_allocations": {
        "db_primary": { "anon_delta_mb": 500, "file_delta_mb": 500 }
      },
      "global_pressure_mb": 1000,
      "stall_samples": {
        "db_primary": { "active_threads": 8, "stalled_threads": 1, "all_threads_stalled": false }
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 compact한 단일 행 JSON 문자열을 출력합니다:

```json
{
  "total_steps_simulated": 1,
  "cgroup_summaries": {
    "db_primary": {
      "final_usage_mb": 4548,
      "final_anon_mb": 2548,
      "final_file_mb": 2000,
      "total_oom_kills": 0,
      "total_throttle_ms": 0,
      "final_psi_some_avg10": 1.19,
      "final_psi_full_avg10": 0.0,
      "final_status": "STATUS_HEALTHY"
    }
  },
  "step_history": [
    {
      "step": 1,
      "low_protection_breached": false,
      "cgroups": {
        "db_primary": {
          "total_usage_mb": 4548,
          "anon_mb": 2548,
          "file_mb": 2000,
          "throttle_delay_ms": 0,
          "oom_killed": false,
          "global_reclaimed_mb": 548,
          "psi_some_avg10": 1.19,
          "psi_full_avg10": 0.0,
          "status": "STATUS_HEALTHY",
          "action": "NONE"
        }
      }
    }
  ]
}
```
