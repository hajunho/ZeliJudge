# #127 - 존 롤스의 정의론: 원초적 입장, 무지의 베일, 최소극대화(Maximin) 규칙 및 차등의 원칙 분배 정의 엔진

## 📖 문제 배경과 역사적 맥락

> *"사상 체계의 제1덕목이 진리이듯이, 사회 제도의 제1덕목은 정의(Justice)이다. 아무리 정교하고 경제적으로 효율적인 법이나 제도라 할지라도, 그것이 정의롭지 못하다면 반드시 개정되거나 폐기되어야 한다. 각 개인은 정의에 입각한 불가침성(Inviolability)을 지니고 있으며, 사회 전체의 복지라는 명분으로도 이를 유린할 수 없다."*  
> — **존 롤스 (John Rawls, 1921–2002), 『정의론』(A Theory of Justice, 1971)**

20세기 서양 정치철학과 규범윤리학은 "최대 다수의 최대 행복"을 절대 기준으로 삼는 **공리주의(Utilitarianism)**가 지배하고 있었습니다. 그러나 공리주의는 사회 전체의 총효용을 증대시키기 위해 소수자나 취약 계층의 자유와 인권을 희생시키는 것을 이론적으로 용인하는 치명적인 결함을 안고 있었습니다.

미국의 철학자 **존 롤스(John Rawls)**는 1971년 출간한 불후의 고전 **『정의론(A Theory of Justice)』**을 통해 칸트의 의무론적 전통과 사회계약설을 현대적으로 부활시켰습니다. 그는 사회 구성원 모두가 동의할 수 있는 가장 공정한 정의의 원칙을 도출하기 위해, 가상의 사고실험인 **"원초적 입장(Original Position)"**과 **"무지의 베일(Veil of Ignorance)"**을 고안했습니다.

```
       ┌────────────────────────────────────────────────────────┐
       │             존 롤스 『정의론』의 3단계 사전체계적 원칙          │
       └────────────────────────────────────────────────────────┘
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │ 제1원칙: 평등한 기본적 자유의 원칙 (Equal Basic Liberties) │
       │  - 양심, 신체, 정치, 결사의 자유는 경제적 효율성이나   │
       │    사회 전체의 총합 복리를 위해 결코 침해될 수 없다    │
       └────────────────────────────┬───────────────────────────┘
                                    │ (Lexical Priority 1)
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │ 제2원칙 (A): 공정한 기회 균등의 원칙 (Fair Opportunity)   │
       │  - 모든 사회적 직위와 공직은 출신 배경에 무관하게 실질   │
       │    적으로 모든 사람에게 공정하게 개방되어야 한다       │
       └────────────────────────────┬───────────────────────────┘
                                    │ (Lexical Priority 2a)
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │ 제2원칙 (B): 차등의 원칙 (Difference Principle / Maximin)│
       │  - 사회적·경제적 불평등은 사회의 "최소 수혜자"에게       │
       │    최대의 이익(Maximin)이 돌아갈 때에만 정당화된다     │
       └────────────────────────────────────────────────────────┘
```

### 롤스 정의론의 핵심 메커니즘
1. **무지의 베일(Veil of Ignorance)**:
   - 계약 당사자들은 자신의 계급, 인종, 성별, 지능, 체력, 자산, 심지어 자신이 속한 세대조차 알지 못하는 순수한 무지의 상태에서 사회의 기본 규칙을 합의합니다.
2. **최소극대화(Maximin) 규칙**:
   - 무지의 베일이 걷혔을 때 자신이 사회에서 가장 불리한 '최소 수혜자(The Least Advantaged, $T_1$)'가 될 가능성을 고려하여, 최악의 상황에서의 몫을 극대화하는 분배 방식을 선택합니다.
