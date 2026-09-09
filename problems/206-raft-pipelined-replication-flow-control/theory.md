# 분산 합의 Raft: Stop-and-Wait 복제 병목과 Pipelined 슬라이딩 윈도우 흐름 제어

## 1. 개요: 분산 합의와 네트워크 대역폭-지연 곱(BDP)의 충돌

분산 합의 알고리즘(Raft, Multi-Paxos)은 분산 데이터베이스(etcd, CockroachDB, TiKV, YugabyteDB)와 분산 스토리지(Ceph, HDFS JournalNode)에서 단일 장애점(SPOF) 없는 선형성(Linearizability) 보장을 위한 핵심 토대입니다.

Raft 프로토콜에서 리더(Leader)는 클라이언트로부터 쓰기 명령(Command)을 수신하면 자신의 로컬 로그에 추가한 뒤, 모든 팔로워(Follower) 노드들에게 `AppendEntries` 원격 프로시저 호출(RPC)을 통해 복제합니다. 과반수(Majority Quorum, $Q = \lfloor N/2 \rfloor + 1$) 노드가 해당 로그 엔트리를 영속화(fsync)하면 리더는 비로소 해당 로그를 커밋(Commit)하고 상태 머신에 적용한 뒤 클라이언트에게 성공 응답을 반환합니다.

그러나 클라우드 분산 환경(AWS Multi-AZ, Azure Availability Zones, Multi-Region)에서 Raft를 운영할 때 직면하는 가장 치명적인 병목은 **네트워크 왕복 시간(Round-Trip Time, RTT)**과 **복제 프로토콜의 전송 모델** 간의 불일치입니다.

---

## 2. Stop-and-Wait 복제의 물리적 한계와 처리량 절벽

### 2.1 Stop-and-Wait 모델
Diego Ongaro의 원본 Raft 논문(In Search of an Understandable Consensus Algorithm §3.6)에 기술된 기본 복제 모델은 단순한 **정지-대기(Stop-and-Wait)** 방식입니다.

```
[Leader]                                         [Follower]
   │                                                 │
   ├── AppendEntries (Batch #1, index 1~10) ────────>│
   │                                                 │ (디스크 fsync)
   │<── AppendEntriesResponse (Ack, matchIndex=10) ──┤
   │                                                 │ (1 RTT 경과: 10ms)
   ├── AppendEntries (Batch #2, index 11~20) ───────>│
   │                                                 │ (디스크 fsync)
   │<── AppendEntriesResponse (Ack, matchIndex=20) ──┤
```

리더는 팔로워에게 `AppendEntries` RPC를 발송한 뒤, 해당 팔로워로부터 `AppendEntriesResponse`가 돌아올 때까지 다음 로그의 전송을 일시 중단합니다.

### 2.2 수학적 처리량 상한선
네트워크 RTT가 $RTT_{\text{ms}}$이고, 단일 RPC에 포함할 수 있는 최대 엔트리 수가 $B$개(또는 최대 배치 바이트 크기 $M_{\text{batch}}$)라고 할 때:

$$\text{Max Throughput}_{\text{Stop-and-Wait}} = \frac{1}{\text{RTT}} \times B \quad [\text{entries/sec}]$$

만약 동일 랙 로컬 환경($\text{RTT} = 0.1\,\text{ms}$)이고 $B = 100$이라면:
$$\text{Max Throughput} = \frac{1}{0.0001\,\text{s}} \times 100 = 1,000,000\,\text{entries/sec}$$

그러나 가용 영역(AZ) 간 네트워크 지연이 $10\,\text{ms}$로 증가하면:
$$\text{Max Throughput} = \frac{1}{0.010\,\text{s}} \times 100 = 10,000\,\text{entries/sec}$$
만약 $B = 5$라면 처리량은 고작 **$500\,\text{entries/sec}$**로 곤두박질칩니다!

