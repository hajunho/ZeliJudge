# Theory #430: 리눅스 커널 mm/workingset.c 페이지 캐시 섀도우 엔트리와 리폴트 거리(Refault Distance) 아키텍처

## 1. 개요 및 배경 (Historical Context & Problem Definition)

### 1.1 전통적 LRU의 한계와 2Q / Dual-List LRU
운영체제의 가상 메모리 관리(Virtual Memory Management) 및 페이지 캐시(Page Cache)는 디스크 I/O 병목을 완화하는 핵심 장치입니다. 초기의 순수 단일 LRU(Least Recently Used) 큐는 대용량 파일의 1회성 순차 스캔(`streaming I/O`)이 발생할 경우, 기존에 자주 사용되던 워킹셋 페이지 전체를 디스크로 몰아내는 **캐시 오염(Cache Pollution)** 문제를 겪었습니다.

이를 해결하기 위해 커널은 2Q 알고리즘을 변형한 **Dual-List LRU(Active / Inactive Lists)**를 도입했습니다:
- 신규 할당된 페이지는 먼저 **Inactive 리스트**의 최상단(MRU)에 위치합니다.
- 짧은 시간 내에 다시 참조(2nd Chance)되지 않은 페이지는 Inactive 리스트의 최하단(LRU)으로 밀려나 퇴출(Evict) 대상이 됩니다.
- 두 번째 참조가 발생한 페이지만 **Active 리스트**로 승격(Promote)됩니다.
- 메모리 압박이 심해지면 커널 백그라운드 스레드(`kswapd`)가 Active 리스트의 페이지를 다시 Inactive 리스트로 강등(Demote)시킵니다.

### 1.2 "조기 퇴출(Premature Eviction)과 스래싱의 저주"
그러나 Active 리스트조차 메모리 압박으로 인해 강등되어 결국 퇴출된 직후, 애플리케이션 루프가 해당 페이지를 다시 필요로 하는 상황이 발생합니다.
전통적인 Dual-List 모델에서는 이전에 Active였던 페이지라는 사실을 기억하지 못하므로, 다시 적재될 때 무조건 **Inactive 리스트**로 보내버립니다.
그 결과:
1. 페이지가 Inactive로 들어오자마자 메모리 압박으로 인해 즉각 다시 퇴출당합니다.
2. 애플리케이션은 매 반복 주기마다 동일한 페이지에 대해 반복적으로 디스크 읽기(Major Page Fault)를 유발합니다.
3. 시스템은 CPU 연산 대신 I/O 대기(D-state, Disk Sleep)에 100% 갇히는 **스래싱(Thrashing)** 현상에 빠지게 됩니다.

---

## 2. mm/workingset.c: 섀도우 엔트리(Shadow Entry)의 혁신

리눅스 커널 3.14에서 요하네스 바이너(Johannes Weiner)는 논문 *"Workingset: Page cache sizing based on refault distance"*의 이론을 구현한 `mm/workingset.c`를 도입했습니다.

### 2.1 섀도우 엔트리의 구조와 XArray 패킹
페이지가 메모리 회수기에 의해 해제될 때, 파일의 페이지 테이블 역할을 하는 XArray(기존 Radix Tree)에서 해당 인덱스의 포인터를 `NULL`로 지우지 않습니다. 대신 **특수 비트(Value Entry Bit)**가 켜진 64비트 정수 형태의 **섀도우 엔트리(Shadow Entry)**를 슬롯에 보관합니다:

```
+------------------+-----------------+--------------------+---+
| memcg_id (16bit) | pgdat_id (8bit) | eviction_ts (38bit)|0b1|
+------------------+-----------------+--------------------+---+
```
- `pack_shadow(memcg, pgdat, eviction)`: 노드와 cgroup 정보 및 퇴출 당시의 전역 퇴출 시퀀스 번호를 결합하여 포인터 형태로 패킹.
- `unpack_shadow(shadow, &memcg, &pgdat, &workingset)`: 다시 페이지 폴트가 일어났을 때 퇴출 시퀀스를 역산.

이 구조는 추가적인 물리 메모리 페이지(`struct page`)를 전혀 소모하지 않고, 기존 XArray의 비어있는 슬롯을 재활용하므로 공간 오버헤드가 극히 적습니다.

---

## 3. 리폴트 거리(Refault Distance)의 수학적 증명

