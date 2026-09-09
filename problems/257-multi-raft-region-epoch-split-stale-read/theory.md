# 핵심 CS 및 분산 시스템 이론: Multi-Raft Region Epoch와 Range Lease 선형성 보장 원리

---

## 1. 분산 키-값 저장소의 수평 확장: Multi-Raft 아키텍처

### 1.1 단일 Raft의 한계와 키스페이스 범위 분할(Range Partitioning)
전통적인 Raft 합의 알고리즘은 단일 복제 로그(Replicated Log)를 기반으로 동작합니다. 그러나 클러스터 규모가 수십~수백 테라바이트에 도달하면 단일 Raft로는 다음과 같은 물리적 한계에 직면합니다:
1. **쓰기 병목**: 모든 쓰기가 단일 리더의 직렬화된 로그와 디스크 fsync를 거쳐야 하므로 수천 Mops/sec 확장이 불가능합니다.
2. **로그 크기 폭증**: 단일 노드가 전체 클러스터 데이터를 유지해야 하므로 수평 스케일아웃이 불가능합니다.

이를 해결하기 위해 TiKV, CockroachDB 등 현대 분산 NewSQL은 **Multi-Raft 아키텍처**를 채택합니다:
- 전체 키스페이스를 정렬된 연속 구간인 **Region (또는 Range)** 단위(통상 64MB ~ 96MB)로 잘게 쪼갭니다.
- 각 Region은 독립적인 Raft Group을 형성하여 서로 다른 리더와 쿼럼 복제본을 가집니다.
- 하나의 물리 서버(Store)는 수백~수천 개의 Region 복제본(Peer)을 호스팅하며, 각 코어에서 Raft 스테이트 머신이 병렬로 실행됩니다.

---

## 2. Region Epoch 메커니즘과 단조 증가 순서성 (Epoch Monotonicity)

Multi-Raft 환경에서 가장 위험한 분산 장애는 **리전 분할(Split) 또는 병합(Merge) 시 발생하는 오래된 라우팅 캐시(Stale Route)에 의한 스플릿 브레인 쓰기**입니다.

### 2.1 Region Epoch 구조
각 Region 메타데이터에는 고유한 `RegionEpoch` 구조체가 포함됩니다:
- **`version` (토폴로지 / 범위 에포크)**:
  - Region의 `[start_key, end_key)` 범위가 변경될 때마다 단조 증가합니다.
  - **Split 발생 시**: 기존 좌측 리전은 `version += 1`이 되고, 우측 신규 리전은 초기 버전(1)으로 생성됩니다.
  - **Merge 발생 시**: 흡수하는 리전은 `version += max(src.version, tgt.version) + 1`로 증가하고, 흡수된 리전은 `Tombstone`으로 마킹됩니다.
- **`conf_ver` (멤버십 설정 에포크)**:
  - Raft 피어 추가(`AddPeer`), 제거(`RemovePeer`) 등 쿼럼 멤버가 바뀔 때마다 1씩 증가합니다.

### 2.2 StaleEpoch 방어 수학적 불변식
클라이언트 $C$가 보낸 요청의 에포크를 $E_C = (v_C, c_C)$, 서버 $S$의 현재 에포크를 $E_S = (v_S, c_S)$라고 할 때:

$$v_C < v_S \implies \text{거부 (STALE\_EPOCH\_VERSION)}$$
$$c_C < c_S \implies \text{거부 (STALE\_EPOCH\_CONF\_VER)}$$

만약 이 검사가 없다면:
- 리전 1 `["a", "z")`이 `["a", "m")`과 `["m", "z")`로 쪼개졌을 때,
- $v_C=1$인 구 클라이언트가 리전 1에 키 `"orange"`(현재 우측 리전 관할)를 쓰면 리전 1의 구 리더가 이를 수락하여, 우측 신규 리전과 완전히 분리된 데이터 오염이 발생합니다.

---

## 3. Range Lease와 선형적 읽기 (Linearizable Read)

### 3.1 Raft ReadIndex vs Leader Lease
Raft에서 선형적 읽기(Linearizability / External Consistency)를 달성하려면, 리더가 자신이 여전히 정당한 리더인지(네트워크 단절로 다른 노드가 새 리더로 선출되지 않았는지) 확인해야 합니다.
1. **ReadIndex 방식**:
   - 읽기 요청마다 다수 노드(Quorum)에 하트비트를 전송하여 왕복 확인.
   - 100% 안전하지만 네트워크 RTT 지연(수 밀리초)이 발생하여 읽기 QPS가 제약됨.
2. **Range Lease (Leader Lease) 방식**:
   - Raft 선거 타임아웃(Election Timeout)보다 짧은 시간 동안 유효한 **시간 기반 임대권(Lease)**을 리더가 획득.
   - 임대 기간 $[T_{\text{start}}, T_{\text{expire}}]$ 동안에는 팔로워들이 새 리더를 선출하지 않음이 수학적으로 보장됨.
   - 따라서 리더는 **Raft 쿼럼 통신 없이 로컬 메모리에서 나노초 단위로 즉각 선형적 읽기를 반환**할 수 있습니다.

### 3.2 Lease 만료와 Stale Read 위험
$$T_{\text{current}} \ge T_{\text{expire}} - \epsilon_{\text{drift}}$$
- 리더가 하트비트를 제때 보내지 못해 클러스터 시계가 `lease_expire_time`을 초과하면, 다른 파티션에서 이미 새로운 리더가 선출되었을 위험이 존재합니다.
- 이 상태에서 로컬 읽기를 허용하면 구 리더가 과거의 데이터를 반환하는 **Stale Read 선형성 파괴**가 일어나므로, 서버는 즉시 요청을 거부하거나 ReadIndex 쿼럼 검증으로 전환해야 합니다.
