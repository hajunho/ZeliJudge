# 문제 #031: 100달러를 딸 때의 기쁨보다 잃을 때의 슬픔이 2배나 더 큰 이유?!: 행동경제학(Behavioral Economics): 대니얼 카너먼(Daniel Kahneman)과 아모스 트버스키(Amos Tversky)의 전망 이론(Prospect Theory), 손실 회피성(Loss Aversion), 확률 가중치(Probability Weighting) 및 심적 회계(Mental Accounting) 시뮬레이터

## 1. 개요 (Story & Context)
전통 고전 경제학(Classical Economics)과 신고전학파는 인간을 언제나 합리적으로 자신의 효용을 극대화하는 **‘호모 에코노미쿠스(Homo Economicus, 합리적 경제인)’**로 가정했습니다. 폰 노이만(John von Neumann)과 오스카 모르겐슈테른(Oskar Morgenstern)의 기대효용 이론(Expected Utility Theory, EUT)에 따르면, 인간은 최종적인 총 자산 상태($W = W_0 + x$)에 정의된 효용 함수 $U(W)$의 기댓값($\mathbb{E}[U(W)]$)을 계산하여 냉철하게 의사결정을 내려야 합니다.

그러나 현실의 인간은 전혀 그렇게 행동하지 않습니다:
1. **동전 던지기 도박의 거부 (Loss Aversion)**:
   - 앞면이 나오면 +150달러를 받고, 뒷면이 나오면 -100달러를 잃는 50:50 동전 던지기 게임이 있습니다.
   - 이 게임의 기댓값은 $+25$달러로 명백히 참여자에게 유리합니다.
   - 하지만 현실에서 거의 모든 사람들은 이 게임을 완강히 거부합니다! 왜일까요? **100달러를 잃었을 때 느끼는 심리적 고통이 150달러를 얻었을 때 느끼는 쾌감보다 훨씬 더 크기 때문**입니다.
2. **복권과 파멸적 보험의 역설 (Probability Weighting)**:
   - 사람들은 기대값이 극도로 마이너스인 복권(1등 당첨 확률 0.001%)을 기꺼이 구매하면서(위험 추구), 동시에 발생 확률이 0.001%인 화재·홍수 재해에 대비해 기댓값 손실보다 훨씬 비싼 보험료를 기꺼이 지불합니다(위험 회피).
   - 동일한 사람이 이익 영역에서는 위험을 추구하고, 손실 영역에서는 위험을 회피하는 극단적인 모순을 보입니다.
3. **아시아 질병 문제와 프레이밍 효과 (Framing Effect)**:
   - 600명의 목숨이 위태로운 전염병 상황에서:
     - **긍정 프레임 ("살릴 수 있다")**: A안(200명 무조건 살림) vs B안(1/3 확률로 600명 모두 살림, 2/3 확률로 0명 살림) $\to$ **72%가 확실한 A안 선택 (위험 회피)**!
     - **부정 프레임 ("죽는다")**: C안(400명 무조건 죽음) vs D안(1/3 확률로 아무도 안 죽음, 2/3 확률로 600명 모두 죽음) $\to$ **78%가 도박인 D안 선택 (위험 추구)**!
   - 객관적으로 A안과 C안(200명 생존, 400명 사망), B안과 D안은 완전히 동일한 사건임에도 불구하고, 단지 언어적 표현(프레임)을 바꾼 것만으로 대중의 선호가 180도 뒤집히는 선호 역전(Preference Reversal)이 일어납니다.

1979년 인지심리학자 **대니얼 카너먼(Daniel Kahneman)**과 **아모스 트버스키(Amos Tversky)**는 이러한 인간의 실제 심리와 인지 편향을 수학적으로 체계화한 **전망 이론(Prospect Theory)**을 발표하였고, 카너먼은 2002년 심리학자로서는 최초로 노벨 경제학상을 수상했습니다.

전망 이론의 3대 핵심 기둥은 다음과 같습니다:
1. **준거점 의존성 (Reference Point Dependence)**: 최종 자산 상태가 아니라, 현재 주관적 기준점($r_0$)으로부터의 **‘변화량(이익 $\Delta x \ge 0$ vs 손실 $\Delta x < 0$)’**에 반응합니다.
2. **S자형 가치 함수 (S-shaped Value Function $v(x)$)**:
   - 이익 영역($x \ge 0$)에서는 오목(Concave, $v''(x) < 0$)하여 **위험 회피(Risk Aversion)**를 유발합니다.
   - 손실 영역($x < 0$)에서는 볼록(Convex, $v''(x) > 0$)하여 **위험 추구(Risk Seeking)**를 유발합니다.
   - 원점에서 손실 영역의 기울기가 이익 영역보다 약 2~2.5배 가파릅니다 (손실 회피 계수 $\lambda \approx 2.25$).
