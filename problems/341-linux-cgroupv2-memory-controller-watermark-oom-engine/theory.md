# 리눅스 커널 Cgroup v2 메모리 컨트롤러(memcg) 및 OOM 아키텍처 심층 이론

## 1. Cgroup v1의 설계 결함과 v2의 단일 통합 계층 (Unified Hierarchy)

리눅스 커널의 자원 관리 서브시스템인 cgroup(Control Groups)은 v1 시절 다음과 같은 치명적 결함을 겪었습니다:
- **서브시스템 간 계층 분열**: CPU, 메모리, 블록 I/O(blkio)가 서로 다른 독립 트리로 구성되어, 특정 프로세스가 메모리 cgroup에서는 그룹 A에 속하고 블록 I/O cgroup에서는 그룹 B에 속할 수 있었습니다. 이로 인해 메모리 쓰기 버퍼(Page Cache)가 디스크로 플러시될 때 I/O 스로틀링이 엉뚱한 그룹에 부과되는 문제가 발생했습니다.
- **cgroup v2의 해결책**: 모든 컨트롤러(cpu, memory, io, pids)가 오직 단 하나의 동일한 **통합 계층 구조(Unified Hierarchy)**를 따릅니다.

---

## 2. 4대 메모리 워터마크(Watermarks)와 비례 제어

cgroup v2는 단순한 `limit_in_bytes` 하나로 모든 것을 제어하던 v1을 탈피하여, 4계층 워터마크 모델을 도입했습니다:

### 2.1 `memory.min` (하드 보장)
- 쿠버네티스의 `requests` 개념을 커널 레벨에서 구현한 것입니다.
- 시스템에 아무리 극단적인 메모리 압박이 발생하더라도, `memory.min` 이하의 페이지는 LRU 리클레임 대상에서 완전히 제외되어 스왑(Swap)되거나 버려지지 않습니다.

### 2.2 `memory.low` (소프트 보호)
- 시스템 여유 메모리가 있는 한 보호되며, 다른 비보호 메모리가 모두 고갈되었을 때만 시스템 메모리 부족분에 비례하여 회수됩니다.

### 2.3 `memory.high` (비례 스로틀링)
- 과거 v1에서는 한계에 도달하면 즉시 프로세스가 OOM으로 사망하거나 CPU 100%를 소모하는 직접 회수 스핀에 빠졌습니다.
- v2의 `memory.high`는 상한선에 도달하기 전 프로세스에게 **벌칙 수면 지연(Penalty Sleep Delay)**을 부과합니다:
  $$\text{delay} = \min\left(1000\text{ms}, \frac{\text{excess} \times 100}{\text{high}}\right)$$
- 할당 빈도가 높은 프로세스를 느리게 만들어 메모리 증가 속도를 억제하고, 백그라운드 워커(`kswapd`, `memcg_reclaim`)가 메모리를 정리할 시간을 벌어줍니다.

### 2.4 `memory.max` (하드 리밋)
- 어떤 프로세스도 이 선을 넘을 수 없습니다. 초과 시 즉시 동기식 직접 회수(Direct Reclaim)가 수행되며, 실패 시 OOM 킬러가 즉시 호출됩니다.

---

## 3. 원자적 그룹 킬 (`memory.oom.group`)과 컨테이너 무결성

cgroup v1의 OOM 킬러는 컨테이너 내부의 프로세스 중 단 하나(보통 가장 메모리를 많이 먹는 워커)만 골라 죽였습니다:
- **문제점**: 웹 서버 마스터 프로세스나 모니터링 데몬은 살아남고 핵심 워커만 죽어버려, 컨테이너가 정상적으로 재시작되지도 못하고 요청을 처리하지도 못하는 **좀비 상태(Corrupted Zombie State)**에 빠졌습니다.
- **cgroup v2 `memory.oom.group`**: cgroup 내의 어떤 프로세스 하나라도 OOM 조건을 유발하면, 커널은 해당 cgroup 전체에 `SIGKILL`을 브로드캐스트하여 **모든 프로세스를 원자적으로 동시 사살**합니다. 이를 통해 쿠버네티스 kubelet이 파드의 사망을 즉각 감지하고 깨끗하게 재시작할 수 있습니다.

---

## 4. OOM Badness 점수 산정 알고리즘

커널이 희생자(Victim)를 선정할 때 사용하는 점수는 다음과 같습니다:
$$\text{points} = \text{RSS} + \text{swap} + (\text{oom\_score\_adj} \times 1000)$$
- `oom_score_adj`: 사용자가 `/proc/[pid]/oom_score_adj`에 기록하는 $[-1000, +1000]$ 범위의 편향치.
- `-1000`으로 설정된 프로세스는 절대 OOM으로 종료되지 않습니다(OOM-disable).
- 쿠버네티스는 QoS 클래스(Guaranteed, Burstable, BestEffort)에 따라 `oom_score_adj`를 차등 부여하여, 시스템 압박 시 BestEffort 파드를 가장 먼저 희생시킵니다.