### 3.1 워킹셋 크기와 퇴출 거리의 관계
이상적인 LRU 캐시 크기가 $M$일 때, 어떤 페이지 $p$가 캐시에서 쫓겨난 후 다시 참조되는 데 걸린 캐시 누적 퇴출 수를 $R$이라 합시다.
- 만약 $R \le M$이라면, 캐시 크기가 $M + R$ 또는 약간 더 컸다면 이 페이지는 애초에 캐시에서 쫓겨나지 않았을 것입니다.
- 현대 리눅스 시스템에서 Active 리스트의 크기 $N_{\text{active}}$는 바로 **현재 보호받고 있는 핵심 워킹셋의 용량**을 나타냅니다.

따라서 어떤 페이지 $p$가 퇴출된 시점 $E_{\text{evict}}$와 다시 요구된 시점 $E_{\text{current}}$ 사이의 거리:
$$\Delta_E = E_{\text{current}} - E_{\text{evict}}$$
이 값이 현재 시스템의 $N_{\text{active}}$보다 작거나 같다면:
$$\Delta_E \le N_{\text{active}}$$
**"이 페이지는 불과 활성 워킹셋 크기만큼의 퇴출이 일어나는 동안 다시 요구되었다."** 즉, **"이 페이지는 본질적으로 현재 활성 워킹셋(Active Working Set)의 구성원이었으나 메모리 압박으로 인해 억울하게 조기 퇴출당한 것"**임이 수학적으로 입증됩니다!

### 3.2 동작 분기
1. **$\Delta_E \le N_{\text{active}}$ (Working Set Refault)**:
   - 커널은 즉각 `SetPageActive(page)`를 호출하여 Inactive 단계를 건너뛰고 **Active LRU 리스트**로 다이렉트 승격합니다.
   - `workingset_activate` 카운터를 증가시킵니다.
   - 다음 번 메모리 회수에서 쉽게 희생되지 않도록 면역력을 부여합니다.
2. **$\Delta_E > N_{\text{active}}$ (Cold Page Refault)**:
   - 활성 워킹셋 주기보다 훨씬 이전에 퇴출되었으므로 일반적인 콜드 데이터로 간주합니다.
   - **Inactive LRU 리스트**로 삽입하여 2차 참조 기회를 다시 거치도록 합니다.

---

## 4. 섀도우 노드 축출과 메모리 누수 방지 (Shadow Nodes Shrinker)

파일이 삭제되지 않는 한 XArray에 남겨진 섀도우 엔트리는 영구히 남을 수 있습니다. 수백만 개의 파일이 접근되고 퇴출되면 섀도우 엔트리를 보관하는 XArray 노드 자체가 커널 슬랩 메모리(`radix_tree_node` / `xa_node`)를 수십 기가바이트씩 갉아먹는 메모리 누수가 발생할 수 있습니다.

이를 방어하기 위해 커널은 **Shadow Shrinker (`workingset_nodes`)**를 구동합니다:
- 현재 시스템의 총 파일 페이지 수 $N_{\text{active}} + N_{\text{inactive}}$에 여유 마진 $M_{\text{slack}}$을 더한 유효 임계 거리 $T_{\text{prune}}$를 설정합니다.
- 거리가 $T_{\text{prune}}$을 초과한 섀도우 엔트리는 더 이상 미래에 활성 워킹셋으로 복귀할 가능성이 0%에 수렴하므로, XArray에서 즉각 슬롯을 비우고 완전히 빈 XArray 노드를 OS 버디 할당자로 반환합니다.

---

## 5. cgroup v2 메모리 컨트롤러와의 유기적 결합

`CONFIG_MEMCG` 환경에서 워킹셋 메커니즘은 컨테이너별로 독립 격리됩니다:
- 각 cgroup의 `lruvec` 단위로 `eviction_counter`와 Active/Inactive 비율이 독립 추적됩니다.
- 한 컨테이너 내부에서 `workingset_refault`가 급증하면서 `workingset_activate` 비율이 임계치를 초과하면, 이는 해당 컨테이너의 `memory.max` 또는 `memory.high`가 실제 애플리케이션의 워킹셋보다 작게 책정되었음을 나타내는 결정적 텔레메트리가 됩니다.
- 쿠버네티스 VPA(Vertical Pod Autoscaler)나 커널 PSI(Pressure Stall Information)는 이 지표를 바탕으로 컨테이너 메모리를 동적으로 확장(`EXPAND_CGROUP_MEMORY`)하는 판단 근거로 활용합니다.