3. **비선형 확률 가중치 함수 (Probability Weighting Function $w(p)$)**:
   - 사람들은 객관적 확률 $p$를 그대로 느끼지 않고, 극히 희박한 확률($p \ll 0.1$)은 과대평가(Overweighting)하고, 중간 및 높은 확률($p > 0.3$)은 과소평가(Underweighting)합니다.

나아가 2017년 노벨 경제학상 수상자 **리처드 탈러(Richard Thaler)**는 이를 확장하여, 사람들이 마음속에 별도의 심리적 장부를 두고 돈을 관리한다는 **심적 회계(Mental Accounting)**와 **쾌락적 편집(Hedonic Editing)** 원리를 정립했습니다.

여러분은 행동경제학 및 핀테크 알고리즘 연구원으로서, 카너먼-트버스키의 누적 전망 이론과 탈러의 심적 회계를 완벽히 전산화하여 금융 상품과 소비자 선택을 분석하는 **Behavioral Prospect Theory Engine**을 구현해야 합니다!

---

## 2. 상태 머신 및 수학 공식

### 2.1 카너먼-트버스키 가치 함수 (Value Function $v(x)$)
준거점 대비 순이익/손실 $x$에 대해:
$$v(x) = \begin{cases} x^\alpha & \text{if } x \ge 0 \\ -\lambda (-x)^\beta & \text{if } x < 0 \end{cases}$$
- 기본 매개변수: $\alpha = 0.88$, $\beta = 0.88$, $\lambda = 2.25$ (손실 회피 계수).

### 2.2 비선형 확률 가중치 함수 (Tversky-Kahneman Weighting $w(p)$)
객관적 발생 확률 $p \in [0, 1]$에 대해:
- 이익 영역 가중치:
  $$w^+(p) = \frac{p^\gamma}{\left(p^\gamma + (1-p)^\gamma\right)^{1/\gamma}} \quad (\text{기본값 } \gamma = 0.61)$$
- 손실 영역 가중치:
  $$w^-(p) = \frac{p^\delta}{\left(p^\delta + (1-p)^\delta\right)^{1/\delta}} \quad (\text{기본값 } \delta = 0.69)$$
- $p=0$이면 $w(p)=0$, $p=1$이면 $w(p)=1$.

### 2.3 전망 가치(Prospect Value $V$) 및 기댓값($EV$)
준거점 $r_0$에 대해 결과 목록 $\{(x_i, p_i)\}$가 주어질 때:
- 객관적 기댓값: $EV = \sum_{i} p_i x_i$
- 주관적 전망 가치:
  $$V = \sum_{i} w(p_i) v(x_i - r_0)$$
  여기서 $x_i - r_0 > 10^{-9}$이면 $w^+(p_i)$, $x_i - r_0 < -10^{-9}$이면 $w^-(p_i)$, $x_i - r_0 = 0$이면 $v=0, w=p_i$.
- 위험 태도(Risk Attitude):
  - 모든 0이 아닌 $\Delta x_i > 0$일 때: $V < v(EV - r_0) - 10^{-4}$이면 `"RISK_AVERSE"`, $V > v(EV - r_0) + 10^{-4}$이면 `"RISK_SEEKING"`, 그 외 `"RISK_NEUTRAL"`.
  - 모든 0이 아닌 $\Delta x_i < 0$일 때: $V > v(EV - r_0) + 10^{-4}$이면 `"RISK_SEEKING"`, $V < v(EV - r_0) - 10^{-4}$이면 `"RISK_AVERSE"`, 그 외 `"RISK_NEUTRAL"`.
  - 이익과 손실이 혼합된 경우: `"MIXED"`.

