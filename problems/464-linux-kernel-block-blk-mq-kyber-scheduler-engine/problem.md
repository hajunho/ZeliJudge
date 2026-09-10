# 리눅스 커널 블록 계층 다중 큐(blk-mq) 태그 셋 및 Kyber I/O 스케줄러 엔진

## 1. 개요 및 배경

초기 리눅스 블록 I/O 계층은 회전식 하드 디스크(HDD)를 위해 설계되었으며, 블록 디바이스마다 하나의 요청 큐(`struct request_queue`)와 이를 보호하는 단일 전역 스핀락(`queue_lock`)을 사용했습니다.
그러나 수백만 단위의 IOPS(Input/Output Operations Per Second)와 마이크로초 단위의 초저지연을 제공하는 고성능 NVMe SSD와 수십~수백 코어를 갖춘 멀티코어 서버 환경이 도래하면서, 전역 스핀락 경합 및 CPU 간 캐시 라인 바운싱(Cache Line Bouncing)이 전체 시스템 I/O 대역폭을 극심하게 제약하는 치명적인 병목이 되었습니다.

리눅스 커널은 이를 근본적으로 해결하기 위해 **blk-mq (Multi-Queue Block Layer)** 아키텍처(`block/blk-mq.c`, `block/blk-mq-tag.c`)를 도입하였습니다. blk-mq는 I/O 큐잉을 2단계(Two-Level)로 분리합니다:
1. **소프트웨어 스테이징 큐 (`struct blk_mq_ctx`)**: CPU 코어마다 독립적으로 할당되어 코어 간 락 경합 없이 I/O 요청을 즉시 수납합니다.
2. **하드웨어 디스패치 큐 (`struct blk_mq_hw_ctx`, hctx)**: NVMe 컨트롤러의 물리 제출 큐(Submission Queue)와 1:1 또는 N:1로 매핑되며, 확장 비트맵(`sbitmap`)을 통해 컨트롤러 명령 태그(Tag)를 고속 할당받아 디스패치합니다.

고성능 NVMe 환경에서는 스케줄러 오버헤드를 완전히 제거한 `none`(Passthrough) 모드가 널리 쓰이지만, 백그라운드 대용량 쓰기(Write) 폭주 시 하드웨어 태그가 모두 쓰기 요청으로 채워져 지연 시간에 극도로 민감한 동기식 읽기(Read) 요청이 큐 뒤에서 장시간 대기하는 **헤드오브라인 블로킹(Head-of-Line Blocking)**이 발생합니다.

페이스북(Meta)이 개발하여 리눅스 커널 4.12에 머지된 **Kyber I/O 스케줄러**(`block/kyber-iosched.c`)는 blk-mq의 고성능을 유지하면서 이 문제를 우아하게 해결합니다:
- **도메인 분리**: 읽기(`KYBER_READ`)와 쓰기(`KYBER_WRITE`)를 서로 다른 큐 도메인으로 분리 관리합니다.
- **읽기 우선순위 및 쓰기 토큰(Token) 제약**: 읽기 요청은 하드웨어 큐 슬롯만 비어있으면 즉시 디스패치되는 반면, 쓰기 요청은 하드웨어 큐 슬롯뿐만 아니라 동적으로 할당된 **쓰기 토큰(`write_tokens`)**을 획득해야만 디스패치됩니다.
- **적응형 지연시간 피드백 제어 (p99 Control Loop)**: 주기적 샘플링 윈도우마다 관측된 99백분위(p99) 완성 지연시간이 목표치(`read_target_us`, `write_target_us`)를 초과하는지 모니터링하여 쓰기 토큰을 즉시 반감(`write_tokens // 2`)하거나 점진적으로 확장(`write_tokens + 1`)합니다.

