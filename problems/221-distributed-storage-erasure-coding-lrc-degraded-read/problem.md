# 문제 221: 대규모 분산 스토리지/오브젝트 스토어: Reed-Solomon(RS) 이레이저 코딩 Degraded Read 지연 폭풍과 로컬 복구 코드(LRC, Local Reconstruction Codes) 테일 레이턴시 최적화

## 1. 개요 (Incident Scenario)

수십 페타바이트(PB) 규모의 멀티미디어 데이터와 AI 학습 데이터셋을 서비스하는 글로벌 클라우드 오브젝트 스토리지(AWS S3, Microsoft Azure Storage, Ceph, MinIO 계열) 엔지니어링 팀은 스토리지 인프라 비용 절감을 위해 기존의 3중 복제(3x Replication, 200% 스토리지 오버헤드)에서 **Reed-Solomon 이레이저 코딩($RS(10, 4)$, 40% 오버헤드)** 방식으로 전면 전환을 단행했습니다.

이론상 $RS(10, 4)$는 데이터 청크 $k=10$개와 패리티 청크 $m=4$개를 14대의 독립된 스토리지 노드(또는 랙)에 분산 저장하여 최대 4대의 드라이브가 동시 고장 나더라도 데이터를 안전하게 보존할 수 있습니다.

그러나 운영 규모가 수만 대의 드라이브로 확장되자, 다음과 같은 치명적인 성능 저하 및 가용성 위기가 발생하기 시작했습니다:

1. **Degraded Read(손상 읽기/재구성 읽기) 시 테일 레이턴시(P99) 폭발 참사**:
   데이터센터 내 수만 대의 HDD/SSD 중 일부는 백그라운드 드라이브 검사(Scrubbing), 불량 섹터 재할당, 네트워크 혼잡 등으로 인해 간헐적으로 응답이 200ms 이상 지연되는 **스트래글러(Straggler, 굼벵이 노드)** 상태에 빠집니다.
   특정 데이터 청크가 오프라인이 되어 복구 읽기(`Degraded Read`)를 수행할 때, 전통적인 $RS(10, 4)$ 알고리즘은 단 1개의 청크를 복구하기 위해 **원격의 $k=10$개 청크를 전부 수신**한 뒤 갈루아 체($GF(2^8)$) 행렬 역연산을 수행해야 합니다.
   이 과정에서 읽어야 하는 10개 노드 중 단 하나라도 스트래글러가 끼어 있으면 전체 복구 읽기 요청이 그 최악의 지연 시간(230ms+)에 묶여 서비스 SLA(150ms)를 대거 초과하는 롱테일 정체(`DEGRADED_READ_TAIL_LATENCY_STALL`)가 발생했습니다.

2. **랙 간 네트워크 대역폭 증폭(Network Amplification) 및 ToR 스위치 질식**:
   단 64MB 크기의 청크 1개를 복구하기 위해 10개 노드로부터 $10 \times 64\text{MB} = 640\text{MB}$의 네트워크 트래픽이 발생합니다. 일시적인 노드 재부팅이나 네트워크 플래핑 시 수천 건의 Degraded Read가 동시다발적으로 촉발되면서 랙 상단(ToR) 스위치가 포화되고 클러스터 전체 네트워크가 마비되는 경고(`HIGH_NETWORK_AMPLIFICATION_WARNING`)가 발생했습니다.

3. **허용 한도 초과 고장 시 데이터 영구 손실**:
   동일 오브젝트에 할당된 노드 중 패리티 허용 한도 $m=4$를 초과하는 5대 이상의 노드가 동시에 다운되면 어떠한 재구성으로도 데이터를 복구하지 못하고 데이터 영구 유실(`DATA_LOSS_UNRECOVERABLE`)이 초래됩니다.

4. **로컬 복구 코드(LRC, Local Reconstruction Codes) 도입을 통한 극적 구원**:
   Microsoft Azure Storage 및 최신 Ceph 아키텍처는 이 문제를 해결하기 위해 **로컬 복구 코드(LRC)**를 도입했습니다.
   $LRC(k=12, l=2, g=2)$ 구조에서는 12개의 데이터 청크를 2개의 로컬 그룹(각 6개)으로 나누고, 각 그룹마다 로컬 패리티 1개씩을 할당합니다. 단일 청크 고장 시 전체 12개 노드가 아닌 **자신이 속한 로컬 그룹의 6개 노드만 조회**하여 즉각 복구합니다. 네트워크 전송량은 50%(384MB)로 급감하며, 다른 그룹에 존재하는 스트래글러의 영향을 100% 차단하여 SLA를 완벽하게 사수합니다(`OPTIMAL_LRC_LOCAL_RECONSTRUCTION`).

5. **헤징(Speculative Hedged Reads)을 통한 지연시간 쐐기 방어**:
   $RS(10, 4)$ 환경에서도 클라이언트 프록시가 $k$개가 아닌 $k+1$개(11개) 노드에 병렬 요청을 전송하고 가장 먼저 도착한 10개의 응답만으로 디코딩을 완료하는 예측적 헤징(Speculative Hedging)을 적용함으로써 스트래글러 1대를 완전히 우회할 수 있습니다(`OPTIMAL_HEDGED_DEGRADED_READ`).

