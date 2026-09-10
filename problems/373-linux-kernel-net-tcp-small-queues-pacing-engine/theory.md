# 리눅스 커널 TCP Small Queues (TSQ)와 안티 버퍼블로트 아키텍처

## 1. 서론: 버퍼블로트(Bufferbloat)의 재앙

1980년대 존 네이글(John Nagle)과 반 제이콥슨(Van Jacobson)이 혼잡 제어(Congestion Control) 알고리즘을 구축한 이래, 인터넷 트래픽의 대다수는 패킷 손실(Packet Loss)을 혼잡 신호로 감지하여 윈도우를 줄이는 손실 기반 혼잡 제어(Reno, Cubic 등)에 의존해 왔습니다.

그러나 메모리 반도체 가격의 급락과 함께 라우터, 스위치, DSL/케이블 모뎀, 그리고 서버의 NIC 링 버퍼 크기가 수십 메가바이트 단위로 무분별하게 확장되었습니다. 그 결과:
1. TCP 송신자는 네트워크 병목 링크가 감당할 수 있는 속도보다 훨씬 빠른 속도로 버스트 패킷을 쏟아붓습니다.
2. 병목 지점의 대용량 버퍼는 패킷을 드롭하지 않고 몇 초 동안 머금고 있게 됩니다.
3. 패킷 손실이 발생하지 않으므로 송신자는 혼잡 윈도우를 계속 키우고, 큐는 꽉 차서 지연 시간(RTT)이 수백 ms에서 수 초까지 치솟습니다.

이 현상을 **버퍼블로트(Bufferbloat)**라고 부릅니다. 대용량 파일 다운로드(FTP/비디오 스트리밍)가 시작되는 순간 웹 브라우징, DNS 조회, 게이밍, VoIP 통화의 반응성이 파괴되는 원인이 바로 이것입니다.

---

## 2. 계층별 안티 버퍼블로트 트라이어드 (Triad)

리눅스 커널 네트워크 서브시스템은 버퍼블로트를 근절하기 위해 3단계 방어선을 구축했습니다:

```
+---------------------------------------------------------------------------------+
|                       Linux Kernel Anti-Bufferbloat Triad                       |
+---------------------------------------------------------------------------------+

  [Layer 4: Transport (TCP)]
  ==========================
  • TCP Small Queues (TSQ) - net/ipv4/tcp_output.c
    - 소켓당 Qdisc + Driver 계층에 보류 가능한 skb 메모리를 2개 skb (~128KB) 이하로 억제
    - 초과 시 TSQ_THROTTLED 설정 및 소켓 송신 동결

  [Layer 3: Packet Scheduler (Qdisc)]
  ===================================
  • FQ (Fair Queueing) & CoDel / FQ-CoDel / CAKE - net/sched/sch_fq.c
    - 플로우별 큐 분리 및 공정 대역폭 분배
    - 소켓 페이싱(Socket Pacing): 버스트 전송 방지 및 균일한 패킷 인터벌 유지
    - 소호(Buffer) 체류 시간 감시 및 임계치 초과 패킷 능동적 폐기(CoDel)

  [Layer 2: Device Driver & Hardware Ring]
  ========================================
  • Byte Queue Limits (BQL) - net/sched/sch_generic.c, lib/dynamic_queue_limits.c
    - NIC 하드웨어 TX 링 버퍼의 미완료 바이트를 동적 측정
    - 하드웨어가 굶주리지(Starvation) 않을 최소한의 큐 깊이만 허용
```

---

## 3. TCP Small Queues (TSQ)의 심층 내부 구조

### 3.1 소켓 송신 메모리 회계: `sk_wmem_alloc`
리눅스 소켓 구조체 `struct sock`은 송신용으로 할당된 총 메모리를 추적하는 원자적 변수 `atomic_t sk_wmem_alloc`을 보유합니다.
- 패킷(sk_buff)이 생성되어 TCP 계층을 떠나 IP/Qdisc/드라이버로 내려갈 때:
  `atomic_add(skb->truesize, &sk->sk_wmem_alloc)`