3. **사전체계적 우선성(Lexical Priority)**:
   - 제1원칙(기본적 자유)은 제2원칙(사회경제적 분배)에 절대적으로 우선합니다. 돈을 더 많이 준다고 해서 노예제나 참정권 박탈을 정당화할 수 없습니다.
   - 제2원칙 내부에서도 기회 균등의 원칙(2a)이 차등의 원칙(2b)에 우선합니다.
4. **공리주의 대 롤스주의 대결**:
   - 총생산이 극대화되지만 하위 20%가 빈곤에 시달리는 사회(공리주의 모델)는, 총생산은 상대적으로 적더라도 하위 20%의 절대적 복지가 가장 높은 사회(롤스주의 모델)보다 열등합니다.

본 과제에서는 롤스의 3단계 사전체계적 원칙과 무지의 베일 속 분배 평가를 시뮬레이션하는 계산 정의론 엔진을 구현합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "basic_liberty_threshold": 80.0,
    "liberty_inequality_tolerance": 5.0,
    "min_opportunity_threshold": 70.0
  },
  "initial_state": {
    "strata": [
      {"name": "T1_least_advantaged", "wealth": 20.0, "liberty": 85.0, "opportunity": 68.0},
      {"name": "T2_working_class", "wealth": 40.0, "liberty": 85.0, "opportunity": 72.0},
      {"name": "T3_middle_class", "wealth": 70.0, "liberty": 85.0, "opportunity": 80.0},
      {"name": "T4_upper_middle", "wealth": 120.0, "liberty": 85.0, "opportunity": 88.0},
      {"name": "T5_top_bracket", "wealth": 250.0, "liberty": 85.0, "opportunity": 95.0}
    ]
  },
  "events": [
    {
      "type": "PUBLIC_EDUCATION_INVESTMENT",
      "params": {
        "amount": 20.0
      }
    },
    {
      "type": "TAX_AND_REDISTRIBUTE",
      "params": {
        "tax_rate_top": 0.25,
        "deadweight_loss": 0.05
      }
    },
    {
      "type": "BASIC_INCOME_DIVIDEND",
      "params": {
        "amount_per_capita": 10.0
      }
    },
    {
      "type": "SELECT_DISTRIBUTION_SCHEME",
      "params": {
        "candidates": [
          {
            "scheme_name": "Scheme_A_Utilitarian",
            "strata_wealth": [10.0, 30.0, 90.0, 250.0, 900.0],
            "min_liberty": 85.0,
            "min_opportunity": 75.0
          },
          {
            "scheme_name": "Scheme_B_Rawlsian",
            "strata_wealth": [50.0, 70.0, 90.0, 140.0, 220.0],
            "min_liberty": 85.0,
            "min_opportunity": 75.0
          }
        ]
      }
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `config`:
   - `basic_liberty_threshold`: 제1원칙 평등한 기본적 자유 최소 보장 점수 ($[0, 100]$, 기본값 `80.0`).
   - `liberty_inequality_tolerance`: 계층 간 자유 점수의 최대 허용 격차 ($[0, 20]$, 기본값 `5.0`).
   - `min_opportunity_threshold`: 제2원칙(A) 공정한 기회 균등 최소 보장 점수 ($[0, 100]$, 기본값 `70.0`).
2. `initial_state`:
   - `strata`: 5대 사회 계층 배열 (`T1_least_advantaged`, `T2_working_class`, `T3_middle_class`, `T4_upper_middle`, `T5_top_bracket`).
   - 각 계층은 `name`, `wealth`, `liberty`, `opportunity` 속성을 가집니다.
3. `events`: 다음 5가지 정책 및 평가 사건이 발생합니다:
   - `TAX_AND_REDISTRIBUTE`:
     - 상위 계층(`T4`, `T5`)의 `wealth`에 `tax_rate_top` 세율을 적용하여 세수 징수.
     - 순 이전액 $\text{net\_transfer} = \text{tax\_collected} \times (1.0 - \text{deadweight\_loss})$.
     - 이전액 분배: $70\%$를 $T_1$에게, $30\%$를 $T_2$에게 지급.
   - `PUBLIC_EDUCATION_INVESTMENT`:
     - $T_1$의 `opportunity`에 $+ \text{amount} \times 0.5$, `wealth`에 $+ \text{amount} \times 0.3$.
     - $T_2$의 `opportunity`에 $+ \text{amount} \times 0.3$, `wealth`에 $+ \text{amount} \times 0.2$. (단, `opportunity`는 최대 $100.0$).
   - `DEREGULATION_GROWTH`:
     - $T_5$의 `wealth`에 $+ \text{growth\_top}$, $T_4$의 `wealth`에 $+ \text{growth\_top} \times 0.5$.
     - $T_1$의 `wealth`에 $+ \text{growth\_bottom}$, $T_1$의 `liberty`에 $- \text{liberty\_cost\_bottom}$.
   - `BASIC_INCOME_DIVIDEND`:
     - 5개 모든 계층의 `wealth`에 $\text{amount\_per\_capita}$ 균등 추가.
   - `SELECT_DISTRIBUTION_SCHEME`:
     - 후보 분배 모델 중 롤스적 최소극대화(Maximin) 승자와 공리주의(Utilitarian) 승자 판별:
       - 롤스 선택: $\text{min\_liberty} \ge \text{basic\_liberty\_threshold} \land \text{min\_opportunity} \ge \text{min\_opportunity\_threshold}$를 만족하는 후보 중 $T_1$의 부가 가장 높은 후보.
       - 공리주의 선택: 5개 계층 부의 총합($\sum \text{wealth}$)이 가장 높은 후보.

### 4. 정의 사회 판정 로직:
매 사건 처리 후 계층 상태를 평가합니다:
1. $\min(\text{liberty}) < \text{basic\_liberty\_threshold}$ 또는 $\max(\text{liberty}) - \min(\text{liberty}) > \text{liberty\_inequality\_tolerance} \implies$ `"UNJUST_LIBERTY_VIOLATION"`
2. $\min(\text{opportunity}) < \text{min\_opportunity\_threshold} \implies$ `"UNJUST_OPPORTUNITY_DEFICIT"`
3. $T_1 \ge 35.0 \implies$ `"JUST_WELL_ORDERED_SOCIETY"` (질서정연한 정의사회)
4. $T_1 \ge 25.0 \implies$ `"MODERATELY_JUST"` (온건한 정의사회)
5. 기타 $\implies$ `"INSUFFICIENT_MAXIMIN_TRANSFER"` (최소 수혜자 배려 부족)

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 사회 상태를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 표준 출력에 인쇄합니다:

```json
{
  "final_justice_status": "JUST_WELL_ORDERED_SOCIETY",
  "is_just_society": true,
  "final_t1_wealth": 97.51,
  "final_total_wealth": 555.38,
  "strata_final": [
    {
      "name": "T1_least_advantaged",
      "wealth": 97.51,
      "liberty": 85.0,
      "opportunity": 78.0
    }
  ],
  "history": [
    {
      "epoch": 1,
      "event": "PUBLIC_EDUCATION_INVESTMENT",
      "status": "OPPORTUNITY_ENHANCED",
      "t1_wealth": 26.0,
      "total_wealth": 510.0,
      "min_liberty": 85.0,
      "min_opportunity": 78.0,
      "justice_status": "MODERATELY_JUST",
      "detail": "Education investment increased T1 opportunity to 78.0"
    }
  ]
}
```

*참고*: 모든 부동소수점 수치는 `round(val, 2)`를 적용합니다.

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 정의 상태 플래그가 완벽히 일치해야 합니다.
2. 롤스의 3단계 사전체계적 우선성(제1원칙 기본적 자유 $\to$ 제2원칙A 기회 균등 $\to$ 제2원칙B 차등의 원칙) 판정 순서를 엄수해야 합니다.
3. Windows 환경에서의 UTF-8 입출력을 준수해야 합니다.
