# 문제 035: 호텔링의 공간 입지 경쟁과 다운스의 중위투표자 정리 시뮬레이터 (Hotelling's Spatial Competition & Downsian Median Voter Theorem)

## 문제 설명

왜 도로변의 주유소들과 패스트푸드점들은 널찍이 떨어져서 고객을 분산 흡수하는 대신, 바로 길 건너편에 다닥다닥 붙어서 개점할까요? 왜 선거철이 되면 당내 경선에서 극단적 구호를 외치던 거대 정당의 대선 후보들이 본선에 진출하자마자 일제히 '중도 실용'을 표방하며 서로 구별하기 힘들 정도로 유사한 공약을 내놓을까요?

이 현상을 수학적으로 설명한 것이 수리경제학자 해럴드 호텔링(Harold Hotelling)의 1929년 기념비적 논문 「경쟁의 안정성」(*Stability in Competition*)에서 제시된 **호텔링의 선형 도시 모델(Hotelling's Linear City Model)**과 **최소 차별화의 원칙(Principle of Minimum Differentiation)**입니다. 이후 정치학자 앤서니 다운스(Anthony Downs)는 1957년 명저 『민주주의의 경제학적 이론』(*An Economic Theory of Democracy*)에서 이를 1차원 이념 스펙트럼($[0, 100]$) 상의 유권자 투표 행태로 확장하여 **중위투표자 정리(Median Voter Theorem, MVT)**를 정립하였습니다.

### 핵심 이론 원리
1. **단일 차원 공간과 유권자 분포**:
   - 사회 구성원들은 이념 축 $[0, 100]$ (0: 극좌/진보, 50: 중도, 100: 극우/보수) 상에 위치합니다.
   - 각 위치 $x$의 유권자들은 가중치 $w_x$를 가집니다.
   - 누적 투표자 수가 전체의 절반($50\%$)에 도달하는 지점이 **중위투표자(Median Voter)의 위치**입니다.
2. **단봉 선호와 근접성 투표 (Proximity Voting)**:
   - 유권자는 자신과 가장 가까운 위치($|x_{\text{voter}} - x_{\text{cand}}|$)에 입지한 후보에게 투표합니다.
   - 두 후보 간 거리가 동일할 경우 표는 균등하게 분할(Split)됩니다.
3. **유권자 소외와 기권 (Voter Alienation & Abstention)**:
   - 후보들이 지나치게 중도로 쏠릴 경우, 이념적 거리가 한계치(`alienation_threshold`, $\delta_{\max}$)를 초과하는 극단 성향의 유권자들은 자신을 대변할 후보가 없다고 느껴 기권(투표 포기)합니다.
4. **최적 입지 및 내시 균형 (Nash Equilibrium)**:
   - 양당제 단순다수대표제(First-Past-The-Post)에서 두 후보는 상대 후보의 위치에 대응하여 자신의 득표수를 극대화하는 **최적 대응 위치(Best Response Position)**로 이동합니다.
   - 유권자 소외가 없을 때, 두 후보는 서로를 향해 계속 이동하여 결국 **중위투표자 위치($x = x_{\text{med}}$)에 수렴하는 유일한 내시 균형**에 도달합니다.
5. **제3당 출마와 스포일러 효과 (Duverger's Law)**:
   - 양당이 중도로 수렴하거나 양극단에 배치되어 있을 때, 제3의 중도 또는 독자 후보가 출마하면 표가 분산되어 기존 선거 판세가 역전되는 현상이 발생합니다.

당신은 선거 전략 컨설팅 및 공간 입지 분석을 위한 호텔링-다운스 공간 경쟁 시뮬레이션 엔진을 구현해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "voters": [
    {"x": 20, "weight": 30.0},
    {"x": 50, "weight": 40.0},
    {"x": 80, "weight": 30.0}
  ],
  "alienation_threshold": 25.0,
  "initial_candidates": {
    "Party_A": 30,
    "Party_B": 70
  },
  "operations": [
    {
      "step": 1,
      "op": "COMPUTE_MEDIAN"
    },
    {
      "step": 2,
      "op": "EVALUATE_ELECTION"
    },
    {
      "step": 3,
      "op": "OPTIMIZE_POSITION",
      "candidate": "Party_A",
      "grid_min": 0,
      "grid_max": 100,
      "grid_step": 1
    },
    {
      "step": 4,
      "op": "SIMULATE_CAMPAIGN",
      "rounds": 2,
      "turn_order": ["Party_A", "Party_B"],
      "grid_min": 0,
      "grid_max": 100,
      "grid_step": 1
    }
  ]
}
```

- `voters`: 유권자 분포 목록 (`x`: 0~100 사이의 위치, `weight`: 해당 위치의 유권자 수/가중치).
- `alienation_threshold`: (선택) 유권자 소외 거리 한계. 가장 가까운 후보와의 거리가 이 값을 초과하면 기권합니다. 생략 시 null (기권 없음).
- `initial_candidates`: 후보자/정당별 초기 위치 딕셔너리.
- `operations`: 실행할 연산 목록
  1. `COMPUTE_MEDIAN`: 전체 유권자의 중앙값(중위투표자 위치)을 계산합니다.
  2. `EVALUATE_ELECTION`: 현재 후보자 위치를 기준으로 각 후보의 득표수, 득표율, 기권율, 승리자 및 승리 표차(Margin of Victory)를 산출합니다.
  3. `OPTIMIZE_POSITION`: 특정 후보(`candidate`)가 다른 후보들의 위치가 고정되어 있을 때, 득표수를 극대화하는 최적 입지 위치를 격자 탐색으로 찾아 이동합니다.
  4. `SIMULATE_CAMPAIGN`: 후보들이 `turn_order` 순서대로 번갈아 가며 최적 대응 위치로 이동하는 선거 운동 과정을 `rounds` 라운드 동안 시뮬레이션합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다. 모든 부동소수점 수치는 소수점 둘째 자리까지 반올림(`round(x, 2)`)합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "COMPUTE_MEDIAN",
      "median_voter_position": 50
    },
    {
      "step": 2,
      "op": "EVALUATE_ELECTION",
      "candidate_positions": {"Party_A": 30, "Party_B": 70},
      "raw_votes": {"Party_A": 30.0, "Party_B": 30.0},
      "vote_percentages": {"Party_A": 30.0, "Party_B": 30.0},
      "abstention_votes": 40.0,
      "abstention_pct": 40.0,
      "winner": "TIE",
      "margin_of_victory": 0.0,
      "is_tie": true
    }
  ],
  "final_candidates": {
    "Party_A": 50,
    "Party_B": 50
  }
}
```

---

## 제약 조건

- 유권자 지점 수: $1 \le K \le 101$
- 후보자 수: $2 \le C \le 5$
- 위치 $x$: $0 \le x \le 100$
- 연산 수: $1 \le M \le 20$
- 동률(Tie) 발생 시 해당 유권자 표는 근접 후보들에게 균등 분할됩니다.
