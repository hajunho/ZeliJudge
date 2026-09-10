# Theory #443: 리눅스 커널 가상화 및 초고속 I/O: drivers/vhost/net.c vhost-net 제로-카피 및 ubuf_info 비동기 완료 콜백 이론

## 1. 반가상화(Paravirtualization) 송신 병목과 메모리 복사 장벽

클라우드 데이터센터 환경에서 가상 머신(Guest VM)의 네트워킹 성능은 물리 호스트와 가상 머신 간의 I/O 가상화 효율에 직결됩니다.
전통적인 `vhost-net` 송신 파이프라인에서 게스트가 1500바이트 표준 패킷이나 9000바이트 점보 프레임을 전송할 때:
1. 게스트는 VirtIO 송신 링(`vring.avail`)에 게스트 물리 주소(GPA)를 기입하고 하이퍼콜 도어벨을 울립니다.
2. 호스트 커널의 `vhost_net` 커널 워커 스레드는 호스트 가상 주소(HVA)로 변환한 뒤 `copy_from_user()` 또는 `memcpy()`를 통해 호스트의 `sk_buff` 선형 버퍼로 데이터를 복제합니다.
3. **CPU 및 메모리 버스 포화**: 100Gbps 회선에서 초당 12.5GB의 데이터를 CPU가 직접 복사해야 하며, 이는 메모리 컨트롤러 대역폭을 고갈시키고 CPU L1/L2/L3 캐시 전체를 순식간에 밀어내어(Cache Thrashing) 호스트의 전체 VM 워크로드 성능을 30~50% 저하시킵니다.

---

## 2. vhost-net Zero-Copy TX와 비동기 ubuf_info 참조 카운팅

리눅스 커널의 **vhost-net 제로-카피(Zero-Copy TX)**는 메모리 복사를 원천적으로 생략하고 게스트의 메모리 페이지를 호스트 `sk_buff` 프래그먼트(`skb_shinfo(skb)->frags`)에 직접 핀(Pin) 고정합니다.

```
+-------------------------------------------------------------------+
|                        Guest Virtual Machine                      |
|                                                                   |
|   virtio-net driver submits packet (GPA 0x100000, len 1500)       |
+─────────────────────────────────┬─────────────────────────────────+
                                  │ vhost MMIO doorbell kick
                                  ▼
+-------------------------------------------------------------------+
|                        Host Kernel: vhost-net                     |
|                                                                   |
|   handle_tx_zerocopy():                                           |
|   1. Pin guest pages via get_user_pages_fast()                    |
|   2. Attach to host skb frags (Zero-Copy!)                        |
|   3. Allocate struct ubuf_info with refcount=1                    |
|   4. skb_shinfo(skb)->destructor_arg = ubuf                       |
|   5. Pass skb to Host NIC driver                                  |
+─────────────────────────────────┬─────────────────────────────────+
                                  │ PCIe DMA Transfer
                                  ▼
+-------------------------------------------------------------------+
|                        Physical NIC Hardware                      |
|                                                                   |
|   Reads memory via PCIe Bus Master DMA...                         |
|   DMA Complete Interrupt fired!                                   |
|   skb_release_data() -> invokes ubuf_info->callback()             |
+─────────────────────────────────┬─────────────────────────────────+
                                  │ vhost_zerocopy_callback()
                                  ▼
+-------------------------------------------------------------------+
|                        vhost-net Worker                           |
|                                                                   |
|   1. Decrement inflight_zcopy_count                               |
|   2. Put descriptor index into vring.used                         |
|   3. virtqueue_kick() notifies Guest: "Buffer safe to reclaim!"   |
+-------------------------------------------------------------------+
```

### (1) 비동기 수명주기(Lifecycle) 보호 딜레마
왜 단순 포인터 전달이 불가능한가?
- 만약 호스트가 게스트 메모리를 직접 가리킨 상태에서 게스트에게 "전송 완료"를 즉시 보고한다면, 게스트는 해당 메모리 버퍼를 즉각 다른 프로세스에 할당하거나 새로운 데이터로 덮어씁니다.
- 하지만 물리 NIC은 여전히 PCIe 버스를 통해 해당 주소의 구 메모리를 읽어 회선으로 송출하고 있을 수 있습니다 (Time-of-Check to Time-of-Use Race).
- 따라서 물리 NIC의 하드웨어 전송 인터럽트가 발생하여 `skb_release_data()`가 실행될 때까지 게스트 버퍼의 반환을 엄격히 동결해야 합니다.

### (2) `struct ubuf_info`의 원자적 콜백
`ubuf_info` 구조체는 커널 네트워킹 스택 전체를 통과하는 동안 복수의 드라이버나 프로토콜이 skb를 참조하더라도 참조 카운트(`refcnt`)가 0이 되는 최종 시점에 단 한 번만 `vhost_zerocopy_callback()`을 호출하여 안전성을 절대적으로 보장합니다.

---

## 3. 적응형 폴백(Adaptive Fallback)과 버퍼 고갈(Starvation) 방어

제로-카피가 항상 복사보다 유리한 것은 아닙니다:

### (1) 소형 패킷 임계치 (`zcopy_min_threshold`)
- 64바이트~512바이트 크기의 작은 패킷(TCP ACK, DNS 질의, ICMP 등)은 메모리 페이지 핀(`get_user_pages`)과 IOMMU 매핑, 콜백 할당에 소요되는 CPU 오버헤드가 단 512바이트를 복사하는 비용보다 훨씬 큽니다.
- 따라서 커널은 `len < zcopy_min_threshold`인 패킷을 즉각 동기식 복사 모드로 처리하고 used 링에 즉시 반환합니다.

### (2) 게스트 버퍼 고갈 방지 (`max_zcopy_inflight`)
- 호스트 NIC이 과부하 상태이거나 패킷 재전송으로 인해 DMA 완료가 지연되면 수많은 게스트 디스크립터가 호스트에 묶여 있게 됩니다.
- 게스트 VirtIO 송신 링(보통 256~1024 엔트리)의 모든 버퍼가 고갈되면 게스트 내부 네트워크 스택이 완전히 블록(TX Hang)됩니다.
- 이를 방어하기 위해 `inflight_zcopy_count >= max_zcopy_inflight`에 도달하면 신규 패킷을 즉각 복사 모드(`COPY_FALLBACK`)로 처리하여 used 링을 순환시킴으로써 무중단 고속 스트리밍을 유지합니다.
