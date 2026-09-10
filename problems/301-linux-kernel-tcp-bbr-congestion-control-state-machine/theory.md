# 리눅스 커널 TCP BBR 혼잡 제어와 클라인록 최적 제어 이론 (Linux Kernel TCP BBR & Kleinrock Operating Point)

## 1. 개요: 손실 기반 혼잡 제어의 종말

전통적인 TCP 혼잡 제어 알고리즘인 Reno(1988)와 CUBIC(2008)은 **패킷 손실(Packet Loss)**을 네트워크 혼잡의 유일한 신호로 해석했습니다.
이 방식은 1980년대 라우터 버퍼가 수 킬로바이트 수준이던 시절에는 유효했으나, 현대 초고속 인터넷에서는 다음과 같은 치명적인 문제점을 야기했습니다:
1. **버퍼블로트(Bufferbloat)**: 스위치와 라우터에 대용량 버퍼가 탑재되면서, 패킷 드롭이 발생할 때까지 수백 밀리초~수 초 분량의 데이터가 큐에 쌓여 레이턴시가 폭증합니다.
2. **랜덤 손실에 취약**: 무선 WiFi나 5G, 해저 광케이블 등 물리적 노이즈로 인한 경미한 패킷 손실(0.1%)에도 송신 윈도우를 절반으로 깎아 대역폭을 낭비합니다.

2016년 구글의 반 제이콥슨(Van Jacobson), 닐 카드웰(Neal Cardwell) 등은 이러한 패러다임을 완전히 폐기하고, 물리적 병목 대역폭과 전파 지연을 직접 측정하여 구동하는 **BBR(Bottleneck Bandwidth and RTT)**을 개발하여 리눅스 4.9 커널에 메인라인으로 머지했습니다.

---

## 2. 클라인록의 최적 동작점 (Kleinrock's Optimal Operating Point)

레너드 클라인록(Leonard Kleinrock)의 대기행렬 이론에 따르면, 네트워크 파이프라인의 상태는 크게 세 영역으로 구분됩니다:

```
 Throughput
     ^
     |         (Kleinrock Point)
BtlBw|             *------------------ (Bottleneck Bandwidth Saturation)
     |            /
     |           /
     |          /
     +---------+----------------------> Inflight Data (Packets in Flight)
               ^
              BDP = BtlBw * RTprop

     RTT
     ^
     |                                (Bufferbloat Queueing Delay)
     |                             *--
     |                            /
RTprop|--------------------------*   (Min Round-Trip Time)
     +-------------------------+------> Inflight Data
                               ^
                              BDP
```

- **Inflight < BDP**: 파이프가 덜 차서 처리량이 대역폭 미만.
- **Inflight = BDP (클라인록 최적점)**: 처리량은 최대(`BtlBw`)에 달하고, 라우터 큐에는 패킷이 전혀 쌓이지 않아 왕복 시간은 물리적 최소치(`RTprop`)를 기록함.
- **Inflight > BDP**: 처리량은 증가하지 않고, 남는 패킷이 전부 라우터 버퍼에 쌓여 RTT만 급증함(버퍼블로트).

BBR의 단 하나의 목표는 **"Inflight를 항상 BDP 근방에 위치시키고, 큐가 비어 있는 상태를 유지하는 것"**입니다.

---

## 3. 이중 윈도우 필터와 독립 측정 원리

하이젠베르크의 불확정성 원리처럼, 하나의 측정 패킷으로 병목 대역폭(`BtlBw`)과 최소 RTT(`RTprop`)를 동시에 정확히 측정하는 것은 불가능합니다 (대역폭을 측정하려면 큐를 채워야 하고, 최소 RTT를 측정하려면 큐를 비워야 하기 때문).

BBR은 이 모순을 해결하기 위해 **서로 다른 시간 주기를 갖는 이중 윈도우 필터**를 사용합니다:
1. **BtlBw Max Filter**: 최근 10개(또는 10 RTT)의 전달률(Delivery Rate) 샘플 중 최댓값을 취합니다.
2. **RTprop Min Filter**: 최근 10초(또는 장기 윈도우) 동안 관측된 RTT 중 최솟값을 취합니다.

---

## 4. 페이싱(Pacing) 엔진과 FQ(Fair Queueing) 스케줄러

전통적인 TCP는 버스트(Burst) 형태로 패킷을 한꺼번에 쏟아붓고 ACK 클럭에 의존했습니다.
그러나 BBR은 커널 패킷 스케줄러(`sch_fq`)와 결합하여, 패킷 하나하나를 나노초/마이크로초 단위로 균등하게 쪼개어 내보내는 **하드웨어/소프트웨어 페이싱(Pacing Rate)**을 강제합니다:
$$\text{pacing\_rate} = \text{pacing\_gain} \times \text{BtlBw}$$

이를 통해 패킷들이 라우터 버퍼에 군집(Cluster)을 형성하여 충돌하는 현상을 원천 방지하고, 버퍼 용량이 작은 라우터에서도 패킷 드롭 없이 99% 이상의 링크 포화율을 달성할 수 있습니다.
