# 문제 #288: TCP Prague와 L4S DualQ 결합형 능동 큐 관리(Coupled AQM): 서브밀리초 지연과 100% 링크 이용률 동시 달성 시뮬레이터

## 실무 배경: 클라우드 게이밍 & XR 스트리밍의 버퍼블로트(Bufferbloat) 참사와 처리량-지연 시간의 트레이드오프
초저지연 인터랙티브 비디오(클라우드 게이밍, Vision Pro XR 스트리밍, 자율주행 원격 제어) 서비스를 글로벌 배포한 엔지니어링 팀은 심각한 기술적 장벽에 부딪혔습니다. 사용자가 4K 게임을 플레이하는 도중 백그라운드 대용량 파일 다운로드(Classic TCP CUBIC)가 시작되면, 엔드투엔드 네트워크 RTT가 평상시 12ms에서 무려 280ms(23배 이상)로 폭증하며 입력 지연과 화면 찢어짐(Jitter/Lag)이 발생한 것입니다.

이것이 바로 반세기 동안 인터넷을 괴롭혀온 **버퍼블로트(Bufferbloat)** 문제입니다:
* **전통적 CUBIC / Reno의 비극**: 패킷 손실이 발생하거나 고전적 ECN 마킹(RFC 3168)을 받으면 혼잡 윈도우(`cwnd`)를 일거에 30~50% 삭감(Multiplicative Decrease)합니다. 이 급격한 윈도우 삭감 후 링크 대역폭이 비는 것을 막으려면 병목 라우터에 수십~수백 밀리초 분량의 거대한 패킷 버퍼가 필수적입니다.
* **낮은 지연시간(Low Latency)과 높은 대역폭(High Throughput)의 상충**: 큐 크기를 강제로 줄이면 CUBIC의 링크 이용률이 40% 미만으로 곤두박질치고, 큐를 키우면 수백 ms의 지연시간이 축적됩니다.

이 한계를 영구히 극복하기 위해 IETF는 2023년 **L4S (Low Latency, Low Loss, Scalable Throughput: RFC 9330, RFC 9331, RFC 9332)** 표준을 확정했습니다.
L4S의 핵심은 두 개의 큐를 운영하는 **DualQ Coupled AQM(Active Queue Management)**과, 미세한 ECN 마킹 비율에 비례하여 윈도우를 부드럽게 미세조정하는 **TCP Prague** 혼잡 제어 알고리즘의 결합입니다.

네트워크 트랜스포트 시스템 엔지니어로서, 고전적 CUBIC 트래픽과 L4S Prague 트래픽이 병목 링크를 공유할 때 **서브밀리초(< 1ms) 대기 지연과 패킷 손실 0%, 그리고 두 트래픽 간의 완벽한 공정성(Fairness)**을 보장하는 DualQ Coupled AQM 엔진을 구현하십시오.

---

## DualQ Coupled AQM 및 TCP Prague 알고리즘 사양

### 1. DualQ 라우터 아키텍처 (RFC 9332)
병목 라우터는 두 개의 독립적인 논리 큐를 유지합니다:
* **Classic 큐 ($Q_C$)**: 고전적 트래픽(ECT(0), Not-ECT) 수용.
  - 목표 큐 깊이: `c_target_pkts` (밀리초 단위의 완충 버퍼).
  - 큐 길이가 목표를 초과할 경우 드롭/마킹 확률 $p_C$가 점진적으로 증가:
    $$p_C \leftarrow \min\left(1.0, p_C + 0.05 	imes rac{|Q_C| - c_{	ext{target}}}{c_{	ext{target}}}ight)$$
    (큐 길이가 목표 이하일 경우 $p_C \leftarrow \max(0.0, p_C 	imes 0.85)$로 감쇠).
  - 패킷이 $Q_C$를 탈출할 때 $p_C > 0.12$인 경우:
    - 패킷이 `ECT(0)`이면 `CE (Congestion Experienced)`로 비트 마킹.
    - 패킷이 `Not-ECT`이면 패킷을 즉시 드롭(Tail Drop/AQM Drop).
