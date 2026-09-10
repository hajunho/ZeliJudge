# [분산 합의/BFT] PBFT(Practical Byzantine Fault Tolerance) 3단계 합의와 프라이머리 이중 제안(Equivocation) 방어 및 뷰 체인지(View Change) 엔진

## 문제 설명

전통적인 크래시 장애 허용(Crash Fault Tolerance, CFT) 합의 알고리즘(Paxos, Raft)은 노드가 다운되거나 네트워크 지연이 발생할 수는 있어도, 노드가 악의적으로 변조된 메시지를 보내거나 동일한 시퀀스 번호에 대해 서로 다른 트랜잭션을 이중 제안(Equivocation)하지 않는다는 선의(Benign)를 전제로 합니다.

그러나 블록체인 컨소시엄, 우주 항공 제어, 금융 결제망, 보안 강화 분산 시스템에서는 악의적인 침입자나 메모리 비트 플립으로 인해 거짓 정보를 생성하는 **비잔틴 장애(Byzantine Fault)**가 발생할 수 있습니다.
1999년 미겔 카스트로(Miguel Castro)와 바버라 리스코프(Barbara Liskov)가 발표한 **PBFT(Practical Byzantine Fault Tolerance)**는 비동기 네트워크 환경에서 $N \ge 3f + 1$개의 노드로 최대 $f$개의 임의 비잔틴 노드(공격자, 침입 노드)가 존재하더라도 전역적 안전성(Safety)과 활동성(Liveness)을 보장하는 역사적인 BFT 알고리즘입니다.

분산 시스템 보안 엔지니어가 되어, PBFT의 핵심 3단계 합의 프로토콜(**Pre-Prepare $	o$ Prepare $	o$ Commit**)과 악의적인 리더의 **이중 제안 공격(Equivocation Attack) 탐지**, 그리고 리더 장애 시 정족수 기반으로 새로운 리더를 선출하는 **뷰 체인지(View Change) 프로토콜**을 완벽하게 재현하는 **PBFT 비잔틴 합의 및 보안 엔진**을 구현하십시오.

---

## PBFT 프로토콜 및 알고리즘 규격

### 1. 클러스터 토폴로지 및 파라미터
- 전체 노드 수 $R = 3f + 1$, 허용 비잔틴 노드 수 $f = \lfloor (R - 1) / 3 floor$.
- 뷰 번호 $v$에 따른 리더(Primary) 노드:
  $$	ext{primary} = 	ext{nodes}[v mod R]$$
  나머지 노드는 백업(Backup) 노드로 동작합니다.
- 정족수(Quorum):
  - **Prepared 정족수**: 동일한 $(v, n, d)$에 대해 $2f$개의 유효한 Prepare 메시지 (자신 포함).
  - **Committed 정족수**: 동일한 $(v, n, d)$에 대해 $2f + 1$개의 유효한 Commit 메시지 (자신 포함).
  - **View-Change 정족수**: 동일한 대상 뷰 $v+1$에 대해 $2f + 1$개의 유효한 View-Change 메시지.

### 2. 3단계 합의 파이프라인 (Three-Phase Consensus)
1. **Pre-Prepare 단계**:
   - 클라이언트 요청이 도착하면 리더(Primary)는 단조 증가하는 시퀀스 번호 $n$을 부여하고 요청의 암호학적 다이제스트 $d = 	ext{sha256}(m)$를 계산합니다.
   - 모든 노드에게 `<<PRE-PREPARE, v, n, d>, m>` 메시지를 브로드캐스트합니다.
   - 백업 노드는 다음 조건을 만족할 때만 Pre-Prepare를 수락합니다:
     - 현재 뷰가 $v$와 일치함.
     - 이미 동일한 $(v, n)$에 대해 다른 다이제스트 $d' 
eq d$를 수락한 적이 없음!
     - 만약 이미 다른 $d'$를 받았는데 또 다른 $d$가 오면 **이중 제안 공격**으로 간주하고 거절하며 진단 코드 `PRIMARY_EQUIVOCATION_DETECTED: node={node_id}, view={v}, seq={n}`를 등록합니다.