본 과제에서는 blk-mq 2단계 큐잉 파이프라인, `none` vs `kyber` 스케줄러 동작, 동적 쓰기 토큰 관리 및 적응형 피드백 제어를 시뮬레이션하는 고성능 블록 I/O 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------+
|                        User Space / Page Cache / O_DIRECT                         |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (submit_bio / blk_mq_submit_bio)
+-----------------------------------------------------------------------------------+
|               blk-mq Level 1: Per-CPU Software Staging Queues                     |
|                                                                                   |
|   [ CPU 0 ctx ]           [ CPU 1 ctx ]           ...      [ CPU N-1 ctx ]        |
+-----------------------------------------------------------------------------------+
             \                           |                           /
              \                          |                          /  Affinity Mapping
               v                         v                         v
+-----------------------------------------------------------------------------------+
|               blk-mq Level 2: I/O Scheduler Domain & Token Gate                  |
|                                                                                   |
|   [ none Scheduler ]                     [ Kyber Scheduler ]                      |
|    - Single FIFO Direct Dispatch          - Domain: KYBER_READ (Uncapped)         |
|    - Queue Saturation Risk                - Domain: KYBER_WRITE (Token-Gated)     |
|                                           - Feedback: P99 Latency Control Loop    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|           Hardware Dispatch Queues (struct blk_mq_hw_ctx, hctx)                  |
|           - Tag Allocation via sbitmap (Max In-Flight: queue_depth)              |
|                                                                                   |
|         [ hctx 0 (Tag Pool) ]                     [ hctx 1 (Tag Pool) ]           |
+-----------------------------------------------------------------------------------+
                   |                                           |
                   v (NVMe SQ Doorbell)                        v (NVMe SQ Doorbell)
