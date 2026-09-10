# 문제 033: 롤스적 정의론과 사회후생함수 시뮬레이터 (Rawlsian Justice & Social Welfare Functions)

## 문제 설명

20세기 정치철학의 기념비적 저작인 존 롤스(John Rawls)의 『정의론』(*A Theory of Justice*, 1971)은 공리주의(Utilitarianism)가 지닌 "다수의 행복을 위해 소수의 기본적 권리와 후생을 희생시킬 수 있다"는 근본적 취약점을 비판하며 출발합니다. 롤스는 사회 구성원들이 자신의 타고난 재능, 계층, 성별, 부(富) 등을 전혀 알지 못하는 가상적 의사결정 상태인 **'무지의 베일(Veil of Ignorance)'**을 가정한 **'원초적 입장(Original Position)'**에서 정의의 원칙을 도출합니다.

이 조건에서 합리적이고 위험회피적인 개인들은 최악의 결과가 발생하는 상황을 방지하기 위해 최소 수혜자(Least Advantaged)의 처지를 극대화하는 **맥시민 원칙(Maximin Criterion)**과 **차등의 원칙(Difference Principle)**을 정의로운 분배의 원칙으로 선택하게 됩니다.

현대 후생경제학(Welfare Economics)에서는 사회적 분배 상태를 수학적으로 평가하기 위해 다양한 **사회후생함수(Social Welfare Function, SWF)**를 활용합니다:
1. **벤담 공리주의 후생함수(Bentham Utilitarian SWF)**:
   $$W_{\text{Bentham}} = \sum_{i=1}^n w_i \cdot u_i$$
   (단, $w_i$는 계층별 인구 가중치 비율, $\sum w_i = 1$)
   - 사회 전체의 총효용 극대화를 추구하며, 분배의 불평등 상태는 고려하지 않습니다.

2. **내시 사회후생함수(Nash Welfare SWF / Bernoulli-Nash Product)**:
   $$W_{\text{Nash}} = \prod_{i=1}^n u_i^{w_i} = \exp\left(\sum_{i=1}^n w_i \ln(u_i)\right)$$
   - 모든 계층의 효용 곱을 극대화하여 극단적인 불평등(효용 0)에 무한대의 페널티를 부과합니다.

3. **롤스 맥시민 후생함수(Rawlsian Maximin SWF)**:
   $$W_{\text{Rawls}} = \min_{i} (u_i)$$
   - 사회에서 가장 열악한 계층의 효용(바닥)을 극대화합니다.
   - 아마르티아 센(Amartya Sen)의 **렉시민 순서(Leximin Ordering)**: 최하위 효용이 동일한 경우, 오름차순으로 정렬된 효용 벡터를 사전식(Lexicographical)으로 비교하여 차상위 취약 계층의 후생을 비교합니다.

4. **센 형평성 후생함수(Sen Equity-Adjusted Welfare)**:
   $$W_{\text{Sen}} = \mu \cdot (1 - G)$$
   - 가중 평균 효용 $\mu$에 가중 지니계수(Gini Coefficient) $G$를 차감하여 소득 불평등을 조정한 실질 복지 지수입니다.