2. **Prepare 단계**:
   - Pre-Prepare를 수락한 정상 노드는 모든 피어에게 `<PREPARE, v, n, d, i>` 메시지를 브로드캐스트합니다.
   - 각 노드는 동일한 $(v, n, d)$에 대해 $2f$개 이상의 Prepare 메시지(자신의 Prepare 포함)를 수집하면 **Prepared 인증서(Prepared Certificate)**를 확정합니다.
3. **Commit 단계**:
   - Prepared 인증서를 획득한 정상 노드는 모든 피어에게 `<COMMIT, v, n, d, i>` 메시지를 브로드캐스트합니다.
   - 각 노드는 동일한 $(v, n, d)$에 대해 $2f + 1$개 이상의 Commit 메시지(자신의 Commit 포함)를 수집하면 **Committed-Local 인증서**를 확정합니다.
4. **실행(Execute) 단계**:
   - 이전 시퀀스 $n-1$까지의 모든 트랜잭션이 로컬 상태 머신에 실행 완료되었을 때, 비로소 시퀀스 $n$의 명령어를 로컬 `state_store`에 적용합니다 (엄격한 순차 실행 순서 보장).
   - `SET key value`: 키-값 저장소에 저장.
   - `DEL key`: 키-값 저장소에서 삭제.

### 3. 비잔틴 공격 시나리오 및 뷰 체인지 (View Change)
- **이중 제안 공격 (Equivocation Attack)**:
  - 악의적인 비잔틴 리더가 노드들의 절반에는 다이제스트 $A$를, 나머지 절반에는 변조된 다이제스트 $B$를 전달합니다.
  - 정직한 노드들은 서로 다른 다이제스트를 교차 확인하여 어느 쪽도 $2f$개의 Prepare를 모으지 못하게 방어합니다.
- **타이머 만료 및 뷰 체인지 전이**:
  - 요청이 처리되지 않고 `timeout_ms` 시간이 만료되면, 정직한 노드들은 현재 뷰에서의 작업을 즉시 중단하고 `state = "VIEW_CHANGE"`로 전이합니다.
  - 모든 피어에게 새로운 뷰 $v+1$을 요청하는 `<VIEW-CHANGE, v+1, i>` 메시지를 전송합니다.
  - 새로운 리더 $p' = (v+1) mod R$가 $2f + 1$개 이상의 유효한 View-Change 투표를 수집하면:
    - 뷰 번호가 $v+1$로 전진하고 모든 노드가 `state = "NORMAL"`로 복귀합니다.
    - 진단 코드 `VIEW_CHANGE_SUCCESSFUL: view {v} -> {v+1}, new_primary={new_primary}`를 기록합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "nodes": ["node_0", "node_1", "node_2", "node_3"],
  "byzantine_nodes": ["node_0"],
  "initial_view": 0,
  "timeout_ms": 3000,
  "workload_events": [
    {
      "type": "CLIENT_REQUEST",
      "request": {"client_id": "c1", "tx_id": "TX_001", "op": "SET balance 1000", "equivocate": true}
    },
    {
      "type": "ADVANCE_TIME",
      "delta_ms": 3500
    },
    {
      "type": "CLIENT_REQUEST",
      "request": {"client_id": "c2", "tx_id": "TX_002", "op": "SET balance 2000", "equivocate": false}
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 계산된 결과를 JSON 문자열(단일 라인)로 출력합니다:
```json
{
  "cluster_size": 4,
  "fault_tolerance_f": 1,
  "final_view": 1,
  "primary_node": "node_1",
  "consensus_status": "CONSENSUS_STABLE",
  "total_committed_txs": 1,
  "committed_tx_ids": ["TX_002"],
  "cluster_state_store": {"balance": "2000"},
  "nodes": {
    "node_0": { ... },
    "node_1": { ... }
  },
  "security_events": [
    "PRIMARY_EQUIVOCATION_ATTACK: primary=node_0, seq=1",
    "VIEW_CHANGE_INITIATED: reason=TIMEOUT_TX_TX_001, target_view=1",
    "VIEW_CHANGE_SUCCESSFUL: view 0 -> 1, new_primary=node_1"
  ]
}
```
