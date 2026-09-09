# Problem 208: 디스크 하나 추가했을 뿐인데 왜 수백 테라바이트가 마구잡이로 이동해요?!: 분산 스토리지 Ceph: CRUSH 맵 가중치 재분배, Straw vs Straw2 버킷 알고리즘과 데이터 이동 최소화 (Ceph Distributed Storage: CRUSH Map Straw vs Straw2 Bucket Rebalancing & Data Movement Minimization)

## 문제 배경 및 개요

수십 페타바이트(PB) 규모의 오픈스토리지 클라우드 인프라(OpenStack Cinder/Glance, Kubernetes Rook-Ceph, AI 학습용 오브젝트 스토리지)를 운영하는 대규모 스토리지 엔지니어링 팀은 정기 유지보수 작업 중 심각한 **"원치 않는 대규모 데이터 이동 폭풍(Unwanted Data Rebalancing Storm)"** 재앙을 겪었습니다.

수백 대의 서버와 수천 개의 OSD(Object Storage Daemon, 물리 드라이브)로 구성된 Ceph 클러스터의 용량이 85%에 도달하자, 운영팀은 랙(Rack) 1번에 **10TB 용량의 신규 드라이브(`osd.12`) 단 1개를 증설**하고 CRUSH 맵에 가중치 `5.0`을 부여했습니다.

수학적으로 이상적인 분산 스토리지라면, 신규 드라이브 1개가 추가되었을 때 **오직 해당 드라이브가 수용해야 할 데이터만큼만 다른 OSD들로부터 균등하게 이전(Migration)**되어야 합니다.

```
[이상적인 데이터 재분배: Optimal Straw2 Minimal Movement]
기존 OSD 0 ~ 11 ──────── (각자 조금씩 기여) ────────> 신규 OSD 12
(기존 OSD들 상호 간에는 데이터 이동이 정확히 0건이어야 함!)
```

그러나 실제 운영 환경(Ceph Hammer 이전 버전의 Classic Straw 버킷)에서는 기괴한 참사가 벌어졌습니다:

```
[Classic Straw 버킷의 대참사: Unnecessary Data Movement Storm]
신규 OSD 12 로 들어가는 데이터:  11.4 TB (정상)
그런데...
기존 OSD 0 ───(수백 GB 이동)───> 기존 OSD 2
기존 OSD 1 ───(수백 GB 이동)───> 기존 OSD 3
기존 OSD 4 ───(수백 GB 이동)───> 기존 OSD 6
...
아무런 변경도 없었던 기존 OSD들끼리 무려 32개 PG(수십 TB)를 마구잡이로 맞교환!
==> 백필(Backfill) 및 복구(Recovery) I/O가 100GbE 백본 네트워크를 완전 마비시킴!
==> 스토리지 클라이언트 I/O 응답 지연시간(Latency)이 3ms에서 1,500ms로 폭증!
```

이 재앙의 근본 원인은 Ceph 초기 버킷 해시 알고리즘인 **Classic Straw 버킷**의 수학적 결함에 있었습니다:
- Classic Straw 알고리즘에서 각 항목의 스트로 길이(Straw Length) 계수는 **버킷에 속한 모든 항목들의 가중치 합과 상대적 차이**에 의존하여 계산됩니다.
- 따라서 새 OSD가 추가되거나 기존 OSD의 가중치가 변경되면, 변경되지 않은 주변 OSD들의 스트로 계수까지 비선형적으로 왜곡되어 **기존 OSD들 사이에서 승자가 뒤바뀌는 스푸리어스 셔플(Spurious Shuffling)**이 대량 발생합니다.
- 이를 해결하기 위해 Sage Weil 등 Ceph 코어 아키텍트는 **Straw2 버킷 알고리즘**을 개발했습니다. 지수 분포 난수 발생 기법($\ln(U_i) / w_i$)을 적용하여, 각 OSD의 점수가 오직 자신의 가중치($w_i$)와 해시값에만 독립적으로 의존하도록 완전히 분리했습니다.
- 그 결과, Straw2에서는 변경되지 않은 OSD들 간의 데이터 이동이 **수학적으로 100% 불가능(Zero Movement)**해졌으며, 오직 추가/수정된 OSD로만 최소한의 데이터가 이동하는 최적 재분배를 달성했습니다.

당신은 Ceph 분산 스토리지 코어 아키텍트로서, CRUSH 맵의 계층적 랙/호스트 장애 도메인 격리(Failure Domain Isolation), Classic Straw vs Straw2 버킷 해시 평가 엔진, 그리고 토폴로지 변경(증설, 가중치 수정, 장애 제거) 시 발생하는 데이터 이동량을 정밀 진단하는 시뮬레이터를 구현해야 합니다.

---

## 핵심 알고리즘 및 수학적 명세

