# Theory #445: 리눅스 커널 실시간 스케줄러: kernel/sched/deadline.c GRUB 대역폭 회수 및 0-Lag 수학적 모델 이론

## 1. 하드 실시간 스케줄링(EDF)과 CBS(Constant Bandwidth Server)의 딜레마

리눅스 커널의 실시간 정책인 `SCHED_DEADLINE`은 Liu & Layland (1973)의 최적 실시간 스케줄링 알고리즘인 **EDF (Earliest Deadline First)**를 기반으로 동작합니다.
각 태스크는 $(Q_i, D_i, P_i)$ 튜플로 정의되며, 단일 코어에서 실행 가능한 충분 조건은 다음과 같습니다:

$$\sum_{i=1}^n \frac{Q_i}{P_i} \le 1.0$$

그러나 순수 EDF는 오동작하거나 무한 루프를 도는 악의적인 태스크가 CPU를 독점하면 다른 모든 실시간 태스크가 연쇄적으로 마감시간을 놓치는 치명적인 결함(Domino Effect)을 가집니다.
이를 방지하기 위해 Abeni & Buttazzo (1998)의 **CBS (Constant Bandwidth Server)**가 도입되었습니다:
- 각 태스크는 최대 $Q_i$만큼의 예산(Runtime Budget)만 사용할 수 있습니다.
- 예산이 소진되면 다음 주기까지 태스크 실행이 강제로 유예(Throttling)됩니다.

### (1) 순수 CBS의 자원 낭비 문제
실시간 미디어 처리(H.264/HEVC 비디오 디코딩, 오디오 DSP, AI 추론)는 프레임의 복잡도에 따라 실행 시간이 극심하게 변동합니다:
- 최악 프레임(I-Frame): $10\text{ms}$ 소요 -> 예산 $Q_i = 10\text{ms}$ 할당.
- 평균 프레임(B/P-Frame): $2\text{ms}$ 소요 -> 조기 완료(Early Completion).
- 순수 CBS에서는 태스크가 $2\text{ms}$만 쓰고 블록되면, 남은 $8\text{ms}$의 예약된 CPU 대역폭은 아무도 쓰지 못하고 완전히 버려집니다.

---

## 2. GRUB (Greedy Reclamation of Unused Bandwidth) 알고리즘

Giuseppe Lipari와 Sanjoy Baruah (2000)가 제안하고 리눅스 커널 4.13+에 머지된 **GRUB** 알고리즘은 다른 태스크들의 하드 실시간 보장을 털끝만큼도 침해하지 않으면서, 버려지는 유휴 대역폭을 활성 태스크들이 탐욕적으로 나누어 쓰도록 혁신했습니다.

```
+-------------------------------------------------------------+
|               Total CPU Bandwidth (100%)                    |
|                                                             |
|  [ Task A (20%) ] [ Task B (30%) ] [ Idle Bandwidth (50%) ] |
|  ◄──────────── U_act = 50% ──────► ◄── Reclaimed by GRUB ──►|
+-------------------------------------------------------------+
```

### (1) 감속 예산 소모 (Budget Scaling)
태스크 $i$가 물리 시간 $\Delta t$ 동안 CPU에서 실행될 때, 예산 $q_i$의 감소율 $\frac{dq_i}{dt}$는 다음과 같이 정의됩니다:

$$\frac{dq_i}{dt} = \max\left(\frac{Q_i}{P_i}, U_{\text{act}}\right)$$

- 시스템에 $U_A = 0.2, U_B = 0.3$ 두 태스크만 활성화되어 있다면 $U_{\text{act}} = 0.5$입니다.
- 태스크 A가 실행될 때:
  $$\Delta q_A = \max(0.2, 0.5) \times \Delta t = 0.5 \times \Delta t$$
- 즉, 물리 시간 $10\text{ms}$를 실행하더라도 예산은 단 $5\text{ms}$만 깎입니다!
- 결과적으로 태스크 A는 본래 할당된 예산의 2배에 달하는 연산량을 유휴 CPU로부터 합법적으로 흡수하여 수행할 수 있습니다.

---

## 3. 0-Lag 타이머 (Zero-Lag Timer)의 엄밀한 수학적 증명

실시간 시스템 이론에서 태스크 $i$의 지연(Lag)은 "이상적인 비례 공유 서버(Fluid Flow Model)에서 받았어야 할 실행 시간"과 "실제 받은 실행 시간"의 차이로 정의됩니다:

$$\text{Lag}_i(t) = U_i \cdot (t - t_0) - E_i(t)$$

### (1) 조기 블록과 부당 이득(Cheating) 취약점
만약 태스크가 남은 예산 $q_i > 0$을 가진 채 조기에 슬립(`BLOCK`)했을 때, 커널이 즉각 $U_{\text{act}} \leftarrow U_{\text{act}} - U_i$로 줄여버린다면:
- 태스크는 자신의 남은 예산 권리를 포기하지 않은 상태에서 활성 이용률만 낮추게 됩니다.
- 그 직후 다른 태스크들이 비정상적으로 부풀려진 유휴 대역폭을 과소모하게 되어, 추후 원래 태스크가 다시 깨어났을 때 순간적인 시스템 과부하($\sum U > 1.0$)로 인해 마감시간을 놓치는 참사가 발생합니다.

### (2) 0-Lag 시각 유도
태스크의 지연 $\text{Lag}_i(t)$가 정확히 0이 되는 미래의 절대 시각 $t_{\text{zero\_lag}}$는 다음과 같이 유도됩니다:

$$t_{\text{zero\_lag}} = d_i - \frac{q_i}{U_i}$$

- **동작 원리**: 태스크가 슬립하더라도 $t_{\text{zero\_lag}}$ 시각까지는 커널이 해당 태스크를 가상의 활성 상태(`INACTIVE_TIMER`)로 간주하여 $U_{\text{act}}$에 계속 포함시킵니다.
- 고해상도 타이머(hrtimer)가 $t_{\text{zero\_lag}}$ 시점에 만료될 때 비로소 $U_{\text{act}}$에서 $U_i$를 감산합니다.
- 이 완벽한 수학적 장치를 통해 GRUB은 어떠한 태스크의 불규칙한 슬립/웨이크업 패턴 하에서도 하드 실시간 결정론(Determinism)을 100% 사수합니다.
