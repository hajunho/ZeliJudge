# 문제 220 이론: 구글 스패너(Google Spanner) TrueTime API, 커밋 대기(Commit Wait)와 선형성(Linearizability) 증명

---

## 1. 분산 시스템에서 물리적 시계(Physical Clock)의 근본적 한계

분산 컴퓨팅 환경에서 독립된 서버 노드들은 각자의 크리스탈 발진기(Quartz Crystal Oscillator)에 의존하는 로컬 물리 시계를 갖습니다. 그러나 크리스탈은 온도, 전압, 노화에 따라 주파수가 흔들리는 **클럭 드리프트(Clock Drift)** 현상을 겪습니다.

### 1.1 NTP(Network Time Protocol)의 한계
일반적인 데이터센터에서 NTP를 사용하여 시계를 동기화할 경우:
- 네트워크 지연(Jitter), 패킷 큐잉, 비대칭 라우팅 경로로 인해 수 밀리초에서 수백 밀리초에 이르는 오차($\pm 50\text{ms} \sim 500\text{ms}$)가 발생합니다.
- 만약 두 트랜잭션 $T_1, T_2$가 서로 다른 데이터센터에서 발생할 때, $T_1$이 절대 시간 기준으로 먼저 완료되었음에도 $T_2$의 로컬 시계가 뒤처져 있다면 $T_2$의 타임스탬프가 $T_1$보다 작아지는 **인과성 역전(Causality Inversion)**이 발생합니다.
- 따라서 순수 NTP 시계는 분산 데이터베이스에서 선형성(Linearizability / External Consistency)을 보장하는 글로벌 타임스탬프로 사용될 수 없습니다.

### 1.2 논리적 시계의 대안과 비용
- **Lamport Timestamps / Vector Clocks**: 인과 관계($A \to B$)를 추적할 수 있으나, 시스템 외부의 인과 관계(사용자가 $T_1$ 성공 문자를 받고 전화로 다른 사용자에게 알려 $T_2$를 실행한 경우)는 추적하지 못합니다.
- **CockroachDB Hybrid Logical Clocks (HLC)**: 물리 시계와 논리 시계를 결합하지만, 노드 간 드리프트가 지정된 최대 오차($\text{max\_offset}$, 예: 500ms)를 초과하면 트랜잭션을 강제 재시작하거나 노드를 종료해야 합니다.

---

## 2. 구글 스패너 TrueTime API 아키텍처

구글은 이 문제를 해결하기 위해 전 세계 주요 데이터센터에 전용 타임 마스터(Time Master) 하드웨어를 배치했습니다.

```
 [Google TrueTime Master Architecture]

              ┌──────────────────┐       ┌──────────────────┐
              │   GPS Receiver   │       │ Rubidium Atomic  │
              │   Time Master    │       │   Time Master    │
              └────────┬─────────┘       └────────┬─────────┘
                       │                          │
                       └────────────┬─────────────┘
                                    │
                                    ▼
                         [Datacenter Time Daemon]
                                    │
               Polls every 30s & calculates drift bound (ε)
                                    │
                                    ▼
              [TrueTime API: TT.now() -> [earliest, latest]]
```

### 2.1 하드웨어 이중화 및 장애 격리
- **GPS 수신기**: 위성 신호 수신을 통해 나노초 단위의 정확한 절대 시각을 제공합니다. 단, 안테나 단선, 기상 악화, 위성 기만(Spoofing) 공격에 취약합니다.
- **루비듐 원자 시계(Rubidium Atomic Clock)**: 외부 신호 없이 독립적으로 진동수를 측정하여 GPS 장애 시에도 극도로 낮은 드리프트($< 1\mu\text{s}/\text{day}$)를 유지합니다. 단, 시간이 지남에 따라 점진적으로 오차가 누적됩니다.
- 두 소스가 상호 불일치할 경우 '거짓말하는 시계(Liar Master)'를 탐지하여 클러스터에서 퇴출합니다.

### 2.2 TrueTime API 인터페이스
TrueTime API는 단일 시각을 반환하지 않고, 불확실성 상한 $\epsilon$을 포함하는 **시간 구간(Interval)**을 노출합니다:
$$\text{TT.now}() = [t_{\text{earliest}}, t_{\text{latest}}] = [t_{\text{local}} - \epsilon, t_{\text{local}} + \epsilon]$$
- 절대 시각 $t_{\text{real}}$은 반드시 이 구간 내에 존재함을 보장합니다:
  $$t_{\text{earliest}} \le t_{\text{real}} \le t_{\text{latest}}$$
- 평상시 구글 인프라에서 $\epsilon$은 **1ms ~ 7ms** 수준을 유지합니다.

---

