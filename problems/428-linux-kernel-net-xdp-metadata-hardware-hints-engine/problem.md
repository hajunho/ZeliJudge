# 문제 428: 리눅스 커널 네트워킹 및 eBPF: XDP 메타데이터(data_meta) 및 하드웨어 오프로드 힌트(XDP Hints) 엔진

## 1. 개요 (Overview)

초고속 클라우드 데이터센터(100GbE, 200GbE, 400GbE) 및 고성능 패킷 프로세싱 환경에서 **XDP(eXpress Data Path)**는 네트워크 드라이버의 가장 초기 수신 단계(RX Ring)에서 `sk_buff` 할당 없이 패킷을 직접 검사하고 조작할 수 있는 초저지연 프레임워크입니다.

그러나 과거의 XDP 아키텍처는 심각한 딜레마를 안고 있었습니다:
최신 스마트 NIC(Intel E810, Mellanox ConnectX-6 Dx 등)의 하드웨어 ASIC은 패킷을 수신할 때 이미 L3/L4 체크섬(IP/TCP/UDP Checksum) 검증, RSS(Receive Side Scaling) 5-튜플 플로우 해시 계산, PTP 하드웨어 타임스탬프 기록, 802.1Q VLAN 태그 분리 등을 하드웨어 레벨에서 완료합니다.
하지만 XDP 프로그램이 패킷을 필터링하거나 검사한 후 일반 리눅스 네트워크 스택으로 전달하기 위해 **`XDP_PASS`**를 반환하면, 드라이버가 하드웨어 디스크립터 메타데이터를 폐기하고 원시 패킷 버퍼만 스택으로 넘기기 때문에 **이미 하드웨어가 계산했던 체크섬과 해시가 모두 유실**되었습니다. 결과적으로 리눅스 커널 스택(GRO, TCP 계층)은 수 기가헤르츠의 CPU 사이클을 낭비하며 소프트웨어로 체크섬을 다시 계산해야 했습니다.

리눅스 커널 커뮤니티는 리눅스 6.3+ 및 6.x 시리즈에서 이를 혁신하기 위해 **XDP 힌트(XDP Hints)**와 **동적 메타데이터 프리헤더(`bpf_xdp_adjust_meta`)** 표준을 도입했습니다.

XDP 프로그램은 `bpf_xdp_adjust_meta(ctx, -offset)`를 호출하여 패킷 헤드룸(`headroom`) 영역으로 `ctx->data_meta` 포인터를 확장한 뒤, 하드웨어 힌트 kfunc(`bpf_xdp_metadata_rx_*`)를 통해 NIC ASIC이 계산한 체크섬 유효성, 플로우 해시, 타임스탬프를 메타데이터 영역에 기록합니다. 이후 `XDP_PASS`로 커널 스택에 진입하면, 네트워크 스택은 메타데이터를 읽어 `skb->ip_summed = CHECKSUM_UNNECESSARY`로 설정하여 소프트웨어 체크섬 연산을 100% 생략하고 하드웨어 오프로드를 유지합니다.

본 과제에서는 리눅스 커널 `net/core/filter.c` 및 `include/net/xdp.h` 기반의 XDP 메타데이터 헤드룸 확장, 하드웨어 힌트 파싱 및 기입, XDP 액션(`XDP_PASS`, `XDP_DROP`, `XDP_REDIRECT`), 그리고 하드웨어 체크섬 오프로드 바이패스 파이프라인을 완벽히 모델링합니다.

---

## 2. 시스템 아키텍처 및 메타데이터 헤드룸 레이아웃

