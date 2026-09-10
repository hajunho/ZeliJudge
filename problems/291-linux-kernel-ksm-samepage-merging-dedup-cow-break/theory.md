# 리눅스 커널 메모리 가상화 백서: KSM(Kernel Samepage Merging, `mm/ksm.c`), Stable/Unstable Tree 아키텍처 및 CoW Break 쓰레싱 방어

## 1. 하이퍼바이저와 컨테이너 환경의 메모리 중복 문제

현대 클라우드 데이터센터 환경에서 단일 호스트 노드는 수십 대의 가상머신(QEMU/KVM)이나 수백 개의 컨테이너를 집적합니다. 이때 각 인스턴스는 동일한 리눅스 배포판(예: Ubuntu 22.04 LTS), 동일한 시스템 라이브러리(`glibc`, `libcrypto`, `libssl`), 파이썬/자바 런타임, 읽기 전용 공유 객체를 중복 로드합니다.

```text
[VM 1 (Ubuntu)]     [VM 2 (Ubuntu)]     [VM 3 (Ubuntu)]
  libc.so (4MB)       libc.so (4MB)       libc.so (4MB)
       │                   │                   │
       ▼                   ▼                   ▼
  [물리 메모리 1]       [물리 메모리 2]       [물리 메모리 3]   <-- 12MB 물리 메모리 낭비!
```

이러한 메모리 낭비를 제거하기 위해 리눅스 커널 2.6.32에 도입된 기술이 바로 **KSM (Kernel Samepage Merging)**입니다.

---

## 2. 리눅스 커널 KSM의 내부 동작 원리 (`mm/ksm.c`)

KSM은 무차별적인 전체 메모리 스캔 대신, 애플리케이션이나 가상화 런타임(KVM/QEMU)이 `madvise(addr, length, MADV_MERGEABLE)` 시스템 콜을 호출하여 지정한 익명 메모리 영역(Anonymous Memory)만을 대상으로 작동합니다.

### 2대 핵심 트리 구조
KSM은 동일성 검사의 시간 복잡도를 $O(N^2)$에서 $O(\log N)$으로 낮추기 위해 두 개의 레드-블랙 트리(RB-Tree)를 운용합니다:

```text
                                [새로운 스캔 후보 페이지 P]
                                              │
                                              ▼
                             ┌─────────────────────────────────┐
                             │    1단계: Stable Tree 탐색      │
                             │  (이미 병합된 쓰기 금지 페이지) │
                             └─────────────────────────────────┘
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                 일치(Match)                                         불일치(Miss)
                    │                                                   │
                    ▼                                                   ▼
       ┌────────────────────────┐                          ┌────────────────────────┐
       │ 기존 KSM 페이지 공유   │                          │   2단계: Unstable Tree │
       │ - PTE를 KSM으로 갱신   │                          │         후보 탐색      │
       │ - 기존 페이지 해제     │                          └────────────────────────┘
       │ - pages_sharing 증가   │                                       │
       └────────────────────────┘                      ┌────────────────┴────────────────┐
                                                    일치(Match)                       불일치(Miss)
                                                       │                                 │
                                                       ▼                                 ▼
                                          ┌────────────────────────┐        ┌────────────────────────┐
                                          │ 새로운 KSM 페이지 생성 │        │ Unstable Tree에        │
                                          │ - Stable Tree로 승격   │        │ 새 후보 노드로 등록    │
                                          │ - 두 페이지 모두 CoW   │        │ (다음 패스 전 클리어)  │
                                          │ - pages_shared++       │        └────────────────────────┘
                                          └────────────────────────┘
```

1. **Stable Tree (안정 트리)**:
   - 이미 병합되어 쓰기 금지(`PTE_RDONLY` / CoW) 플래그가 설정된 페이지들입니다.
   - 키는 페이지 내용의 체크섬/해시이며, 내용이 임의로 변경되지 않으므로 트리의 정렬 불변성이 보장됩니다.
2. **Unstable Tree (불안정 트리)**:
   - 아직 병합되지 않은 단독 후보 페이지들입니다.
   - 페이지가 쓰기 금지 상태가 아니므로 프로세스가 임의로 내용을 수정할 수 있습니다. 만약 내용이 바뀌면 트리의 정렬 순서가 파괴되므로, **`ksmd`는 매 스캔 패스를 새로 시작할 때마다 Unstable Tree를 전면 삭제(`rb_destroy`)**하여 메모리 오염을 원천 차단합니다.

---

## 3. 실무 KSM 운영 재앙과 성능 병목

### 1) CoW Break 쓰레싱 (Copy-on-Write Break Thrashing)
* 가상머신이 KSM으로 병합된 페이지에 쓰기(`write`)를 수행하면 CPU는 즉시 **Write Protection Page Fault (`#PF`, `do_wp_page()`)**를 발생시킵니다.
* 커널은 새로운 물리 페이지를 할당받아 4KB 데이터를 복사하고, 페이지 테이블 엔트리를 쓰기 가능으로 복구합니다.
* 데이터베이스 버퍼 풀이나 가변 힙 등 쓰기 빈도가 높은 메모리를 KSM으로 묶으면:
  $$\text{스캔 및 병합} \longrightarrow \text{즉시 쓰기 발생(CoW Break)} \longrightarrow \text{페이지 복사} \longrightarrow \text{재병합...}$$
  이 악순환이 초당 수천 번 반복되면서 CPU는 100% 고갈되고 메모리 절감은 0이 되는 참극이 발생합니다.

### 2) NUMA 비대칭 지연과 TLB Shootdown
* `merge_across_nodes = 1`로 설정하면 Node 0의 물리 페이지로 Node 1의 가상머신 페이지들이 통합됩니다.
* 이로 인해 Node 1의 CPU 코어는 모든 메모리 읽기를 UPI/QPI 버스를 통해 원격 Node 0으로 전송해야 하므로 메모리 지연 시간이 2배 이상 폭증합니다.
* 또한 페이지 병합 및 해제 시 다른 CPU 소켓에 Inter-Processor Interrupt (IPI)를 발송하여 원격 TLB를 무효화하는 **TLB Shootdown 스톰**이 발생합니다.

---

## 4. 실무 커널 튜닝 가이드

```bash
# 1. 고성능 NUMA 서버에서는 노드 간 병합을 반드시 금지하여 로컬 지연 시간 보호
echo 0 > /sys/kernel/mm/ksm/merge_across_nodes

# 2. 과도한 rmap 역참조 체인(Reverse Mapping Walk) 방지를 위해 최대 공유 수 제한
echo 256 > /sys/kernel/mm/ksm/max_page_sharing

# 3. 읽기 전용 가상머신 밀집 호스트의 경우 스캔 주기 가속
echo 1000 > /sys/kernel/mm/ksm/pages_to_scan
echo 20 > /sys/kernel/mm/ksm/sleep_millisecs

# 4. 쓰기 집중형 데이터베이스 서버의 경우 CoW 쓰레싱 방지를 위해 KSM 비활성화
echo 0 > /sys/kernel/mm/ksm/run
```
