# 문제 428 심층 이론: 리눅스 커널 XDP 메타데이터(data_meta)와 하드웨어 체크섬 오프로드 최적화

---

## 1. 100GbE+ 환경에서 소프트웨어 체크섬의 CPU 사이클 비용

인터넷 프로토콜(IPv4 헤더 체크섬, TCP/UDP 페이로드 체크섬)은 16비트 원스 보수 덧셈(1's Complement Sum)으로 정의되어 있습니다.
100GbE 네트워크 링크에서 1500바이트 표준 MTU 패킷이 풀 라인 레이트로 수신될 경우 초당 약 810만 패킷(Mpps)이 도착하며, 64바이트 최소 패킷의 경우 초당 **1억 4,880만 패킷(148.8 Mpps)**에 달합니다.

### 1.1 소프트웨어 체크섬의 수학적 계산 비용
패킷 크기를 $L$ 바이트라 할 때, 64비트 레지스터 단위로 캐리(Carry)를 접으며 체크섬을 계산하는 데 필요한 최소 CPU 사이클은 다음과 같습니다:
$$\Delta T_{\text{csum}} = N_{\text{pkts}} \times \left( \left\lceil \frac{L}{8} \right\rceil \times \tau_{\text{add}} + \tau_{\text{fold}} \right)$$
- 1500바이트 패킷 하나당 약 200~300 사이클이 소모됩니다.
- 초당 810만 패킷을 소프트웨어로 체크섬 검증할 경우, **초당 약 20억~24억 CPU 사이클**이 오직 체크섬 계산에만 증발합니다 (서버 CPU 코어 8~12개가 완전히 포화되는 수준).
- 반면 최신 NIC 하드웨어는 파이프라인 수신 단계에서 0-CPU-사이클로 체크섬 검증을 완료합니다.

---

## 2. 레거시 XDP의 한계: 하드웨어 메타데이터 증발 문제

XDP(eXpress Data Path)는 초고속 패킷 처리를 위해 설계되었으나, 초기에는 `struct xdp_buff` 구조체가 단지 세 개의 포인터만 가졌습니다:
- `data`: 패킷 페이로드 시작
- `data_end`: 패킷 페이로드 끝
- `data_hard_start`: 드라이버 페이지 프레임 시작

### 2.1 메타데이터 손실 메커니즘
하드웨어 NIC이 패킷을 수신하면 링 디스크립터(Descriptor)에 "체크섬 검증 완료(CSUM_OK)", "RSS 5-튜플 해시", "PTP 수신 타임스탬프" 플래그를 실어 보냅니다.
하지만 XDP 드라이버는 XDP 프로그램을 실행할 때 이 하드웨어 디스크립터를 버리고 순수 패킷 버퍼(`xdp_buff`)만 BPF VM에 넘겼습니다.
XDP 프로그램이 패킷을 파싱한 후 커널 TCP 스택으로 넘기기 위해 `XDP_PASS`를 반환하면, 스택은 하드웨어가 체크섬을 검증했는지 알 수 없으므로 `skb->ip_summed = CHECKSUM_NONE`으로 초기화하고 전면적인 소프트웨어 재계산을 강제했습니다.

---

## 3. XDP 메타데이터(`data_meta`)와 `bpf_xdp_adjust_meta`

리눅스 커널은 이를 해결하기 위해 `xdp_buff`에 네 번째 포인터인 **`data_meta`**를 추가했습니다.

```
[xdp_buff Layout]
struct xdp_buff {
    void *data;             /* 패킷 L2 헤더 시작 */
    void *data_end;         /* 패킷 끝 */
    void *data_meta;        /* 메타데이터 시작 (기본적으로 data와 동일) */
    void *data_hard_start;  /* 버퍼 물리 시작점 (헤드룸 포함) */
};
```

### 3.1 헤드룸 확장 동작 원리
1. `bpf_xdp_adjust_meta(ctx, -offset)`를 호출하면, 커널은 `data_meta` 포인터를 `data` 앞쪽의 헤드룸 공간으로 `offset` 바이트만큼 전진(메모리 주소 감소)시킵니다.
2. XDP 프로그램은 `data_meta`와 `data` 사이의 공간에 구조체를 직접 정의하여 데이터를 쓸 수 있습니다:
   ```c
   struct my_meta {
       __u32 rx_hash;
       __u16 csum_status;
       __u16 vlan_tag;
   };
   ```

---

## 4. 리눅스 6.3+ XDP Hints kfuncs와 제로-오버헤드 스택 패스

리눅스 6.3부터 BPF BTF(BPF Type Format) 기반의 드라이버 kfunc 인터페이스가 공식 도입되었습니다:
- `bpf_xdp_metadata_rx_hash(ctx, &hash)`
- `bpf_xdp_metadata_rx_timestamp(ctx, &timestamp)`
- `bpf_xdp_metadata_rx_vlan_tag(ctx, &vlan)`
- `bpf_xdp_metadata_rx_csum(ctx, &csum)`

### 4.1 `XDP_PASS` 시 SKB 변환 파이프라인
드라이버의 `napi_gro_receive()` 또는 `build_skb()` 루틴은 `XDP_PASS` 반환 후 다음을 수행합니다:
1. `xdp_buff`의 `data_meta < data` 여부를 검사합니다.
2. 메타데이터에 유효한 하드웨어 체크섬 플래그가 기록되어 있다면, `skb->ip_summed = CHECKSUM_UNNECESSARY` 플래그를 설정합니다.
3. 리눅스 커널 TCP/IP 스택은 `ip_summed == CHECKSUM_UNNECESSARY`를 확인하고 **소프트웨어 체크섬 검증 루틴을 통째로 스킵(Skip)**합니다.
4. RSS 플로우 해시가 `skb->hash`에 복사되어 소프트웨어 플로우 해시 계산(Jenkins Hash / Flow Dissector) 없이 하드웨어 해시 그대로 멀티코어 소켓 큐로 다이렉트 디스패치됩니다.

---

## 5. 결론

XDP 메타데이터와 XDP 힌트는 고성능 패킷 프로세싱에서 "eBPF의 프로그래머블한 유연성"과 "하드웨어 ASIC의 초고속 오프로드 성능"을 완벽하게 결합한 현대 리눅스 네트워킹의 최고봉입니다.
Cilium, Katran, Cloudflare 등 글로벌 스케일 인프라에서 수천만 패킷을 처리하면서도 호스트 CPU 오버헤드를 0으로 유지할 수 있는 필수 아키텍처입니다.