* **L4S 큐 ($Q_L$)**: 확장형 초저지연 트래픽(ECT(1)) 전용 수용.
  - 즉각적 스텝 마킹(Step Marking): 패킷 잔류 개수가 `l_thresh_pkts` 이상이면 즉시 `CE` 마킹.
  - 결합 마킹 확률 $p_{	ext{coupled}}$: Classic 큐의 혼잡을 L4S 큐로 연동하여 공정성을 보장:
    $$p_{	ext{coupled}} = \min(1.0, k 	imes \sqrt{p_C})$$
    ($k$는 결합 계수 `coupling_k`).
  - L4S 패킷 추출 시 `len(Q_L) >= l_thresh` 이거나 `p_coupled > 0.35`이면 `CE` 마킹.
* **DualQ 스케줄러**:
  - L4S 큐에 우선순위를 부여하되, Classic 큐의 기아(Starvation)를 방지하기 위해 슬롯당 L4S 배출 한도를 전체 용량의 `l_max_quota_ratio`(기본 80%)로 캡핑.
  - L4S 할당량 소진 후 Classic 큐를 배출하고, 여유 슬롯이 남으면 잔여 L4S를 추가 배출.

---

### 2. 송신자 혼잡 제어 (CUBIC vs TCP Prague)
* **Classic CUBIC**:
  - `ECT(0)` 또는 `Not-ECT` 사용.
  - 드롭 또는 CE 마킹 수신 시: 30% 삭감 ($	ext{cwnd} \leftarrow \max(2.0, 	ext{cwnd} 	imes 0.7)$).
  - 무손실/무마킹 수신 시: 윈도우 1.0 증가 ($	ext{cwnd} \leftarrow 	ext{cwnd} + 1.0$).
* **TCP Prague (RFC 9331)**:
  - `ECT(1)` 사용.
  - AccECN 피드백: RTT당 도착한 CE 마킹 비율 $f = rac{	ext{marks}}{	ext{acked}}$ 산출.
  - 마킹 비율의 지수 이동 평균(EWMA) $lpha$ 갱신 ($g = 	ext{ewma\_g}$, 기본 $1/16 = 0.0625$):
    $$lpha \leftarrow (1 - g)lpha + g \cdot f$$
  - 혼잡 발생 시 스케일러블 백오프:
    $$	ext{cwnd} \leftarrow \max\left(2.0, 	ext{cwnd} 	imes \left(1 - rac{lpha}{2}ight)ight)$$
  - 무마킹 시: 윈도우 1.0 증가.

---

## 입력 형식
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "capacity_pkts_per_slot": 16,
    "l_thresh_pkts": 2,
    "c_target_pkts": 6,
    "coupling_k": 2.0,
    "l_max_quota_ratio": 0.8,
    "duration_slots": 6
  },
  "flows": [
    {"id": "cubic_coexist", "type": "CUBIC", "initial_cwnd": 8.0, "ecn_type": "ECT(0)"},
    {"id": "prague_coexist", "type": "PRAGUE", "initial_cwnd": 8.0, "ecn_type": "ECT(1)"}
  ]
}
```

## 출력 형식
표준 출력(stdout)으로 매 슬롯 큐 상태 및 최종 성능 지표를 JSON 단일 라인으로 출력합니다:
```json
{
  "slots_simulated": 6,
  "history": [
    {
      "slot": 0,
      "qlen_classic": 0,
      "qlen_l4s": 0,
      "drained_total": 16,
      "flows": {
        "cubic_coexist": {"cwnd": 9.0, "delivered": 8, "alpha": null},
        "prague_coexist": {"cwnd": 8.0, "delivered": 8, "alpha": 0.0}
      }
    }
  ],
  "summary": {
    "mean_qlen_classic": 1.5,
    "mean_qlen_l4s": 0.17,
    "l4s_latency_advantage_ratio": 8.82,
    "jains_fairness_index": 0.9984,
    "delivered_per_flow": {"cubic_coexist": 48, "prague_coexist": 48},
    "drops": {"classic": 0, "l4s": 0},
    "marks": {"classic": 0, "l4s": 2}
  }
}
```