당신은 분산 스토리지 아키텍트로서, $RS(k, m)$ 및 $LRC(k, l, g)$의 청크 배치, 노드 스트래글러 및 장애 모델링, Degraded Read 시의 네트워크 증폭 및 테일 레이턴시, 헤징 최적화를 정밀하게 시뮬레이션하는 진단 엔진을 구현해야 합니다.

---

## 2. 아키텍처 및 상태 모델

```
 [Classic Reed-Solomon RS(10, 4) Degraded Read]
  Object Chunks: [ D0  D1  D2  D3  D4  D5  D6  D7  D8  D9 ] [ P0  P1  P2  P3 ]
                   ▲
                   │ (D0 Node Offline!)
                   │
  Reconstruction: Reads ALL k=10 healthy chunks (D1..D9 + P0)
  Network Traffic: 10 * Chunk_Size = 640 MB
  Latency: MAX(latency of 10 nodes) + Decode_CPU
  ===> If Node-5 is a Straggler (230ms), Degraded Read STALLS at 235ms!

 ───────────────────────────────────────────────────────────────────────────

 [Azure Storage / Ceph Local Reconstruction Codes LRC(12, 2, 2)]
  Local Group 0: [ D0  D1  D2  D3  D4  D5 ] + [ L0 (Local Parity) ]
  Local Group 1: [ D6  D7  D8  D9 D10 D11 ] + [ L1 (Local Parity) ]
  Global Parity: [ G0  G1 ]

  Case: D1 Node Offline! (Straggler is Node-8 in Local Group 1)
  Reconstruction: Reads ONLY 6 chunks in Group 0 (D0, D2..D5 + L0)!
  Network Traffic: 6 * Chunk_Size = 384 MB (50% reduction!)
  Latency: MAX(latency of Group 0 nodes) + Light_XOR_Decode
  ===> Completely avoids Node-8! Finishes in 17.5ms (Zero SLA Violation)!
```

### 시뮬레이션 동작 규격

1. **스토리지 코딩 스키마 설정**:
   - `storage_scheme`: `"REED_SOLOMON"` 또는 `"LOCAL_RECONSTRUCTION_CODES"`
   - `k`: 데이터 청크 개수
   - `m`: 패리티 청크 개수 (RS 전용)
   - `l`: 로컬 그룹 개수 (LRC 전용, $k$는 $l$의 배수, 그룹 크기 $S = k / l$)
   - `g`: 글로벌 패리티 개수 (LRC 전용)
   - `chunk_size_mb`: 청크 1개의 크기(MB)
   - `read_timeout_ms`: 읽기 지연 시간 SLA 임계치(ms)
   - `decode_cpu_overhead_ms`: 재구성 디코딩 CPU 연산 오버헤드(ms)
   - `speculative_hedged_reads_enabled`: 헤징 투기적 요청 활성화 여부(bool)

2. **노드 상태 및 지연시간 모델**:
   - `nodes` 맵은 각 노드의 `status` (`"HEALTHY"` 또는 `"OFFLINE"`), `latency_ms`, `is_straggler`, `straggler_latency_ms`를 포함합니다.
   - `status == "OFFLINE"`: 드라이브 장애 또는 노드 다운 상태 (응답 불가).
   - `status == "HEALTHY"`: 정상 응답 가능. `is_straggler == true`이면 `straggler_latency_ms` 반환, 그렇지 않으면 `latency_ms` 반환.

3. **읽기 요청 처리 (Read Execution)**:
   - **정상 읽기(Normal Read)**: 대상 청크가 위치한 노드가 `HEALTHY`이면 단 1개의 청크만 직접 읽습니다. 지연시간은 해당 노드의 지연시간이며, 재구성 네트워크 트래픽은 0입니다.
   - **손상 읽기(Degraded Read)**: 대상 청크가 위치한 노드가 `OFFLINE`인 경우 복구를 수행합니다:
     - **REED_SOLOMON**: 전체 $k+m$ 청크 중 대상 청크를 제외한 후보 노드들 중 `HEALTHY` 상태인 노드를 탐색합니다.
       - 정상 후보 노드 수가 $k$개 미만이면: 복구 불가(`unrecoverable_failures += 1`, 페널티 지연시간 `read_timeout_ms * 2.0`).
       - `speculative_hedged_reads_enabled == true`이고 정상 노드가 $k+1$개 이상이면: 가장 빠른 $k$개 노드의 응답을 선택합니다.
       - 그렇지 않으면: 후보 순서대로 처음 발견된 $k$개 노드의 응답을 취합니다.
       - 지연시간 = 선택된 $k$개 노드의 최대 지연시간 + `decode_cpu_overhead_ms`
       - 재구성 네트워크 전송량 = $k \times \text{chunk\_size\_mb}$
     - **LOCAL_RECONSTRUCTION_CODES**:
       - 대상 청크가 속한 로컬 그룹을 판정합니다 ($i < k$인 데이터 청크는 그룹 $\lfloor i / S \rfloor$, $k \le i < k + l$인 로컬 패리티는 그룹 $i - k$).
       - 해당 로컬 그룹 내의 나머지 $S$개 청크가 **전부 `HEALTHY`** 상태라면 **로컬 복구(Local Reconstruction)**를 수행합니다:
         - 지연시간 = 로컬 $S$개 노드의 최대 지연시간 + (`decode_cpu_overhead_ms` * 0.5)
         - 재구성 네트워크 전송량 = $S \times \text{chunk\_size\_mb}$
       - 로컬 그룹 내에 다른 고장 노드가 있어 $S$개를 채우지 못하면 **글로벌 복구(Global Reconstruction)**로 폴백합니다:
         - 전체 $k+l+g$ 청크 중 대상 제외 정상 노드 $k$개를 수집하여 복구합니다.
         - 정상 노드가 $k$개 미만이면 복구 불가 처리.
         - 지연시간 = 선택된 $k$개 노드의 최대 지연시간 + `decode_cpu_overhead_ms`
         - 재구성 네트워크 전송량 = $k \times \text{chunk\_size\_mb}$