```
[Packet Buffer Memory Layout with XDP Metadata]
+-------------------+-------------------+-----------------------------------+
| Reserved Headroom | XDP Metadata Area |            Packet Data            |
| (Driver Reserved) |   (data_meta)     |       (data ~ data_end)           |
+-------------------+-------------------+-----------------------------------+
^                   ^                   ^                                   ^
packet_start        data_meta           data                                data_end
                    <--- delta (< 0) ---
                    (bpf_xdp_adjust_meta)

-------------------------------------------------------------------------------

[Hardware Hints to Kernel SKB Pipeline]
  NIC Hardware ASIC (Hardware Checksum OK, RSS Hash 0x1234, PTP Timestamp)
       │
       ▼ (Raw Packet Arrives at Driver RX)
  XDP Program
       │
       ├─► bpf_xdp_adjust_meta(ctx, -32)   (Allocates metadata space in headroom)
       │
       ├─► populate_hints(RX_CSUM, HASH)  (Writes HW ASIC hints into data_meta)
       │
       ▼ (Returns XDP_PASS)
  Linux Kernel Network Stack (napi_gro_receive)
       │
       ├─► Inspects data_meta
       │   ├─► csum_valid == True  ──► skb->ip_summed = CHECKSUM_UNNECESSARY (0 CPU cycles!)
       │   └─► csum_valid == False ──► skb->ip_summed = CHECKSUM_NONE (Software fallback)
       │
       └─► Preserves Hardware RSS Hash & Timestamp for Socket Steering
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 엔진 구성 매개변수 (`config`)
- `headroom`: 패킷 버퍼 시작 지점에 할당된 기본 헤드룸 크기(바이트, 기본값 `64`).

### 3.2 이벤트 처리 규칙

1. **`NIC_RX_PACKET` (`time`, `pkt_id`, `data_len`, `hw_csum_valid`, `hw_rx_hash`, `hw_timestamp_ns`, `vlan_tag`)**:
   - 하드웨어 NIC에서 물리 패킷이 수신된 시점을 모사합니다.
   - 초기 패킷 상태: `headroom = config.headroom`, `meta_len = 0`, `meta_payload = {}`.
   - `packets_received`를 1 증가시키고 `event_logs`에 `NIC_RX_PACKET`을 기록합니다.

2. **`BPF_XDP_ADJUST_META` (`time`, `pkt_id`, `delta`)**:
   - `bpf_xdp_adjust_meta` 헬퍼 함수를 모사합니다.
   - `delta < 0` (메타데이터 공간 확장):
     - 요청 크기 `needed = abs(delta)`가 패킷의 남은 `headroom`보다 크면 헤드룸 고갈 에러입니다.
     - `headroom_exhaustions`를 1 증가시키고, `XDP_META_ERROR`(`ENOSPC_HEADROOM_EXHAUSTED`)를 기록하며 실패(`-28, -ENOSPC`)를 반환합니다.
     - 남은 공간이 충분하면:
       - `headroom -= needed`, `meta_len += needed`, `meta_adjusted_count += 1`.
       - `event_logs`에 `BPF_XDP_ADJUST_META_SUCCESS`를 기록합니다.

3. **`POPULATE_METADATA_HINTS` (`time`, `pkt_id`, `fields`)**:
   - XDP 프로그램이 드라이버 kfunc를 호출하여 하드웨어 힌트를 메타데이터에 채워 넣습니다.
   - `meta_len == 0`이면 메타데이터 공간이 할당되지 않았으므로 `NO_METADATA_SPACE_ALLOCATED` 에러를 기록하고 중단합니다.
   - 요청된 필드에 따라 하드웨어 정보를 기록합니다:
     - `"RX_CSUM"`: `csum_valid = hw_csum_valid`
     - `"RX_HASH"`: `rx_hash = hw_rx_hash`
     - `"TIMESTAMP"`: `timestamp_ns = hw_timestamp_ns`
     - `"VLAN"`: `vlan_tag = vlan_tag`
   - `event_logs`에 `METADATA_HINTS_POPULATED`를 기록합니다.

4. **`XDP_RETURN` (`time`, `pkt_id`, `action`)**:
   - XDP 프로그램의 최종 반환 액션을 처리합니다.
   - **`action == "XDP_DROP"`**:
     - `xdp_drop_count`를 1 증가시키고 `event_logs`에 `XDP_ACTION_DROP`을 기록합니다. 패킷은 즉각 폐기됩니다.
   - **`action == "XDP_REDIRECT"`**:
     - `xdp_redirect_count`를 1 증가시키고 `event_logs`에 `XDP_ACTION_REDIRECT`를 기록합니다 (`meta_forwarded = (meta_len > 0)`).
   - **`action == "XDP_PASS"`**:
     - `xdp_pass_count`를 1 증가시키고 커널 `sk_buff` 구조체를 생성합니다:
       - `meta_payload`에 `csum_valid == True`가 포함되어 있으면:
         `skb.ip_summed = "CHECKSUM_UNNECESSARY"`, `hardware_csum_offloaded += 1`.
       - 메타데이터가 없거나 `csum_valid == False`이면:
         `skb.ip_summed = "CHECKSUM_NONE"`, `software_csum_fallbacks += 1`.
       - `meta_payload`에 `rx_hash`, `timestamp_ns`, `vlan_tag`가 있으면 `skb`에 보존합니다.
     - 생성된 `skb`를 `forwarded_skbs` 목록에 추가하고 `event_logs`에 `XDP_PASS_SKB_ALLOCATED`를 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {
    "headroom": 64
  },
  "trace": [
    {"time": 10, "type": "NIC_RX_PACKET", "pkt_id": "p1", "data_len": 1500, "hw_csum_valid": true, "hw_rx_hash": "0x12345678", "hw_timestamp_ns": 1000000, "vlan_tag": 100},
    {"time": 20, "type": "BPF_XDP_ADJUST_META", "pkt_id": "p1", "delta": -32},
    {"time": 30, "type": "POPULATE_METADATA_HINTS", "pkt_id": "p1", "fields": ["RX_CSUM", "RX_HASH", "TIMESTAMP", "VLAN"]},
    {"time": 40, "type": "XDP_RETURN", "pkt_id": "p1", "action": "XDP_PASS"}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"packets_received":1,"meta_adjusted_count":1,"xdp_pass_count":1,"xdp_drop_count":0,"xdp_redirect_count":0,"hardware_csum_offloaded":1,"software_csum_fallbacks":0,"headroom_exhaustions":0},"forwarded_skbs":[{"pkt_id":"p1","len":1500,"ip_summed":"CHECKSUM_UNNECESSARY","hash":"0x12345678","timestamp_ns":1000000,"vlan_tag":100}],"event_logs":[{"time":10,"event":"NIC_RX_PACKET","pkt_id":"p1","len":1500,"hw_csum_valid":true},{"time":20,"event":"BPF_XDP_ADJUST_META_SUCCESS","pkt_id":"p1","meta_len":32,"remaining_headroom":32},{"time":30,"event":"METADATA_HINTS_POPULATED","pkt_id":"p1","populated_fields":["csum_valid","rx_hash","timestamp_ns","vlan_tag"]},{"time":40,"event":"XDP_PASS_SKB_ALLOCATED","pkt_id":"p1","ip_summed":"CHECKSUM_UNNECESSARY","csum_offloaded":true}]}
```
