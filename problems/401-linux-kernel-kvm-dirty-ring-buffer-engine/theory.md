# 401: 리눅스 커널 가상화 — KVM Dirty Ring Buffer 아키텍처와 대규모 VM 무중단 라이브 마이그레이션 이론

## 1. 가상 머신 실시간 마이그레이션의 메모리 추적 병목

실시간 마이그레이션(Live Migration) 중 게스트 가상 머신의 중단 시간(Downtime)을 수십 밀리초 이하로 억제하기 위해서는, 마이그레이션 반복 주기(Pre-copy Round) 동안 vCPU가 수정하는 메모리 페이지를 신속하고 오버헤드 없이 식별해야 합니다.

### 1.1 전통적 전역 비트맵 방식 (`KVM_GET_DIRTY_LOG`)의 한계
- 1990년대부터 사용된 비트맵 방식은 메모리 슬롯의 모든 4KB 페이지에 대해 1비트를 할당합니다.
- **$O(N)$ 복사 비용**: 2TB 메모리를 장착한 SAP HANA나 거대 데이터베이스 VM의 경우, 비트맵 크기만 64MB에 달합니다. 100ms마다 비트맵을 커널에서 유저 공간(QEMU)으로 복사하면 초당 수백 메가바이트의 메모리 대역폭이 낭비됩니다.
- **전역 쓰기 보호(Write-Protect) 병목**: 비트맵을 초기화할 때 커널은 2단계 페이지 테이블(EPT/NPT)의 모든 엔트리를 다시 쓰기 보호로 전환해야 하므로, 모든 vCPU가 EPT 락 경합에 묶여 정지되는 Stop-the-World 지연이 발생합니다.

---

## 2. KVM Dirty Ring Buffer (`virt/kvm/dirty_ring.c`)의 혁신

리눅스 커널 5.11에서 Peter Xu 등에 의해 머지된 **Dirty Ring Buffer**는 메모리 추적 패러다임을 **전역 공간 스캔($O(N)$)** 에서 **vCPU별 이벤트 로깅($O(	ext{더티 페이지 수})$)** 으로 전환했습니다.

### 2.1 분산형 원형 링 버퍼 (Distributed Circular Ring Buffers)
- 각 vCPU는 유저 공간과 커널 공간이 공유(`mmap`)하는 고정 크기(기본 4096 엔트리)의 `struct kvm_dirty_gfn` 링 버퍼를 보유합니다.
- vCPU가 페이지에 쓰기를 가할 때 하드웨어 PML(Page Modification Logging) 또는 가상화 예외 핸들러가 해당 GFN을 vCPU 전용 링의 `tail`에 $O(1)$로 즉시 기록합니다.
- vCPU 간에 락을 공유하지 않으므로 코어 수가 수백 개로 증가해도 완벽한 선형 확장성(Linear Scalability)을 유지합니다.

### 2.2 2단계 커밋(Two-Phase Commit)과 흐름 제어(Flow Control)
1. **생산 (vCPU)**:
   vCPU는 `tail`을 전진시키며 GFN을 푸시합니다. $	ext{tail} - 	ext{head} == 	ext{ring\_size}$가 되면 링이 포화되어 vCPU는 하이퍼바이저로 탈출(`KVM_EXIT_DIRTY_RING_FULL`)합니다.
2. **수집 (Reap)**:
   유저 공간 마이그레이터는 `head`부터 `tail`까지 GFN을 읽어 네트워크로 송신하고 슬롯을 `RESET` 상태로 마킹합니다.
3. **재설정 (Reset)**:
   유저 공간이 `ioctl(KVM_RESET_DIRTY_RINGS)`을 호출하면 커널은 `RESET` 마킹된 엔트리를 확인하고 EPT 쓰기 권한을 원자적으로 재설정한 뒤 `head`를 전진시켜 vCPU를 언락합니다.

### 2.3 지능적 vCPU 쓰로틀링 (Self-Throttling)
네트워크 전송 속도보다 메모리를 훨씬 빠르게 수정하는 쓰기 집약적(Write-Heavy) vCPU가 존재할 때, 전역 비트맵 방식에서는 VM 전체가 멈췄습니다. 그러나 Dirty Ring 방식에서는 해당 vCPU의 링만 지속적으로 가득 차 탈출하므로, 다른 정상 vCPU의 동작을 전혀 방해하지 않고 공격적 vCPU만 정밀하게 쓰로틀링됩니다.

---

## 3. 결론

KVM Dirty Ring Buffer는 테라바이트급 대규모 엔터프라이즈 가상 머신의 실시간 마이그레이션 오버헤드를 90% 이상 격감시킨 최신 클라우드 가상화 기술의 정수입니다.