### 2.3 대역폭-지연 곱(Bandwidth-Delay Product, BDP)의 낭비
네트워크 링크 용량이 $C = 10\,\text{Gbps}$이고 $\text{RTT} = 10\,\text{ms}$일 때, 네트워크 파이프가 수용할 수 있는 데이터 양인 **BDP**는 다음과 같습니다:

$$\text{BDP} = C \times \text{RTT} = 10\,\text{Gbps} \times 0.010\,\text{s} = 100\,\text{Mbit} = 12.5\,\text{MB}$$

Stop-and-Wait 방식에서 1개 배치 크기가 $64\,\text{KB}$라면, $12.5\,\text{MB}$의 파이프라인 용량 중 고작 $0.5\%$만 활용하고 나머지 $99.5\%$의 대역폭을 허공에 버리는 극심한 비효율이 발생합니다.

---

## 3. 나이브 Unbounded Pipelining의 재앙: Rejection Storm과 Buffer Bloat

Stop-and-Wait의 병목을 없애기 위해 가장 단순하게 생각할 수 있는 해결책은 응답을 기다리지 않고 새 로그가 들어올 때마다 즉시 RPC를 연속 발송하는 **비제한 파이프라이닝(Unbounded Pipelining)**입니다.

```
[Unbounded Pipelining: 낙관적 연속 발송]
Leader ──── RPC #1 (idx 10~15) ─────────────────────────> Follower
Leader ──── RPC #2 (idx 16~20) ─────────────────────────> Follower
Leader ──── RPC #3 (idx 21~25) ─────────────────────────> Follower
Leader ──── RPC #4 (idx 26~30) ─────────────────────────> Follower
...
Leader ──── RPC #30 (idx 150~155) ──────────────────────> Follower
```

그러나 실제 분산 환경에서는 다음과 같은 치명적인 장애가 발생합니다:

### 3.1 소켓 버퍼 팽창 및 메모리 고갈 (Buffer Bloat)
팔로워 노드가 잠시 동안 디스크 I/O 병목(ext4 저널 플러시, RocksDB 컴팩션)이나 가비지 컬렉션(JVM GC pause, Go STW)으로 인해 $100\,\text{ms}$ 동안 멈칫(Stall)하면:
- 리더는 팔로워가 멈춘 줄 모르고 수백 개의 RPC를 연속으로 생성하여 소켓 송신 버퍼(`SO_SNDBUF`)에 밀어넣습니다.
- 커널 소켓 버퍼가 가득 차면 사용자 공간 메모리에 RPC 큐가 거대하게 누적되어 리더 프로세스가 OOM(Out Of Memory) 킬러에 의해 강제 종료됩니다.

### 3.2 연쇄 거절 폭풍 (Cascading Rejection Storm)
더욱 무서운 문제는 **로그 불일치(Log Divergence)** 상황에서 발생합니다.

```
[팔로워의 인덱스 10에 이전 리더의 비커밋 충돌 로그 존재]
Follower Log: [idx 9: Term 1] [idx 10: Term 1 (충돌!)]

Leader가 Unbounded Pipelining으로 RPC #1~#10을 연속 전송:
- RPC #1: prevLogIndex=9, prevLogTerm=2 (불일치!) ==> REJECT!
- RPC #2: prevLogIndex=15, prevLogTerm=2 ==> Follower에 idx 15 없음! ==> REJECT!
- RPC #3: prevLogIndex=20, prevLogTerm=2 ==> Follower에 idx 20 없음! ==> REJECT!
...
- RPC #10: prevLogIndex=55, prevLogTerm=2 ==> Follower에 idx 55 없음! ==> REJECT!
```

1. RPC #1이 거절되었음에도 이미 파이프라인에 발송된 RPC #2부터 #10까지 **10개의 RPC가 연속으로 거절**됩니다.
2. 리더는 거절 응답이 올 때마다 `nextIndex`를 감소시키며 재전송을 시도하므로, 네트워크에는 $O(W^2)$의 무의미한 거절 패킷과 재전송 패킷이 교차하며 폭풍(Storm)을 일으킵니다.
3. CPU 사용률이 100%로 치솟고, 정상적인 하트비트마저 타임아웃되어 불필요한 리더 선출(Split-Brain / Leader Flapping)로 이어집니다.