- `truesize`는 실제 페이로드 데이터뿐만 아니라 `struct sk_buff` 헤더, `skb_shared_info`, 슬랩 할당자 정렬 오버헤드를 모두 포함한 실제 RAM 점유 바이트입니다 (보통 1460 바이트 MSS 패킷의 truesize는 약 2048~2304 바이트).

### 3.2 TSQ 한도 산출식
리눅스 커널 `tcp_output.c`의 TSQ 한도 계산 로직:
```c
static bool tcp_small_queue_check(struct sock *sk, const struct sk_buff *skb,
                                  unsigned int factor)
{
    unsigned int limit;

    limit = max_t(unsigned int, 2 * skb->truesize,
                  min_t(unsigned int,
                        sk->sk_pacing_rate >> factor,
                        sock_net(sk)->ipv4.sysctl_tcp_limit_output_bytes));

    if (atomic_read(&sk->sk_wmem_alloc) > limit) {
        set_bit(TSQ_THROTTLED, &tp->tsq_flags);
        return true; // 스로틀링 발생!
    }
    return false;
}
```
- 최소 한도: 패킷 2개의 truesize ($2 \times \text{skb\_truesize}$). 이는 NIC가 다음 패킷을 처리하는 동안 드라이버 링이 비어 파이프라인이 중단되는 기아 현상(Starvation)을 방지합니다.
- 최대 한도: `sysctl_tcp_limit_output_bytes` (디폴트 128KB 또는 256KB) 또는 소켓 페이싱 레이트에 비례하는 값.

### 3.3 비동기 통지와 `tcp_wfree()`의 마법
소켓이 스로틀링되면 CPU는 소켓 전송을 멈추고 유휴 상태가 되거나 다른 태스크를 실행합니다.
이후 NIC가 실제 패킷을 송출 완료하면 TX 완료 인터럽트가 발생하고, 인터럽트 핸들러(NAPI/Softirq)는 `dev_kfree_skb()`를 거쳐 패킷의 소멸자(Destructor)인 `tcp_wfree()`를 실행합니다:

```c
void tcp_wfree(struct sk_buff *skb)
{
    struct sock *sk = skb->sk;

    if (test_and_clear_bit(TSQ_THROTTLED, &tp->tsq_flags)) {
        // Softirq 태스크릿 또는 워크큐를 통해 소켓 전송 재개
        tasklet_schedule(&tsq_tasklet);
    }
    atomic_sub(skb->truesize, &sk->sk_wmem_alloc);
}
```
`tcp_wfree()`가 호출되는 순간 `sk_wmem_alloc`이 감소하면서 `TSQ_THROTTLED` 비트가 클리어되고, 지연되었던 `tcp_write_xmit()`이 즉시 재개됩니다.

---

## 4. 소켓 페이싱(Pacing)과 FQ 스케줄러의 연동

전통적인 TCP는 cwnd가 100 패킷이면 100개의 패킷을 선로 대역폭(Line Rate)으로 연달아 발사하는 **마이크로 버스트(Micro-burst)**를 유발했습니다. 이는 스위치 버퍼에 순간적인 혼잡을 일으킵니다.

리눅스는 `SO_MAX_PACING_RATE` 및 `sk->sk_pacing_rate`를 통해 각 세그먼트 사이의 시간 간격을 계산합니다:
$$
\Delta t_{\text{pacing}} = \frac{\text{skb\_len} \times 10^9}{\text{sk\_pacing\_rate}} \quad (\text{ns})
$$
FQ(Fair Queueing) 스케줄러는 각 소켓의 `pacing_next_time`을 레드-블랙 트리(RB-Tree)로 관리하며, 정확한 나노초 타이머(`hrtimer`)를 통해 패킷을 부드럽게(Smooth) 분산 송출합니다.

TSQ와 FQ Pacing의 결합은 버퍼블로트를 완전히 제거하면서도 100Gbps+ 초고속 링크에서 99.99% 대역폭 효율을 달성하는 리눅스 네트워크 스택의 핵심 토대입니다.