4. **메트릭 산출 및 최종 Verdict 판정 규칙**:
   - `p99_latency_ms`: 전체 요청 지연시간 목록(오름차순 정렬)에서 99번째 백분위수 (인덱스: $\min(N-1, \lceil 0.99 \times N \rceil - 1)$).
   - `average_reconstruction_network_mb`: 총 재구성 네트워크 전송량 / Degraded Read 횟수 (Degraded Read가 없으면 0.0).
   - **판정 우선순위**:
     1. `unrecoverable_failures > 0` $\to$ `status = "FAILED"`, `verdict = "DATA_LOSS_UNRECOVERABLE"`
     2. `read_sla_violations > 0` 또는 `p99_latency_ms > read_timeout_ms` $\to$ `status = "FAILED"`, `verdict = "DEGRADED_READ_TAIL_LATENCY_STALL"`
     3. `scheme == "LOCAL_RECONSTRUCTION_CODES"` 이고 `degraded_reads > 0` 이며 `avg_recon_network <= S * chunk_size_mb` $\to$ `status = "SUCCESS"`, `verdict = "OPTIMAL_LRC_LOCAL_RECONSTRUCTION"`
     4. `scheme == "LOCAL_RECONSTRUCTION_CODES"` 이고 `degraded_reads > 0` 이며 `avg_recon_network > S * chunk_size_mb` $\to$ `status = "SUCCESS"`, `verdict = "LRC_GLOBAL_RECONSTRUCTION_FALLBACK"`
     5. `hedging_enabled == true` 이고 `degraded_reads > 0` 이며 `read_sla_violations == 0` $\to$ `status = "SUCCESS"`, `verdict = "OPTIMAL_HEDGED_DEGRADED_READ"`
     6. `scheme == "REED_SOLOMON"` 이고 `avg_recon_network >= 500.0` $\to$ `status = "SUCCESS"`, `verdict = "HIGH_NETWORK_AMPLIFICATION_WARNING"`
     7. 그 외 정상 처리: `status = "SUCCESS"`, `verdict = "NORMAL_READ_WORKLOAD"`

---

## 3. 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "storage_scheme": "LOCAL_RECONSTRUCTION_CODES",
    "k": 12,
    "l": 2,
    "g": 2,
    "chunk_size_mb": 64.0,
    "read_timeout_ms": 150.0,
    "decode_cpu_overhead_ms": 5.0,
    "speculative_hedged_reads_enabled": false
  },
  "nodes": {
    "node-0": { "status": "HEALTHY", "latency_ms": 15.0, "is_straggler": false },
    "node-1": { "status": "OFFLINE", "latency_ms": 15.0, "is_straggler": false },
    "node-8": { "status": "HEALTHY", "latency_ms": 15.0, "is_straggler": true, "straggler_latency_ms": 240.0 }
  },
  "read_requests": [
    {
      "request_id": "R1",
      "target_chunk_index": 1,
      "chunk_to_node_map": ["node-0", "node-1", "node-2", "node-3", "node-4", "node-5", "node-6", "node-7", "node-8", "node-9", "node-10", "node-11", "node-12", "node-13", "node-14", "node-15"]
    }
  ]
}
```

---

## 4. 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다. 부동소수점 수치는 소수점 둘째 자리까지 반올림합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_LRC_LOCAL_RECONSTRUCTION",
  "metrics": {
    "storage_scheme": "LOCAL_RECONSTRUCTION_CODES",
    "total_reads": 1,
    "degraded_reads": 1,
    "read_sla_violations": 0,
    "unrecoverable_failures": 0,
    "p99_latency_ms": 17.5,
    "average_reconstruction_network_mb": 384.0
  }
}
```