당신은 가상 국가의 정책 기획처 AI 시스템을 구축해야 합니다. 각 사회 계층의 가중치와 기준 효용, 그리고 제안된 정책들의 효용 변동분($\Delta u_i$)을 입력받아 각 후생 지표를 계산하고, 공리주의적 희생(Utilitarian Sacrifice) 여부 및 원초적 입장(무지의 베일) 하에서의 최적 정책을 도출하는 프로그램을 작성하십시오.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "strata": [
    {
      "name": "계층명 (str)",
      "weight": 0.5,
      "baseline_utility": 30.0
    }
  ],
  "operations": [
    {
      "step": 1,
      "op": "EVALUATE_POLICY",
      "policy_id": "P-01",
      "title": "정책명",
      "deltas": {
        "계층명": 5.0
      }
    },
    {
      "step": 2,
      "op": "COMPARE_AND_RANK",
      "policy_ids": ["P-01", "P-02"]
    }
  ]
}
```

- `strata`: 사회 계층 목록 (1개 이상). `weight`는 가중치(양수), `baseline_utility`는 초기 기준 효용.
  - 가중치 정규화: $w_i' = w_i / \sum w_j$
- `operations`: 순차적으로 실행할 연산 목록
  1. `EVALUATE_POLICY`: 특정 정책에 따른 각 계층의 최종 효용($u_i = \text{baseline} + \Delta$)과 각 사회후생함수 값을 평가합니다.
     - `deltas`에 명시되지 않은 계층의 효용 변동분은 0.0입니다.
     - 파레토 개선(`is_pareto_improvement`): 모든 계층의 효용이 감소하지 않고($\Delta_i \ge 0$), 최소 한 계층 이상 증가($\Delta_j > 0$)한 경우 `true`.
     - 롤스적 개선(`is_rawlsian_improvement`): 최하위 계층의 최종 효용이 기준 상태(baseline)의 최하위 계층 효용보다 높은 경우 `true`.
     - 취약층 희생(`worst_off_sacrificed`): 정책 후 최하위 계층 효용이 기준 상태의 최하위 계층 효용보다 감소한 경우 `true`.
  2. `COMPARE_AND_RANK`: 지정된 정책 목록을 각 기준(벤담, 내시, 롤스 렉시민, 센 형평)에 따라 순위를 매기고 승자를 판별합니다.
     - `veil_of_ignorance_choice`: 무지의 베일 하에서 롤스적 맥시민(렉시민) 1위 정책.
     - `utilitarian_rawlsian_conflict`: 벤담 1위와 롤스 1위가 상이한 경우 `true`.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 따르는 단일 줄 JSON 객체를 출력합니다. 모든 부동소수점 수치는 소수점 4자리로 반올림(`round(x, 4)`)합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "EVALUATE_POLICY",
      "policy_id": "P-BASE",
      "bentham": 46.0,
      "rawls_min": 30.0,
      "gini": 0.2391,
      "status": "EVALUATED"
    },
    {
      "step": 2,
      "op": "COMPARE_AND_RANK",
      "bentham_winner": "P-01",
      "rawls_winner": "P-02",
      "veil_of_ignorance_choice": "P-02",
      "utilitarian_rawlsian_conflict": true,
      "rankings": {
        "bentham": ["P-01", "P-02"],
        "nash": ["P-02", "P-01"],
        "rawls": ["P-02", "P-01"],
        "sen": ["P-02", "P-01"]
      }
    }
  ],
  "evaluated_policies": {
    "P-01": {
      "policy_id": "P-01",
      "title": "정책 제목",
      "final_utilities": {
        "working_class": 35.0,
        "middle_class": 60.0
      },
      "bentham_utilitarian": 51.5,
      "nash_welfare": 49.2,
      "rawls_maximin": 35.0,
      "least_advantaged_group": "working_class",
      "leximin_vector": [35.0, 60.0],
      "gini_coefficient": 0.21,
      "sen_equity_welfare": 40.685,
      "is_pareto_improvement": true,
      "is_rawlsian_improvement": true,
      "worst_off_sacrificed": false
    }
  }
}
```

---

## 제약 조건

- 계층 수 $N$: $2 \le N \le 20$
- 연산 수 $M$: $1 \le M \le 30$
- 각 계층의 가중치 $w_i > 0$
- 기준 효용 및 정책 후 최종 효용 $u_i \ge 0$ (내시 후생함수는 모든 $u_i > 0$일 때 $\exp(\sum w_i \ln u_i)$, 0 이하가 포함된 경우 $0.0$)
- 부동소수점 오차 방지를 위해 비교 시 epsilon $10^{-6}$을 사용하며 결과값은 `round(val, 4)`로 기록합니다.
- 지니계수 계산 공식 (가중 지니계수):
  $$G = \frac{\sum_{i=1}^n \sum_{j=1}^n w_i' w_j' |u_i - u_j|}{2 \mu}$$
  ($\mu = \sum_{i=1}^n w_i' u_i$, $\mu \le 10^{-9}$인 경우 $G = 0.0$)
