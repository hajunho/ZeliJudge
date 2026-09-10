# Linux Kernel Multi-Gen LRU (MGLRU) 심층 이론 및 수리적 분석

## 1. 리눅스 가상 메모리 관리와 LRU의 역사적 한계

전통적인 UNIX 및 초기 Linux 커널(v2.4 ~ v5.x)의 메모리 관리 서브시스템(`mm/vmscan.c`)은 **2-List LRU (Active and Inactive Lists)** 아키텍처에 기반을 두었습니다.

### 1.1 2-List LRU의 구조
- **Active List**: 활성 참조 중인 페이지들.
- **Inactive List**: 참조되지 않아 회수 대상이 되는 페이지들.
- 시스템에 메모리 압박(Memory Pressure)이 발생하면 `kswapd` 또는 직접 회수(Direct Reclaim) 루틴이 Inactive List의 꼬리에서 페이지를 검사하여, 페이지 테이블의 Accessed 비트가 설정되어 있지 않으면 디스크로 축출(Evict)했습니다.

### 1.2 2-List LRU의 3대 결함
1. **스핀락 경합 (`lru_lock` Contention)**:
   - 모든 CPU 코어가 단일 메모리 노드/존(Zone)의 `lru_lock`을 획득해야 페이지를 리스트 간에 이동시킬 수 있었습니다. 수백 코어의 현대 서버 환경에서 `lru_lock` 병목은 심각한 CPU 사이클 낭비를 초래했습니다.
2. **단조로운 2계위 분류로 인한 정보 손실**:
   - 페이지의 생애 주기 동안 단지 활성/비활성이라는 1비트 수준의 이진 상태만 추적하므로, "언제", "얼마나 자주" 접근되었는지를 정밀하게 알 수 없었습니다.
3. **순차 I/O에 의한 캐시 오염 (Scan Pollution / Thrashing)**:
   - 1회성 대용량 백업이나 순차 파일 읽기가 발생하면 엄청난 양의 새로운 페이지가 유입되어 기존의 중요한 워킹셋 페이지들을 Inactive List로 밀어내고 디스크로 쫓아내는 비극이 빈번하게 일어났습니다.

---

## 2. Multi-Gen LRU (MGLRU) 아키텍처

Linux 6.1에 머지된 MGLRU는 페이지들을 다수의 **세대(Generations)**로 추적하고, 각 세대 내부를 4단계 **접근 빈도 티어(Access Tiers)**로 분할하여 관리합니다.

### 2.1 세대(Generation) 링 버퍼
MGLRU는 단조 증가하는 64비트 정수 시퀀스 번호를 사용합니다:
- `max_seq`: 가장 최근에 할당되거나 활성화된 페이지들이 배치되는 최신 세대.
- `min_seq`: 가장 오래되어 회수 대상이 되는 최소 세대.
- `MAX_NR_GENS`: 유지 가능한 최대 세대 수 (기본 $4$ 또는 $8$).
- 세대 간격 Invariant:
  $$\text{spread} = \max\_seq - \min\_seq + 1 \le \text{MAX\_NR\_GENS}$$

### 2.2 4-Tier 접근 빈도 분류
각 세대 내에서 페이지는 참조 빈도에 따라 4개의 티어로 나뉩니다:
$$\text{Tier} \in \{0, 1, 2, 3\}$$
- **Tier 0**: 마지막 세대 노화 이후 참조되지 않음 ($0$ Accesses). 즉시 회수 1순위.
- **Tier 1**: $1$회 참조.
- **Tier 2**: $2$회 참조.
- **Tier 3**: $3$회 이상 집중 참조된 핫 워킹셋 ($3+$ Accesses).

### 2.3 워킹셋 보호 승격 (Working Set Protection & Promotion)
회수 스캐너가 `min_seq` 세대를 검사할 때:
- $\text{Tier} > 0$ 이거나 $\text{Accessed} == \text{True}$ 인 페이지는 버려지지 않습니다.
- 커널은 이 페이지를 최신 세대 $\max\_seq$로 **승격(Promotion)**시키고, $\text{Tier}$를 $1$ 감등하여 과도한 승격을 방지합니다:
  $$\text{gen}' = \max\_seq, \quad \text{tier}' = \max(0, \text{tier} - 1), \quad \text{accessed}' = \text{False}$$
- 오직 $\text{Tier} == 0$ 이고 $\text{Accessed} == \text{False}$ 인 콜드 페이지만이 안전하게 회수됩니다.

이 메커니즘을 통해 순차 I/O로 유입된 페이지들($\text{Tier} 0$)은 즉시 버려지고, 실제 애플리케이션의 핵심 워킹셋($\text{Tier} 1 \sim 3$)은 영구히 보호됩니다.

---

## 3. 메모리 쓰레싱(Thrashing)과 리폴트(Refault) 분석

### 3.1 리폴트 거리(Refault Distance) 이론
페이지 $P$가 시간 $t_{evict}$에 메모리에서 쫓겨난 후, 짧은 시간 간격 $t_{refault}$ 내에 다시 접근되어 페이지 폴트를 발생시키는 현상을 **리폴트(Refault)**라고 합니다.
$$\Delta t = t_{refault} - t_{evict}$$
만약 회수된 페이지 중 상당수가 즉시 리폴트된다면, 현재 메모리가 애플리케이션의 작업 집합(Working Set Size, WSS)을 수용하기에 부족하다는 명백한 증거이며, 시스템은 **쓰레싱(Thrashing)** 상태에 빠집니다.

### 3.2 쓰레싱 판정 메트릭
$$\text{Refault Ratio} = \frac{\text{Refault Count}}{\max(1, \text{Total Evictions})}$$
$$\text{Thrashing Flag} = (\text{Refault Count} \ge 2) \land (\text{Refault Ratio} \ge 0.25)$$

MGLRU는 이와 같은 통계를 통해 `vm.swappiness` 및 세대 노화 주기(`aging_interval`)를 동적으로 자동 조율(Autotuning)합니다.