---

## 4. Production-grade Pipelined Flow Control: etcd/raft 아키텍처

Kubernetes의 백엔드 스토리지인 etcd(`go.etcd.io/raft`)와 TiKV(`tikv/raft-rs`)는 이 문제를 해결하기 위해 **이중 진행 상태(Progress States)**와 **In-flight 슬라이딩 윈도우 흐름 제어(Inflights Window Flow Control)**를 결합한 표준 아키텍처를 수립했습니다.

```
                       ┌─────────────────────────┐
                       │       StateProbe        │ (탐색 모드: inflights <= 1)
                       │  정확한 matchIndex 탐색 │
                       └───────────┬─────────────┘
                                   │
                    MsgAppResp     │    거절 발생 (MsgAppResp with Reject)
                    성공 응답 수신 │    진행상태 강등 & Inflight 전량 파기
                                   ▼
                       ┌─────────────────────────┐
                       │     StateReplicate      │ (고속 복제 모드: inflights <= W)
                       │   파이프라인 슬라이딩   │
                       │     윈도우 스트리밍     │
                       └─────────────────────────┘
```

### 4.1 이중 상태 머신 (Dual Progress States)

각 팔로워 노드에 대해 리더는 독립적인 `Progress` 상태를 유지합니다:

1. **`StateProbe` (탐색 상태)**:
   - 새 리더로 선출된 직후, 노드가 재시작된 직후, 또는 **로그 거절 응답을 수신한 직후** 진입합니다.
   - 이 상태에서는 **동시에 단 1개의 RPC만** 보낼 수 있습니다 (`max_inflight = 1`).
   - 팔로워의 실제 로그 일치점(`matchIndex`)이 어디인지 확인하기 전까지는 절대 대량 파이프라이닝을 개시하지 않습니다.
   - 팔로워로부터 성공(`MsgAppResp.Reject == false`) 응답이 돌아오면 즉시 `StateReplicate`로 승격됩니다.

2. **`StateReplicate` (고속 파이프라이닝 상태)**:
   - 팔로워와의 일치점이 확인된 정상 운영 상태입니다.
   - 리더는 팔로워의 응답을 기다리지 않고 최대 `max_inflight` (기본값 $8 \sim 32$)개의 RPC를 연속 발송할 수 있습니다.
   - 발송할 때마다 `nextIndex`를 낙관적으로 전진시킵니다.

### 4.2 In-flight 슬라이딩 윈도우 (`tracker.Inflights`)

리더는 팔로워별로 원형 큐(Ring Buffer) 형태의 In-flight 윈도우를 관리합니다:

```python
class InflightWindow:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.buffer = []  # [(rpc_id, end_index), ...]

    def full(self) -> bool:
        return len(self.buffer) >= self.capacity

    def add(self, rpc_id: int, end_index: int):
        self.buffer.append((rpc_id, end_index))

    def free_to(self, match_index: int):
        # match_index 이하의 로그를 담당하던 In-flight 엔트리를 모두 제거
        while self.buffer and self.buffer[0][1] <= match_index:
            self.buffer.pop(0)

    def reset(self):
        self.buffer.clear()
```

- **흐름 제어 백프레셔(Backpressure)**:
  팔로워의 응답이 지연되어 `inflights.full()`이 되면, 리더는 해당 팔로워에 대한 추가 RPC 전송을 즉시 중단(Throttle)합니다. 이로써 팔로워의 GC pause나 디스크 스톨 시 리더의 소켓 버퍼 팽창이 원천 차단됩니다.
- **성공 응답 수신 시 윈도우 회수 (`free_to`)**:
  팔로워가 `match_index = 50`으로 응답하면, `end_index <= 50`인 모든 In-flight 항목이 즉시 방출되어 윈도우 슬롯이 열립니다. 리더는 열린 슬롯만큼 새로운 로그 배치를 즉시 전송합니다.