## 3. 커밋 대기(Commit Wait)와 선형성 수학적 증명

스패너의 목표는 **외부 일관성(External Consistency)** 보장입니다:
$$\text{If } T_2 \text{ begins after } T_1 \text{ commits (in absolute real time), then } s_2 > s_1$$

### 3.1 커밋 타임스탬프 결정 규칙
트랜잭션 $T_1$의 코디네이터가 2PC Prepare 단계를 완료한 절대 시각을 $t_{\text{prepare}}(T_1)$이라 할 때, 코디네이터는 로컬 `TT.now()`를 호출하여 타임스탬프 $s_1$을 결정합니다:
$$s_1 \ge \text{TT.now}().\text{latest} = t_{\text{prepare}}(T_1) + \text{offset}_1 + \epsilon_1$$
오프셋의 정의상 $t_{\text{local}} = t_{\text{real}} + \text{offset}$이며 $|\text{offset}| \le \epsilon$ 이므로:
$$s_1 \ge t_{\text{prepare}}(T_1) + \epsilon_1$$

### 3.2 커밋 대기 규칙 (Commit Wait Rule)
코디네이터는 로컬 시계 기준 $\text{TT.now}().\text{earliest} > s_1$이 될 때까지 클라이언트에 커밋 완료 응답을 보내지 않고 2PL 락을 계속 보유합니다:
$$t_{\text{commit}}(T_1) \ge t \quad \text{where} \quad \text{TT.now}(t).\text{earliest} > s_1$$
$$\implies (t + \text{offset}_1) - \epsilon_1 > s_1 \implies t > s_1 + \epsilon_1 - \text{offset}_1$$
최악의 경우($\text{offset}_1 = -\epsilon_1$) 코디네이터는 최소 $2\epsilon_1$ 동안 대기해야 합니다:
$$t_{\text{commit}}(T_1) > s_1$$

### 3.3 선형성 증명 (Proof of Linearizability)
트랜잭션 $T_2$가 $T_1$의 커밋 완료 이후에 시작된다고 가정합시다:
$$t_{\text{start}}(T_2) > t_{\text{commit}}(T_1)$$
트랜잭션 $T_2$의 코디네이터가 부여하는 타임스탬프 $s_2$는 다음과 같습니다:
$$s_2 \ge \text{TT.now}(t_{\text{start}}(T_2)).\text{latest} \ge t_{\text{start}}(T_2) - \epsilon_2 + \epsilon_2 = t_{\text{start}}(T_2)$$
앞서 유도한 부등식을 결합하면:
$$s_2 \ge t_{\text{start}}(T_2) > t_{\text{commit}}(T_1) > s_1$$
$$\therefore s_2 > s_1 \quad (Q.E.D.)$$

어떠한 중앙 집중형 마스터 노드나 분산 락 조정자 없이도, 각 노드가 순수하게 자신의 로컬 TrueTime API와 $2\epsilon$ 커밋 대기만을 수행함으로써 전 세계 모든 데이터센터에 걸쳐 완벽한 외부 일관성(선형성)이 성립함을 수학적으로 증명할 수 있습니다.

---

## 4. 시계 불확실성($\epsilon$) 폭증의 시스템적 영향

```
 [Throughput & Latency vs Clock Uncertainty ε]

   Commit Wait Time = 2 * ε
   -----------------------------------------------------
   ε = 2ms   ==> Commit Wait = 4ms   (High Throughput)
   ε = 7ms   ==> Commit Wait = 14ms  (Normal Operation)
   ε = 50ms  ==> Commit Wait = 100ms (High Contention)
   ε = 150ms ==> Commit Wait = 300ms (Lock Queue Collapse!)
```

1. **핫스팟 키의 처리량 상한 (Throughput Limit)**:
   특정 키에 대한 락 보유 시간은 최소 $2\epsilon$에 비례합니다.
   단일 키의 최대 쓰기 처리량(TPS)은 다음과 같이 제한됩니다:
   $$\text{Max TPS}_{\text{single-key}} \le \frac{1}{2\epsilon + t_{\text{exec}}}$$
   - $\epsilon = 4\text{ms}$ 일 때: 약 $100 \sim 120 \text{ TPS}$ 달성 가능
   - $\epsilon = 100\text{ms}$ 일 때: 최대 $4 \sim 5 \text{ TPS}$로 급락

2. **락 대기 큐 타임아웃과 계단식 장애**:
   $\epsilon$이 100ms 이상으로 폭증하면 대기 중인 트랜잭션들이 `lock_wait_timeout_ms`를 초과하여 연쇄적으로 롤백(`ABORT`)됩니다.
   클라이언트는 재시도 폭풍(Retry Storm)을 유발하여 시스템 전체가 붕괴합니다.
