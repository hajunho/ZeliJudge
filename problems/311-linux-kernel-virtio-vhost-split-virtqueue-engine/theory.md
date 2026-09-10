# 리눅스 커널 VirtIO & vhost-net 스플릿 버트큐 아키텍처 백서 (Theoretical Background)

## 1. 개요: 가상화 I/O와 VM-Exit의 병목

하드웨어 가상화(Intel VT-x, AMD-V)에서 가상 머신(게스트)이 가상 I/O 디바이스와 통신하기 위해 과거에는 순수 소프트웨어 에뮬레이션(QEMU가 e1000 NIC의 PCI 레지스터를 하나씩 흉내 내는 방식)을 사용했습니다.

그러나 이 방식은 패킷 1개를 보낼 때마다 다음 단계를 거쳐야 했습니다:
1. 게스트가 특정 I/O 포트나 메모리 매핑 I/O(MMIO)에 쓰기 수행
2. CPU 하드웨어가 이를 트랩하여 **VM-Exit** 발생
3. 호스트 커널(KVM)로 제어권 전환 후 유저스페이스 QEMU 프로세스로 시그널 전달
4. QEMU가 에뮬레이션 수행 후 다시 **VM-Entry**로 게스트 복귀

VM-Exit 1회당 약 1,500 ~ 3,000 CPU 클럭 사이클이 소모되므로, 초당 수십만 패킷을 처리할 때 CPU의 90% 이상이 컨텍스트 스위칭 오버헤드로 낭비되는 참사가 발생했습니다.

---

## 2. VirtIO 표준과 스플릿 버트큐 (Split Virtqueue) 구조

OASIS VirtIO 표준은 가상 장치 전용의 초경량 파라버추얼라이제이션(Paravirtualization) 인터페이스를 정의합니다. 그 핵심이 바로 락(Lock) 없이 단방향 메모리 배리어만으로 동기화되는 **스플릿 버트큐(Split Virtqueue)**입니다.

```
       [ 게스트 OS 드라이버 ]                  [ 호스트 하이퍼바이저 / vhost ]
                 |                                          |
                 | === Available Ring (게스트가 작성) ====> |
                 |                                          |
                 | <=== Used Ring (호스트가 작성) ========= |
                 |                                          |
                 +---------- Descriptor Table[N] -----------+
```

1. **디스크립터 테이블 (`vring_desc`)**:
   ```c
   struct vring_desc {
       __virtio64 addr;   /* 게스트 물리 메모리 주소 */
       __virtio32 len;    /* 버퍼 길이 */
       __virtio16 flags;  /* VRING_DESC_F_NEXT, VRING_DESC_F_WRITE */
       __virtio16 next;   /* 체인의 다음 디스크립터 인덱스 */
   };
   ```
2. **사용 가능 링 (`vring_avail`)**:
   - 게스트가 완성된 디스크립터 체인의 헤드 인덱스를 배열에 적고 `idx`를 증가시킵니다.
   - 단일 쓰기자(Single-Writer: 게스트) 구조이므로 별도의 락이 필요 없습니다.
3. **사용 완료 링 (`vring_used`)**:
   - 호스트가 데이터 전송 또는 수신을 마친 뒤, 헤드 ID와 전송 길이를 적고 `idx`를 증가시킵니다.
   - 단일 쓰기자(Single-Writer: 호스트) 구조입니다.

---

## 3. 알림 억제(Notification Suppression)와 인터럽트 완화

가상화에서 I/O 지연과 CPU 점유율을 결정짓는 핵심은 "언제 상대방을 깨울 것인가?"입니다:

1. **게스트 $	o$ 호스트: Kicking 억제 (`VRING_USED_F_NO_NOTIFY`)**:
   - 호스트(vhost-net)가 이미 작업 루프를 돌며 패킷을 맹렬히 처리하고 있는 중이라면, 게스트가 새 버퍼를 넣을 때마다 `ioeventfd`로 호스트를 킥(Kick)할 이유가 없습니다.
   - 호스트는 `used_flags`에 `VRING_USED_F_NO_NOTIFY`를 설정하여 게스트의 VM-Exit 킥을 차단하고 공유 링 폴링으로 처리합니다.
2. **호스트 $	o$ 게스트: Interrupt 억제 (`VRING_AVAIL_F_NO_INTERRUPT`)**:
   - 게스트 OS가 NAPI 폴링 루틴을 돌고 있거나 고속 패킷 수신 중일 때, 호스트가 매 패킷마다 vCPU에 가상 인터럽트(irqfd)를 걸면 인터럽트 폭풍이 발생합니다.
   - 게스트는 `avail_flags`에 `VRING_AVAIL_F_NO_INTERRUPT`를 설정하여 불필요한 vCPU 인터럽트를 잠재웁니다.

---

## 4. vhost-net과 제로 카피 데이터 패스

QEMU 기반 VirtIO 에뮬레이션은 유저스페이스를 거쳐야 하므로 여전히 컨텍스트 스위칭이 존재합니다.
리눅스 커널의 **`vhost-net` (`drivers/vhost/net.c`)**은 이 한계를 뛰어넘어, 공유 링 버퍼를 호스트 커널 스레드가 직접 감시하고 커널 네트워크 스택(TAP 디바이스, 물리 NIC 드라이버)과 직접 바인딩합니다.

이로 인해 게스트의 메모리가 커널 모드에서 직접 매핑되어, 유저스페이스 복사 없는 완벽한 **Zero-Copy Virtqueue** 파이프라인이 완성됩니다.
