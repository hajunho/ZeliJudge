# [분산 시스템/ACID 트랜잭션] FoundationDB의 탈중앙화 트랜잭션 아키텍처: 시퀀서(Sequencer), 프록시(Proxy), 리졸버(Resolver)의 읽기 버전(Read Version) 할당 및 키 충돌 감지(Conflict Detection) 엔진

## 문제 설명

애플(Apple)의 CloudKit(수억 대의 iOS 기기 간 사진/파일/연락처 동기화 백엔드), 스노우플레이크(Snowflake)의 클라우드 메타데이터 카탈로그, 에픽게임즈(Epic Games)의 초대규모 게임 플랫폼을 지탱하는 핵심 분산 데이터베이스는 바로 **FoundationDB**입니다.

전통적인 분산 데이터베이스(Spanner, CockroachDB, TiDB)는 스토리지 노드가 Raft/Paxos 합의와 트랜잭션 잠금(2PL/2PC)을 직접 수행하는 일체형 구조를 채택하지만, FoundationDB는 SIGMOD 2021 논문으로 유명한 **"트랜잭션 연산과 스토리지의 완전 분리(Decoupled Architecture)"**를 채택하여 초당 수백만 건의 엄격한 직렬화(Strict Serializability) 트랜잭션을 지연시간 없이 처리합니다:

1. **시퀀서 (Sequencer)**:
   - 클러스터의 단일 시계 역할을 수행하며, 단조 증가하는 **읽기 버전(Read Version)**과 커밋 배치 단위의 **커밋 버전(Commit Version)**을 나노초 단위로 발급합니다.
2. **트랜잭션 프록시 (Transaction Proxies)**:
   - 클라이언트의 트랜잭션 요청을 수신하고, 시퀀서로부터 읽기 버전을 취득하며, 커밋 시 클라이언트들의 쓰기 요청을 배치(Batch)로 묶어 리졸버로 전송합니다.
3. **리졸버 (Resolvers)와 샤딩된 키 충돌 감지 (Conflict Detection)**:
   - 리졸버는 디스크를 전혀 사용하지 않는 **순수 메모리 기반 충돌 검사 노드**입니다.
   - 전체 키 공간(Key Space)을 범위별로 샤딩하여 분담하며, 최근 커밋된 트랜잭션들의 **5초 이동 윈도우(Rolling History Window)**를 유지합니다.
   - 트랜잭션 $T$가 $R_v$ 시점에 읽은 키 목록($K_{read}$)에 대해, $R_v < C_v \le \text{CurrentVersion}$ 범위 내에서 다른 트랜잭션에 의해 수정된 이력이 존재하는지 검사합니다:
     - 충돌 발견 시: `not_committed` (에러 코드 1020, `write_conflict`)를 반환하여 트랜잭션을 즉시 중단(Abort)시킵니다.
     - 충돌 부재 시: 모든 담당 리졸버가 커밋을 승인하고 새 커밋 버전 $C_v$를 키 이력에 기록합니다.
4. **5초 MVCC 만료 (`transaction_too_old`, 에러 코드 1007)**:
   - 트랜잭션의 $R_v$가 리졸버의 보관 한계($\text{CurrentVersion} - \text{MaxHistoryVersions}$)보다 오래된 경우, 충돌 여부를 확신할 수 없으므로 `transaction_too_old`로 즉시 거절합니다.
5. **읽기 전용 트랜잭션 (Read-Only Snapshot)**:
   - 읽기 전용 트랜잭션은 리졸버에 등록하거나 잠금을 걸 필요 없이, 시퀀서가 부여한 $R_v$ 이하의 스냅샷 데이터만을 일관성 있게 읽고 즉시 커밋 완료됩니다.

클라우드 인프라 및 분산 DB 코어 엔지니어링 팀의 일원이 되어, FoundationDB의 시퀀서, 다중 샤딩 리졸버, 프록시 커밋 파이프라인을 구축하고, 동시 다발적인 트랜잭션 요청에 대해 정확한 읽기/커밋 버전 할당, 키 범위 충돌 검사, 5초 MVCC 윈도우 만료 처리 및 최종 KV 스토어 일관성을 유지하는 **FoundationDB 트랜잭션 리졸버 엔진**을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "initial_version": 1000,
    "max_history_versions": 100,
    "resolvers": [
      {"id": "res_0", "start_key": null, "end_key": "m"},
      {"id": "res_1", "start_key": "m", "end_key": null}
    ],
    "initial_kv": {
      "acc_alice": 1000,
      "acc_bob": 500
    }
  },
  "transactions": [
    {
      "tx_id": "tx_1",
      "type": "READ_WRITE",
      "read_version": 1000,
      "read_keys": ["acc_alice", "acc_bob"],
      "write_ops": {
        "acc_alice": 900,
        "acc_bob": 600
      }
    }
  ]
}
```

- `config`:
  - `initial_version` (Integer): 초기 시퀀서 버전 (기본 1000).
  - `max_history_versions` (Integer): 리졸버가 유지하는 최대 MVCC 이력 버전 수 (기본 100).
  - `resolvers` (Array): 샤딩된 리졸버 정의 (`start_key`, `end_key`).
  - `initial_kv` (Object): 스토리지의 초기 Key-Value 상태.
- `transactions` (Array of Object):
  - `tx_id` (String): 트랜잭션 식별자
  - `type` (String): `"READ_WRITE"` 또는 `"READ_ONLY"`
  - `read_version` (Integer): 트랜잭션이 읽기를 시작한 시점의 버전
  - `read_keys` (Array of String): 트랜잭션이 읽은 키 목록 (충돌 검사 대상)
  - `write_ops` (Object): 커밋 성공 시 기록할 키-값 맵

---

## 출력 형식

표준 출력(stdout)으로 트랜잭션 처리 결과 요약 및 각 트랜잭션의 커밋/중단 상세, 최종 KV 스토어 상태가 포함된 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "summary": {
    "initial_version": 1000,
    "final_version": 1001,
    "total_transactions": 1,
    "committed_count": 1,
    "aborted_count": 0
  },
  "transactions": [
    {
      "tx_id": "tx_1",
      "status": "COMMITTED",
      "type": "READ_WRITE",
      "read_version": 1000,
      "commit_version": 1001,
      "written_keys": ["acc_alice", "acc_bob"]
    }
  ],
  "final_kv_store": {
    "acc_alice": 900,
    "acc_bob": 600
  }
}
```