### 1. Classic Straw 버킷 알고리즘
- 버킷 내 항목들을 가중치 순으로 정렬한 뒤, 누적 가중치 비율을 바탕으로 각 OSD의 스트로 팩터(`straws[item]`)를 계산합니다:
  $$\text{straw}[i] = \text{straw}[i-1] \times \left( \frac{W_{\text{below}} + w_{i+1}}{W_{\text{below}}} \right)^{\frac{1}{n - 1 - i}}$$
- 해시 평가 시:
  $$\text{score}_i = (\text{hash32}(pg, item_i, r) \ \& \ \text{0xffff}) \times \text{straw}[item_i]$$
- 결함: $n$ 또는 특정 가중치가 변하면 모든 $i$의 스트로 팩터가 변하여, 변경되지 않은 OSD들 간에도 $\text{score}_i$의 대소 관계가 역전됩니다 (`unnecessary_moves > 0`).

### 2. Straw2 버킷 알고리즘 (Ceph 표준 최적 해싱)
- 각 항목의 점수는 오직 자신의 가중치 $w_i$와 의사 난수 $U_i$에만 의존합니다:
  $$U_i = \frac{(\text{hash32}(pg, item_i, r) \pmod{65535} + 1)}{65536.0} \in (0, 1)$$
  $$\text{score}_i = \frac{\ln(U_i)}{w_i}$$
- $\ln(U_i) < 0$이므로 $\text{score}_i$는 음수이며, 이를 최대화하는(0에 가장 가까운) 항목이 승자가 됩니다.
- 수학적 불변식: 다른 OSD의 가중치가 변하거나 새 OSD가 추가되어도, 기존 OSD $A$와 OSD $B$의 점수 $\text{score}_A, \text{score}_B$는 단 $1\,\text{bit}$도 변하지 않습니다. 따라서 $A$와 $B$ 사이의 데이터 교환 확률은 정확히 **$0\%$**입니다.

### 3. 장애 도메인 격리 (Failure Domain Isolation)
- $R$개의 복제본(Replica)을 배치할 때, 동일한 장애 도메인(예: 동일 랙)에 2개 이상의 복제본이 배치되어서는 안 됩니다.
- 랙 수가 복제본 수보다 적은 환경($N_{\text{racks}} < R$)에서는 장애 도메인 충돌(`failure_domain_violations > 0`)이 발생하여 클러스터가 위험 상태(`status: FAILED`, `FAILURE_DOMAIN_VIOLATION`)로 판정됩니다.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "crush_map": {
    "bucket_algorithm": "STRAW2",
    "failure_domain_type": "rack",
    "racks": {
      "rack-0": [
        {"id": "osd.0", "weight": 2.0},
        {"id": "osd.1", "weight": 4.0},
        {"id": "osd.2", "weight": 6.0},
        {"id": "osd.3", "weight": 8.0}
      ],
      "rack-1": [
        {"id": "osd.4", "weight": 2.0},
        {"id": "osd.5", "weight": 4.0},
        {"id": "osd.6", "weight": 6.0},
        {"id": "osd.7", "weight": 8.0}
      ],
      "rack-2": [
        {"id": "osd.8", "weight": 2.0},
        {"id": "osd.9", "weight": 4.0},
        {"id": "osd.10", "weight": 6.0},
        {"id": "osd.11", "weight": 8.0}
      ]
    }
  },
  "pool_config": {
    "num_pgs": 1000,
    "replica_count": 3,
    "pg_size_gb": 100.0
  },
  "rebalance_action": {
    "action_type": "ADD_OSD",
    "target_rack": "rack-1",
    "target_osd": "osd.12",
    "new_weight": 5.0
  }
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 복제 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_STRAW2_MINIMAL_DATA_MOVEMENT",
  "bucket_algorithm": "STRAW2",
  "failure_domain_type": "rack",
  "metrics": {
    "total_pgs": 1000,
    "replica_count": 3,
    "total_pg_replicas": 3000,
    "moved_replicas": 198,
    "moves_to_or_from_target": 198,
    "unnecessary_moves": 0,
    "unnecessary_move_ratio_pct": 0.0,
    "total_data_movement_tb": 19.34,
    "unnecessary_data_movement_tb": 0.0,
    "failure_domain_violations": 0
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`FAILURE_DOMAIN_VIOLATION`**: 단일 PG의 복제본들이 동일한 랙(장애 도메인)에 중복 배치되어 `failure_domain_violations > 0`인 경우 (`status: FAILED`).
2. **`CLASSIC_STRAW_UNNECESSARY_DATA_MOVEMENT_STORM`**: 토폴로지 변경 대상이 아닌 무관한 OSD들 사이에서 불필요한 PG 이동이 발생한 경우 (`unnecessary_moves > 0`).
3. **`OPTIMAL_STRAW2_MINIMAL_DATA_MOVEMENT`**: 변경되지 않은 OSD 간 데이터 이동이 0건(`unnecessary_moves == 0`)이고 장애 도메인이 100% 준수된 경우.