### 2.4 의사결정 비교 및 행동 이상 현상 (`COMPARE_GAMBLES`)
두 대안 Option A와 Option B에 대해:
- 기댓값 선택 `ev_choice`: $EV_A > EV_B + 10^{-4}$이면 `"OPTION_A"`, $EV_B > EV_A + 10^{-4}$이면 `"OPTION_B"`, 그 외 `"INDIFFERENT"`.
- 전망 이론 선택 `prospect_choice`: $V_A > V_B + 10^{-4}$이면 `"OPTION_A"`, $V_B > V_A + 10^{-4}$이면 `"OPTION_B"`, 그 외 `"INDIFFERENT"`.
- 행동 이상 현상 감지 (`anomaly`: `ev_choice != prospect_choice`):
  - `CERTAINTY_EFFECT`: 합리적 $EV$는 B를 선호하나, 인간 $V$는 확실한 단일 이익($p=1.0$)인 A를 선호하는 경우.
  - `LOSS_AVERSION_REJECTION`: 합리적 $EV$는 양(+)인 B를 선호하나, 손실이 섞여 있어 인간 $V$가 무행동(A)을 선호하는 경우.
  - `LOTTERY_EFFECT`: 합리적 $EV$는 안전한 A를 선호하나, 극소 확률($p \le 0.05$) 대박이 포함된 B를 인간 $V$가 선호하는 경우.
  - `INSURANCE_EFFECT`: 합리적 $EV$는 재해를 감수하는 B를 선호하나, 극소 확률 재난을 피하기 위해 확실한 손실(보험료 A)을 인간 $V$가 선호하는 경우.
  - 기타 불일치: `"BEHAVIORAL_ANOMALY"`.
  - 이상 현상 없음: `"NONE"`.

### 2.5 탈러의 쾌락적 편집 원리 (`HEDONIC_EDITING`)
여러 재무적 사건 $\{x_1, x_2, \dots\}$이 발생했을 때:
- 분리 가치: $V_{\text{seg}} = \sum v(x_i)$
- 통합 가치: $V_{\text{int}} = v(\sum x_i)$
- 최적 전략 `optimal_strategy`:
  - $V_{\text{seg}} > V_{\text{int}} + 10^{-4}$이면 `"SEGREGATE"` (따로따로 제시)
  - $V_{\text{int}} > V_{\text{seg}} + 10^{-4}$이면 `"INTEGRATE"` (합쳐서 일괄 제시)
  - 그 외 `"INDIFFERENT"`
- 쾌락적 규칙 분류 `hedonic_rule`:
  - 모든 사건이 양수: `"SEGREGATE_MULTIPLE_GAINS"` (좋은 소식은 쪼개서 기쁨을 배가)
  - 모든 사건이 음수: `"INTEGRATE_MULTIPLE_LOSSES"` (나쁜 소식은 한 번에 털어서 고통을 축소)
  - 혼합 사건이며 순결과 $> 0$: `"INTEGRATE_MIXED_GAIN"` (작은 손실을 큰 이익으로 상쇄)
  - 혼합 사건이며 순결과 $< 0$:
    - `optimal_strategy == "SEGREGATE"`이면 `"SILVER_LINING"` (먹구름 속 은빛 한 줄기 희망: 거대한 손실 속 작은 환급/보너스를 따로 떼어 위안 제공)
    - 그 외 `"INTEGRATE_MIXED_LOSS"`

---

## 3. 입력 형식 (Input Specification)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "parameters": {
    "alpha": 0.88,
    "beta": 0.88,
    "lambda": 2.25,
    "gamma": 0.61,
    "delta": 0.69
  },
  "operations": [
    {
      "id": "certainty_test",
      "op": "COMPARE_GAMBLES",
      "reference_point": 0.0,
      "option_a": [{"x": 2400.0, "p": 1.0}],
      "option_b": [{"x": 10000.0, "p": 0.25}, {"x": 0.0, "p": 0.75}]
    }
  ]
}
```

---

## 4. 출력 형식 (Output Specification)
표준 출력(stdout)으로 처리 결과를 담은 JSON 객체를 한 줄로 출력합니다:
```json
{
  "results": [
    {
      "id": "certainty_test",
      "op": "COMPARE_GAMBLES",
      "option_a_ev": 2400.0,
      "option_a_prospect_value": 929.8058,
      "option_b_ev": 2500.0,
      "option_b_prospect_value": 863.0232,
      "ev_choice": "OPTION_B",
      "prospect_choice": "OPTION_A",
      "anomaly": true,
      "anomaly_type": "CERTAINTY_EFFECT"
    }
  ]
}
```
모든 수치(EV, Prospect Value, Segregated/Integrated Value 등)는 소수점 4자리까지 반올림(`round(val, 4)`)합니다.
