# 기술 이론: 리눅스 커널 GRO(Generic Receive Offload) 및 NAPI 서브시스템 아키텍처

## 1. 개요 및 설계 철학
100GbE NIC 환경에서는 64바이트 최소 패킷 기준 초당 최대 **1억 4,800만 개(148 Mpps)**, 1500바이트 MTU 패킷 기준 약 **810만 개(8.1 Mpps)**의 패킷이 시스템으로 쏟아져 들어옵니다.

현대 x86 CPU 1개 코어(3.0 GHz)의 클럭 사이클은 초당 30억 번 진동합니다. 즉, 패킷당 허용되는 CPU 시간은 불과 **370 사이클(Clock Cycles)**에 불과합니다. 단 한 번의 L3 캐시 미스(약 200 사이클)나 메인 메모리 DRAM 접근(약 250~300 사이클)만으로도 패킷 처리가 지연되어 링 버퍼 드롭이 발생합니다.

리눅스 커널은 이를 해결하기 위해 두 가지 핵심 계층을 도입했습니다:
1. **NAPI(New API)**: 인터럽트 폭풍(Interrupt Storm)을 방지하고 폴링(Polling) 루프로 패킷을 일괄 수거.
2. **GRO(Generic Receive Offload)**: 드라이버 수신 단계에서 동일 플로우의 연속 세그먼트들을 64KB의 슈퍼 패킷으로 병합(`skb_gro_receive`)하여 네트워크 스택의 트래버설 비용을 $O(N)$에서 $O(N / K)$ ($K \approx 45 \sim 64$)로 감축.

```
       [ 하드웨어 NIC RX Ring Buffer ]
                     │
            DMA 전송 및 NAPI 인터럽트
                     ▼
          [ napi_struct -> poll() ]
                     │
            napi_gro_receive(&napi, skb)
                     │
          ┌──────────┴──────────┐
          │  GRO 엔진 검증       │ ◀─── 5-Tuple, SEQ, DF, ACK 확인
          └──────────┬──────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   [ Coalesce 병합 ]        [ Flush 방출 ]
    (skb 페이로드 결합)     (napi_gro_complete)
                                 │
                                 ▼
                     [ netif_receive_skb ]
                                 │
                     [ TCP/IP L4 Socket Stack ]
```

---

## 2. GRO vs LRO 비교 분석

| 비교 항목 | LRO (Large Receive Offload) | GRO (Generic Receive Offload) |
| :--- | :--- | :--- |
| **구현 계층** | NIC 하드웨어 ASIC 또는 드라이버 종속적 | 커널 코어 계층 (`net/core/dev.c`) |
| **프로토콜 무결성** | 헤더 필드 무차별 병합 (ECN/SACK 유실) | TCP 의미론 100% 엄격 보존 |
| **라우팅 / 포워딩** | 불가 (게이트웨이 장비에서 패킷 훼손) | 완전 지원 (필요 시 세그먼트 분할 보존) |
| **적용 범위** | 특정 IPv4/TCP 환경에 한정 | IPv4, IPv6, UDP(GRO/GSO), VXLAN, Geneve |
| **제어 패킷 처리** | SYN/FIN/RST 오작동 위험 | 즉시 바이패스 및 펜딩 버퍼 강제 플러시 |

---

## 3. GRO 병합 알고리즘의 3대 불변 조건 (Invariants)

리눅스 커널 `net/ipv4/tcp_offload.c`의 `tcp_gro_receive()` 함수는 다음의 불변 조건을 철저히 검증합니다:

### (1) 연속성 불변식 (Sequence Continuity)
수신된 세그먼트의 TCP Sequence Number $S_{curr}$은 선행 보류 세그먼트의 마지막 시퀀스 번호 $S_{prev}$와 페이로드 길이 $L_{prev}$의 합과 완벽히 일치해야 합니다:
$$S_{curr} = S_{prev} + L_{prev}$$
단 1바이트라도 차이가 발생하면(패킷 유실 또는 역전 도착), TCP 슬라이딩 윈도우 무결성을 위해 기존 보류 패킷을 즉시 방출(`OUT_OF_ORDER`)합니다.

### (2) IP ID 일관성 (IP Identification Consistency)
IPv4 헤더의 Don't Fragment(DF) 플래그가 설정되어 있지 않은 경우(`DF == 0`), 네트워크 경로상에서 패킷이 재조합될 수 있으므로 커널은 IP ID가 반드시 연속 단조 증가($\text{ID}_{curr} = \text{ID}_{prev} + 1$)할 것을 요구합니다. 반면 `DF == 1`인 경우 최신 리눅스 커널은 동일한 ID나 난수 ID를 허용합니다.

### (3) 플래그 및 옵션 보존 (Flag & Option Preservation)
- `SYN`, `FIN`, `RST`, `URG` 제어 플래그는 TCP 연결 상태 전이(State Transition)를 유발하므로 절대 병합할 수 없습니다. 도착 즉시 사유 `"CONTROL_PACKET"`으로 방출됩니다.
- `PSH(Push)` 플래그는 상위 애플리케이션으로의 즉시 전달 신호이므로 슈퍼 패킷의 메타데이터에 비트 OR 연산으로 누적 보존됩니다.

---

## 4. 리눅스 커널 핵심 자료구조 및 함수 맵

- `struct napi_struct`: 디바이스 드라이버의 NAPI 인스턴스. 내부에 `gro_hash` 및 `gro_list` 보유.
- `napi_gro_receive()`: 디바이스 드라이버가 RX 링에서 패킷을 꺼내 커널 GRO 계층으로 인입시키는 메인 진입점.
- `dev_gro_receive()`: L2(이더넷, VLAN) 오프로드 계층.
- `inet_gro_receive()`: IPv4 헤더, 체크섬, DF 비트, ToS 검증.
- `tcp_gro_receive()`: TCP 5-튜플, 시퀀스, ACK, 윈도우, 제어 플래그 검증 및 `skb_gro_receive` 호출.
- `napi_gro_complete()`: 병합된 슈퍼 패킷의 최종 IP 총 길이(Total Length) 및 TCP 체크섬을 재계산하고 `netif_receive_skb()`로 전달.