### 4.3 거절 시 In-flight 즉각 파기 및 강등 (Wipeout on Reject)

Pipelined Flow Control의 가장 중요한 안전 장치는 **거절 시의 즉각적인 상태 정리**입니다:

```
[StateReplicate 도중 팔로워 거절 응답 도착]
1. 진행 상태를 즉시 StateProbe로 강등! (StateReplicate -> StateProbe)
2. inflights.reset() 호출하여 현재 In-flight 윈도우 전량 파기!
3. 기존 In-flight RPC ID들을 무효 집합으로 등록 (이후 도착하는 잔여 응답 폐기)
4. 팔로워의 conflictIndex 힌트를 반영하여 nextIndex 재설정
5. 정확한 1회의 탐색 RPC만 발송하여 대기
```

이 규칙 덕분에 Unbounded Pipelining에서 발생하던 10~30회의 연쇄 거절 폭풍이 **정확히 1회의 거절과 1회의 탐색만으로 완벽히 종식**됩니다.

---

## 5. Raft 불변식 및 쿼럼 커밋 법칙

### 5.1 과반수 쿼럼 (Quorum Size)
$N$개 노드로 구성된 클러스터에서 합의를 달성하기 위한 최소 과반수 노드 수 $Q$는 다음과 같습니다:

$$Q = \left\lfloor \frac{N}{2} \right\rfloor + 1$$

- $N = 3$ 노드: $Q = 2$
- $N = 5$ 노드: $Q = 3$

리더는 자신의 로컬 로그 길이를 포함하여 클러스터 전체 노드의 `match_index`를 수집하고 내림차순 정렬했을 때, $Q$-번째 노드의 `match_index`를 커밋 후보 인덱스 $M$으로 도출합니다.

### 5.2 이전 임기 로그의 독립적 커밋 금지 (Safety Rule Section 5.4.2)
Raft의 가장 중요한 안전성 불변식 중 하나는:
> **"리더는 이전 임기(Term)의 로그 엔트리가 과반수 노드에 복제되었다 하더라도, 현재 임기(Current Term)의 로그 엔트리가 과반수에 도달하기 전까지는 이전 임기 로그를 독자적으로 커밋할 수 없다."**

따라서 리더는 $M > \text{commit\_index}$일 때, 반드시 해당 위치의 로그가 현재 임기에 생성된 엔트리(`leader_log[M - 1].term == current_term`)인지 확인한 후에만 커밋 인덱스를 $M$으로 전진시킵니다.

---

## 6. 프로덕션 환경 튜닝 및 아키텍처 권장사항

| 파라미터 / 전략 | 권장 설정값 | 엔지니어링 근거 |
| :--- | :--- | :--- |
| `max_inflight` | `8` ~ `32` (etcd 기본값: 256) | 네트워크 RTT $10\,\text{ms}$ 기준 $16 \sim 32$개로 BDP를 100% 포화시키며, 장애 시 메모리 소비를 엄격히 제한 |
| `batch_size` | `64KB` ~ `512KB` (엔트리 $10 \sim 50$개) | 너무 작으면 syscall 및 패킷 오버헤드 증가, 너무 크면 serialization 지연시간 증가 |
| 이종 RTT 쿼럼 | 비동기 파이프라인 | 5노드 Multi-AZ 환경에서 지연이 큰 원격 노드($40\,\text{ms}$)의 응답을 기다리지 않고 빠른 로컬 노드($4\,\text{ms}, 8\,\text{ms}$)만으로 초저지연 과반수 커밋 달성 |
| GC & fsync 보호 | Inflight Window Throttle | 디스크 fsync 스톨 시 백프레셔로 리더 소켓 버퍼 팽창 방어 |
| 충돌 복구 | `StateProbe` 강등 + Inflight Wipeout | 연쇄 거절 폭풍 0건 유지 및 단 1 RTT 내 일치점 수렴 보장 |
