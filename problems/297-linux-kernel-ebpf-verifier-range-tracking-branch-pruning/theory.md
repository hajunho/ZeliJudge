# 리눅스 커널 eBPF 검증기: 추상 해석과 분기 가지치기 (eBPF Verifier: Abstract Interpretation & Branch Pruning)

## 1. 개요 및 배경

리눅스 커널 eBPF(Extended Berkeley Packet Filter)는 현대 클라우드 인프라, 네트워킹(Cilium, Katran), 시스템 관측(BCC, bpftrace), 그리고 런타임 보안(Falco, Tetragon)의 핵심 근간입니다.
커널 공간에서 임의의 사용자 작성 코드를 실행할 수 있다는 것은 혁신적인 유연성을 제공하지만, 동시에 포인터 오염, 널 역참조, 커널 메모리 유출, 영구 락(Lock) 및 DoS를 유발할 수 있는 치명적인 보안 위협이 됩니다.

리눅스 커널은 이를 해결하기 위해 `kernel/bpf/verifier.c`라는 정교한 정적 분석기를 내장하고 있습니다. eBPF 검증기는 프로그램을 실제로 실행하지 않고, 수학적인 **추상 해석(Abstract Interpretation)**을 통해 모든 가능한 제어 흐름 경로(Control Flow Graph)에서 프로그램이 안전함을 증명합니다.

---

## 2. 추상 해석(Abstract Interpretation)과 구간 산술(Interval Arithmetic)

실제 실행 환경에서 레지스터는 하나의 구체적인 64비트 정수(Concrete Value)를 갖지만, 검증 시점에는 사용자가 전달할 패킷 데이터나 시스템 콜 인자의 정확한 값을 알 수 없습니다.
따라서 검증기는 레지스터를 구체값 대신 **가능한 값들의 상한/하한 범위(Interval [umin, umax])**로 추상화하여 추적합니다.

### 2.1 범위 좁히기 (Range Narrowing via Conditional Branches)
조건부 분기 명령(`JGT`, `JEQ` 등)을 만나면 검증기는 상태를 분기 경로와 직진 경로로 복제하고, 각 분기의 조건에 맞게 수치 구간을 좁힙니다.
예를 들어 $R_3 \in [0, 65535]$인 상태에서 `if (R3 > 20) goto branch;` 명령을 만나면:
- **분기 경로(Branch Taken)**: $R_3 \in [\max(0, 20 + 1), 65535] = [21, 65535]$
- **직진 경로(Fallthrough)**: $R_3 \in [0, \min(65535, 20)] = [0, 20]$

이를 통해 직진 경로에서 $R_3$을 기반으로 고정 크기 버퍼(예: 30바이트)에 접근할 때 오버플로우가 발생하지 않음을 정적 증명할 수 있습니다.

---

## 3. 포인터 검증 및 패킷 경계 안전성 (Pointer Safety & Packet Bounds)

XDP(eXpress Data Path)나 TC 필터에서 네트워크 패킷 버퍼는 `data`(시작 포인터)와 `data_end`(끝 포인터)로 주어집니다.
C 언어 수준에서 다음과 같은 경계 검사를 수행합니다:
```c
if ((void *)(data + 14) > data_end)
    return XDP_DROP;
```
eBPF 검증기는 이 비교 명령을 인식하여 `data` 레지스터(`PTR_TO_PACKET`)에 대해 `pkt_range = 14` 바이트가 안전함을 기록합니다.
이후 `*(u32 *)(data + 0)`과 같이 메모리 로드(`LDX`)가 발생하면, 접근하려는 최대 오프셋(0 + 4 = 4)이 증명된 범위(14) 이내인지를 검사합니다. 만약 검사를 거치지 않고 오프셋 12에서 4바이트를 읽으려 하면(12 + 4 = 16 > 14) 검증기는 즉시 프로그램을 거부(Reject)합니다.

---

## 4. 분기 가지치기와 상태 포함 관계 (Branch Pruning & State Subsumption)

모든 가능한 실행 경로를 단순 무식(Brute-force)하게 탐색할 경우, $N$개의 조건문이 존재하면 탐색해야 하는 경로의 수가 $2^N$으로 지수적 폭발(State Explosion)을 일으킵니다. 커널 내에서 검증기가 수초 이상 실행되면 CPU 지연 및 DoS를 유발하므로, 리눅스 커널은 **분기 가지치기(Branch Pruning)**를 사용합니다.

### 4.1 상태 포함 관계 (`states_equal()` / `regsafe()`)
이미 안전하게 `EXIT`에 도달하여 검증이 완료된 경로상의 상태 $S_{	ext{old}}$가 존재할 때, 새로운 경로가 동일한 PC에서 도달한 상태 $S_{	ext{cur}}$이 $S_{	ext{old}}$보다 **더 엄격하거나 안전한 부분집합**이라면, $S_{	ext{cur}}$로부터 시작되는 이후의 실행 또한 필연적으로 안전함을 연역적으로 보장할 수 있습니다.

수학적으로:
$$S_{	ext{cur}} \sqsubseteq S_{	ext{old}} \iff orall r \in [0, 10], 	ext{regsafe}(r_{	ext{cur}}, r_{	ext{old}})$$
- **스칼라 포함 조건**:
  $$[	ext{umin}_{	ext{cur}}, 	ext{umax}_{	ext{cur}}] \subseteq [	ext{umin}_{	ext{old}}, 	ext{umax}_{	ext{old}}]$$
- **패킷 포인터 포함 조건**:
  $$	ext{off}_{	ext{cur}} == 	ext{off}_{	ext{old}} \land 	ext{pkt\_range}_{	ext{cur}} \ge 	ext{pkt\_range}_{	ext{old}}$$

이 조건이 성립하면 현재 분기의 하위 트리를 전혀 탐색하지 않고 즉시 가지치기(`pruned`)하여 수십만 개의 중복 경로를 $O(V + E)$ 수준으로 단축합니다.
