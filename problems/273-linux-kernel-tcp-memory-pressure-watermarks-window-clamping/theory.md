# 리눅스 커널 TCP 메모리 아키텍처와 압박 회수 메커니즘 (Linux Kernel TCP Memory Architecture & Pressure Recovery)

## 1. tcp_mem의 단위와 오해: 바이트가 아니라 4KB 페이지다!

많은 시스템 엔지니어들이 `sysctl` 튜닝 시 가장 흔히 범하는 실수는 `net.ipv4.tcp_mem`의 값을 바이트(Bytes)로 착각하는 것입니다:
- `tcp_rmem`과 `tcp_wmem`은 **바이트(Bytes)** 단위입니다 (`[min, default, max]`).
- 반면 `tcp_mem`은 **메모리 페이지(Pages, x86_64 기본 4096 Bytes)** 단위입니다!

예를 들어 서버에 128GB RAM이 있더라도 `tcp_mem = 65536 131072 262144`로 기본 설정되어 있다면:
- `pressure` 한계: $131,072 \times 4\text{KB} = 512\text{MB}$!
- `max` 한계: $262,144 \times 4\text{KB} = 1024\text{MB} = 1\text{GB}$!

즉, 서버에 수십 GB의 메모리가 남아돌아도 TCP 버퍼의 합이 고작 512MB를 넘는 순간 전사적인 TCP 패킷 드롭과 커넥션 프리징이 발생합니다.

---

## 2. TCP 메모리 압박 3단계 상태 머신과 히스테리시스(Hysteresis)

```
       [Allocated Pages]
              ▲
              │
    max       ├─── Hard Limit: skb_alloc 실패 (-ENOBUFS), 패킷 즉시 드롭, 신규 SYN 거부
              │
              │    [STATUS_PRESSURE_OFO_PRUNED]
    pressure  ├─── Memory Pressure Onset: OFO 큐 파기, Window Clamping, autotuning 동결
              │    ▲
              │    │ (히스테리시스 구간: 압박 상태 유지)
              │    ▼
    min       └─── Pressure Cleared: tcp_memory_pressure = 0 환원, 정상 버퍼 확장 재개
              │
              └─► [STATUS_NORMAL]
```

커널은 압박 플래그가 수시로 켜지고 꺼지며 발생하는 진동(Flapping)을 방지하기 위해 **히스테리시스 루프**를 적용합니다:
- `pages > pressure` $\implies$ `pressure_state = True`
- `pages < min` $\implies$ `pressure_state = False`
- `min <= pages <= pressure` $\implies$ 이전 상태를 그대로 유지!

---

## 3. OFO(Out-of-Order) 큐 파기와 윈도우 클램핑(Window Clamping)

1. **`tcp_collapse_ofo_queue()`**:
   네트워크 지연이나 패킷 손실로 인해 순서가 뒤바뀐 패킷들은 소켓의 OFO 큐(RB-Tree)에 임시 버퍼링됩니다. 메모리 압박이 발생하면 커널은 애플리케이션의 정상 동작보다 커널 생존을 우선시하여 이 OFO 버퍼를 즉각 강제 해제합니다. 송신측은 해당 패킷을 타임아웃 후 재전송해야 합니다.
2. **`tcp_clamp_window()`**:
   소켓이 상대방에게 수신 윈도우(`rcv_wnd`)를 알릴 때, 가용 수신 버퍼 여유 공간을 축소하여 통보합니다. 버퍼 고갈 시 `Zero Window (win 0)`을 전송하여 송신측의 전송 파이프라인을 완전히 차단함으로써 시스템 패닉을 방어합니다.