+-----------------------------------------------------------------------------------+
|               NVMe Controller Hardware Execution & Completion Queues              |
+-----------------------------------------------------------------------------------+
```

---

## 3. 세부 동작 원리 및 수학적 모델

### 3.1 디스패치 규칙

각 하드웨어 큐 $h$에 대해 동시 처리 가능한 최대 태그 수는 $\text{queue\_depth}$입니다. 현재 실행 중인 요청 수는 $\text{in\_flight}(h)$, 실행 중인 쓰기 요청 수는 $\text{write\_in\_flight}(h)$로 표기합니다.

1. **`none` 스케줄러**:
   - 단일 FIFO 스테이징 큐에서 요청을 꺼냅니다.
   - 디스패치 조건: $\text{in\_flight}(h) < \text{queue\_depth}$

2. **`kyber` 스케줄러**:
   - 별도의 `staging_reads[h]`와 `staging_writes[h]` 큐를 유지합니다.
   - **우선순위 1 (읽기 디스패치)**:
     $$\text{staging\_reads}[h] \ne \emptyset \quad \land \quad \text{in\_flight}(h) < \text{queue\_depth}$$
     조건을 만족하면 읽기 요청을 즉시 디스패치합니다.
   - **우선순위 2 (쓰기 디스패치)**:
     읽기 큐가 비어있을 때:
     $$\text{staging\_writes}[h] \ne \emptyset \quad \land \quad \text{in\_flight}(h) < \text{queue\_depth} \quad \land \quad \text{write\_in\_flight}(h) < \text{write\_tokens}[h]$$
     조건을 만족할 때만 쓰기 요청을 디스패치합니다. 쓰기 토큰이 부족하면 하드웨어 큐 슬롯이 비어있더라도 쓰기를 대기시켜, 후속 읽기 요청을 위한 버퍼를 확보합니다.

### 3.2 지연 시간 메트릭

요청 $r$의 제출 시각을 $T_{\text{submit}}$, 디스패치 시각을 $T_{\text{dispatch}}$, 하드웨어 완료 시각을 $T_{\text{complete}}$라 할 때:
- 큐 대기 시간:
  $$L_{\text{queue}} = T_{\text{dispatch}} - T_{\text{submit}}$$
- 디바이스 실행 시간:
  $$L_{\text{device}} = T_{\text{complete}} - T_{\text{dispatch}} = \text{device\_latency\_us}$$
- 총 반환 지연 시간:
  $$L_{\text{total}} = T_{\text{complete}} - T_{\text{submit}} = L_{\text{queue}} + L_{\text{device}}$$

### 3.3 Kyber 주기적 샘플링 및 적응형 피드백 제어 (`SAMPLE_INTERVAL_EXPIRED`)

샘플링 윈도우 동안 완료된 요청들의 $L_{\text{total}}$ 집합에 대해 99백분위수($P_{99}$)를 계산합니다.
원소 수 $N$개인 정렬된 리스트 $A$에서:
$$P_{99} = A\left[\max(0, \lceil 0.99 \times N \rceil - 1)\right]$$
($N = 0$인 경우 $P_{99} = 0$)

쓰기 토큰 조정 규칙:
1. **읽기 정체 (`THROTTLE_READ_CONGESTION`)**:
   $$P_{99}^{\text{read}} > \tau_{\text{read}} \implies \text{write\_tokens} \leftarrow \max(\text{min\_tokens}, \lfloor \text{write\_tokens} / 2 \rfloor)$$
2. **쓰기 지연 저하 (`THROTTLE_WRITE_LATENCY`)**:
   $$P_{99}^{\text{read}} \le \tau_{\text{read}} \quad \land \quad P_{99}^{\text{write}} > \tau_{\text{write}} \implies \text{write\_tokens} \leftarrow \max(\text{min\_tokens}, \text{write\_tokens} - 1)$$
3. **정상 상태 및 토큰 확장 (`EXPAND_TOKENS`)**:
   $$P_{99}^{\text{read}} \le \tau_{\text{read}} \quad \land \quad P_{99}^{\text{write}} \le \tau_{\text{write}} \implies \text{write\_tokens} \leftarrow \min(\text{max\_tokens}, \text{write\_tokens} + 1)$$

토큰이 갱신된 후에는 샘플 윈도우 기록을 초기화하고, 대기 중이던 쓰기 요청의 추가 디스패치를 즉시 시도합니다.

---

## 4. 입출력 규격

### 입력 JSON 포맷
```json
{
  "config": {
    "nr_hw_queues": 1,
    "queue_depth": 2,
    "scheduler": "kyber",
    "read_target_us": 2000,
    "write_target_us": 10000,
    "initial_write_tokens": 1,
    "min_write_tokens": 1,
    "max_write_tokens": 2
  },
  "operations": [
    {
      "type": "SUBMIT",
      "timestamp_us": 100,
      "req_id": "w1",
      "cpu_id": 0,
      "hctx_id": 0,
      "op_type": "WRITE",
      "device_latency_us": 3000
    },
    {
      "type": "SAMPLE_INTERVAL_EXPIRED",
      "timestamp_us": 4000
    },
    {
      "type": "QUERY_STATS",
      "timestamp_us": 4100
    },
    {
      "type": "DRAIN_ALL",
      "timestamp_us": 5000
    }
  ]
}
```

### 출력 JSON 포맷
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "SUBMIT",
      "req_id": "w1",
      "status": "DISPATCHED",
      "hctx_id": 0,
      "in_flight": 1
    }
  ],
  "summary": {
    "total_submitted": 3,
    "total_dispatched": 3,
    "total_completed": 3,
    "read_stats": {
      "count": 1,
      "avg_queue_lat_us": 0.0,
      "avg_total_lat_us": 500.0,
      "max_total_lat_us": 500
    },
    "write_stats": {
      "count": 2,
      "avg_queue_lat_us": 1500.0,
      "avg_total_lat_us": 4500.0,
      "max_total_lat_us": 6000
    },
    "requests": [
      {
        "req_id": "r1",
        "op_type": "READ",
        "hctx_id": 0,
        "submit_time": 200,
        "dispatch_time": 200,
        "complete_time": 700,
        "queue_lat_us": 0,
        "device_lat_us": 500,
        "total_lat_us": 500
      }
    ]
  }
}
```
