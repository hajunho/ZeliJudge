# 문제 034: 액설로드의 협력의 진화와 반복 죄수의 딜레마(IPD) 시뮬레이터 (Axelrod's Evolution of Cooperation & Iterated Prisoner's Dilemma Engine)

## 문제 설명

토머스 홉스(Thomas Hobbes)는 『리바이어던』(*Leviathan*, 1651)에서 중앙 집권적 절대 권력이 없는 자연 상태(State of Nature)를 "만인에 대한 만인의 투쟁"이자 "외롭고, 가난하고, 험악하며, 잔인하고, 짧은 삶"으로 묘사했습니다. 현대 게임이론(Game Theory)은 이를 **죄수의 딜레마(Prisoner's Dilemma, PD)**로 정식화했습니다.

보수 행렬(Payoff Matrix)에서 협력($C$)과 배신($D$)의 보수가 다음 조건을 만족할 때:
$$T > R > P > S \quad \text{및} \quad 2R > T + S$$
- $T$ (Temptation to Defect): 일방적 배신 유혹 (예: 5점)
- $R$ (Reward for Mutual Cooperation): 상호 협력 보상 (예: 3점)
- $P$ (Punishment for Mutual Defection): 상호 배신 처벌 (예: 1점)
- $S$ (Sucker's Payoff): 호구의 보수 (일방적 협력 피해, 예: 0점)

단 1회의 게임에서 합리적 행위자의 우월 전략(Dominant Strategy)은 배신($D$)이며, 이는 양자 모두에게 열악한 $(P, P)$ 내시 균형으로 귀결됩니다.

그러나 국제정치학자 로버트 액설로드(Robert Axelrod)는 1984년 불후의 명저 『협력의 진화』(*The Evolution of Cooperation*)에서, **반복 죄수의 딜레마(Iterated Prisoner's Dilemma, IPD)** 환경에서는 중앙 정부나 사법 기구가 전혀 없는 무정부 상태에서도 행위자들 사이에 자발적인 상호 협력이 출현하고 진화적으로 안정화될 수 있음을 컴퓨터 토너먼트 실험을 통해 실증하였습니다.

이 토너먼트에서 아나톨 라포포트(Anatol Rapoport)가 제출한 가장 단순한 프로그램인 **팃포탯(Tit-for-Tat, TFT)**이 복잡한 확률적·기회주의적 전략들을 모두 꺾고 종합 우승을 차지했습니다. 액설로드는 승리하는 전략의 4대 핵심 덕목을 도출했습니다:
1. **신사성(Nice)**: 먼저 결코 배신하지 않음 (첫 라운드는 무조건 $C$).
2. **보복성(Retaliatory)**: 상대가 배신하면 즉시 다음 라운드에서 배신으로 응징.
3. **용서성(Forgiving)**: 상대가 다시 협력으로 돌아서면 즉각 과거를 잊고 협력 복귀.
4. **명확성(Clear & Non-Envious)**: 행동 패턴이 투명하여 예측 가능하며, 상대를 이기려 들지 않고 상호 이익을 극대화함.

더 나아가 존 메이나드 스미스(John Maynard Smith)의 **진화적 안정 전략(Evolutionary Stable Strategy, ESS)**과 **복제자 동역학(Replicator Dynamics)**을 적용하면, 각 세대(Generation)마다 높은 평균 적합도(보수)를 거둔 전략의 인구 비율($x_i$)이 증가하고 도태되는 진화적 동역학을 모델링할 수 있습니다:
$$x_i(t+1) = x_i(t) \cdot \frac{f_i(t)}{\bar{f}(t)}$$
(단, $f_i(t) = \sum_j x_j(t) M_{ij}$, $\bar{f}(t) = \sum_i x_i(t) f_i(t)$)

당신은 액설로드의 반복 죄수의 딜레마 토너먼트, 1대1 대결, 침입 분석(Invasion Analysis), 그리고 복제자 진화 동역학을 완전히 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 사전 정의 전략 집합 (Memory-1 Automata)

모든 전략은 직전 라운드 결과 $(a_{\text{self}}, a_{\text{opp}})$에 따라 다음 행동($C$ 또는 $D$)을 결정하는 기억 길이 1의 유한 오토마톤입니다:

| 전략명 | $p_0$ (첫 수) | $(C, C)$ 시 | $(C, D)$ 시 | $(D, C)$ 시 | $(D, D)$ 시 | 신사성 여부 (`is_nice`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `ALL_C` (무조건 협력) | $C$ | $C$ | $C$ | $C$ | $C$ | `true` |
| `ALL_D` (무조건 배신) | $D$ | $D$ | $D$ | $D$ | $D$ | `false` |
| `TIT_FOR_TAT` (팃포탯) | $C$ | $C$ | $D$ | $C$ | $D$ | `true` |
| `SUSPICIOUS_TFT` (의심 많은 팃포탯) | $D$ | $C$ | $D$ | $C$ | $D$ | `false` |
| `PAVLOV` (파블로프 / 성공-유지 실패-변경) | $C$ | $C$ | $D$ | $D$ | $C$ | `true` |
| `GRIM_TRIGGER` (냉혹한 방아쇠) | $C$ | $C$ | $D$ | $D$ | $D$ | `true` |

*(참고: `GRIM_TRIGGER`는 상대가 한 번이라도 배신하면 영구히 배신을 지속합니다.)*

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "payoff_matrix": [3, 5, 0, 1],
  "operations": [
    {
      "step": 1,
      "op": "MATCH",
      "strategy1": "TIT_FOR_TAT",
      "strategy2": "ALL_D",
      "rounds": 10
    },
    {
      "step": 2,
      "op": "TOURNAMENT",
      "strategies": ["ALL_C", "ALL_D", "TIT_FOR_TAT", "GRIM_TRIGGER", "PAVLOV"],
      "rounds": 20
    },
    {
      "step": 3,
      "op": "REPLICATOR_DYNAMICS",
      "initial_shares": {
        "ALL_C": 0.25,
        "ALL_D": 0.45,
        "TIT_FOR_TAT": 0.30
      },
      "generations": 15
    },
    {
      "step": 4,
      "op": "INVASION_ANALYSIS",
      "resident_strategy": "ALL_D",
      "invader_strategy": "TIT_FOR_TAT",
      "cluster_share": 0.05,
      "rounds": 20
    }
  ]
}
```

### 연산 종류
1. `MATCH`: 두 전략 간의 $N$라운드 대결을 실행하고 점수, 평균 보수, 상호 협력 비율, 대결 히스토리 문자열을 기록합니다.
2. `TOURNAMENT`: 주어진 전략 집합의 모든 쌍(자기 자신과의 대결 포함)에 대해 리그전을 수행하고, 평균 라운드 보수표($M_{ij}$), 총점, 순위, 신사적 전략의 지배 여부를 계산합니다.
3. `REPLICATOR_DYNAMICS`: 세대별 인구 분포 진화 과정을 시뮬레이션하고 최종 세대의 점유율, 생존 전략 및 지배 전략을 산출합니다. (점유율 $10^{-5}$ 미만은 0으로 처리, $1\%$ 초과 시 생존 간주)
4. `INVASION_ANALYSIS`: 기존 거주 전략 집단($1-\delta$)에 소규모 돌연변이 침입 집단($\delta$)이 유입되었을 때, 침입자의 적합도가 거주자보다 높아 집단을 침입할 수 있는지 판정합니다 ($f_{\text{invader}} > f_{\text{resident}}$).

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다. 모든 부동소수점 수치는 소수점 4자리로 반올림(`round(x, 4)`)합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "MATCH",
      "strategy1": "TIT_FOR_TAT",
      "strategy2": "ALL_D",
      "score1": 9,
      "score2": 14,
      "avg_payoff1": 0.9,
      "avg_payoff2": 1.4,
      "mutual_cooperation_rate": 0.0,
      "history1": "CDDDDDDDDD",
      "history2": "DDDDDDDDDD"
    }
  ]
}
```

---

## 제약 조건

- 라운드 수 $N$: $5 \le N \le 100$
- 세대 수 $G$: $1 \le G \le 50$
- 보수 행렬: $[R, T, S, P]$에서 $T > R > P > S$ 및 $2R > T + S$ 보장.
- 연산 수: $1 \le M \le 20$
