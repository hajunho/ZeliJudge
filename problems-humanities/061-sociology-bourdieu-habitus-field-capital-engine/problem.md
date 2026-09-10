# 피에르 부르디외: 구별짓기, 4대 자본과 아비투스·장(Field) 계급 재생산 엔진 (Pierre Bourdieu: Distinction, Habitus, Field & Capital Engine)

## 문제 설명

20세기 프랑스의 세계적인 사회학자 **피에르 부르디외(Pierre Bourdieu, 1930~2002)**는 현대 사회학의 최고 고전으로 꼽히는 저서 『구별짓기: 문화와 취향의 사회학적 비판』(*La Distinction: Critique sociale du jugement*, 1979)과 『실천감각』(*Le sens pratique*, 1980)을 통해, 계급 불평등이 어떻게 단순한 화폐 소득을 넘어 문화적 취향, 학력, 사회적 연망, 그리고 상징적 위세를 통해 세대 간에 영구히 재생산되는지를 규명했습니다.

부르디외 이론의 3대 핵심 기둥은 다음과 같습니다:

1. **4대 자본(Four Forms of Capital)**:
   - **경제 자본($K_{econ}$)**: 화폐, 부동산, 금융 자산 등 즉각 물질적 전환이 가능한 자본.
   - **문화 자본($K_{cult}$)**: 예술적 감식안, 고급 어휘 구사력(신체화), 학위 및 자격증(제도화), 고전문학·회화 소유(객관화).
   - **사회 자본($K_{soc}$)**: 명문대 동문회, 엘리트 사교 클럽, 인맥 네트워크의 크기와 질.
   - **상징 자본($K_{symb}$)**: 타인으로부터 인정받은 명예, 신용, 권위, 정당성(Legitimacy).

2. **장(Field, Champ)과 노모스(Nomos)**:
   - 사회는 단일한 전장이 아니라, 독자적인 게임의 규칙(Nomos)과 가치 척도를 가진 자율적 **장(예: 학술장, 현대미술장, 기업금융장, 정치장)**들로 분화되어 있습니다.
   - 각 장마다 중시하는 자본의 가중치($w_{econ}, w_{cult}, w_{soc}, w_{symb}$)가 다르며, 이에 따라 주체들의 장내 실질 권력($Power$)과 서열이 결정됩니다.

3. **아비투스(Habitus)와 상징 폭력(Symbolic Violence)**:
   - 주체는 성장 배경과 계급 조건 속에서 무의식적으로 내면화된 성향 체계인 **아비투스**를 형성합니다.
   - 지배 계급은 자신의 자의적인 문화적 취향(클래식 음악, 아방가르드 회화, 세련된 매너)을 '보편적이고 우월한 미적 가치'로 포장하여 피지배 계급에게 강요합니다.
   - 피지배 계급은 이 지배를 불평등한 사회적 강요가 아니라 '자신의 타고난 재능 부족'이나 '노력 부족'으로 착각하고 자발적으로 복종하는데, 부르디외는 이를 **오인(Méconnaissance)**에 기초한 **상징 폭력(Symbolic Violence)**이라 정의했습니다.

본 문제는 부르디외의 자본 벡터 공간, 장(Field)별 가중치 평가, 자본 구성 비율에 따른 계급 분파(Class Fraction) 분류, 상징 폭력 콘테스트 및 경제 자본의 문화 자본 전환을 정밀하게 모사하는 인문 사회학적 시뮬레이션 엔진을 구현하는 것입니다.

```
                  [ 4대 자본 벡터 (Capital Vector) ]
            (경제 자본, 문화 자본, 사회 자본, 상징 자본)
                                |
                                v
               [ 특정 장(Field) 진입 및 노모스 평가 ]
                   Power = ∑ (Weight_i * Capital_i)
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
   [ 자본 구성비 분석 ]                   [ 장내 위계 서열화 ]
   Ratio = K_cult / K_econ                - 최상위 34%: DOMINANT_CLASS
   - >= 1.25: 지식인 지배분파             - 중간층: PETITE_BOURGEOISIE
   - <= 0.80: 부르주아 지배분파           - 하위 33%: WORKING_CLASS
   - 그 외: 균형 분파
             |                                     |
             +------------------+------------------+
                                |
                                v
         [ 상징 폭력 콘테스트 (Symbolic Violence Contest) ]
          P_dominant >= P_subordinate * hegemony_ratio ?
                /                               \
            (성공)                             (실패)
              |                                  |
    상징 폭력 행사 관철                 대항 및 저항 (Parity)
    - 피지배자의 상징 자본 차감        - 자본 변동 없음
    - 지배자의 상징적 위세 증대        - CONTESTED_RESISTANCE
    - 오인 강화 (MECONNAISSANCE)
```

---

## 알고리즘 및 수학적 명세

### 1. 장내 권력 계산 (Field Power)
주체 $A$의 자본 벡터가 $\mathbf{K}_A = \{econ, cult, soc, symb\}$이고, 장 $F$의 가중치가 $\mathbf{w}_F = \{w_{econ}, w_{cult}, w_{soc}, w_{symb}\}$일 때, 장내 권력 $P_F(A)$는 다음과 같이 정의됩니다:
$$P_F(A) = \sum_{c \in \{econ, cult, soc, symb\}} w_{F, c} \cdot K_{A, c}$$
(모든 계산은 부동소수점 넷째 자리까지 반올림)

### 2. 상호작용(Interactions) 시계열 처리

#### 1) 자본 전환 (`CAPITAL_CONVERSION`)
주체 $A$가 자본 $from$을 자본 $to$로 전환할 때:
- 실지출액: $spent = \min(K_{A, from}, amount)$
- 원천 자본 차감: $K_{A, from} \leftarrow 	ext{round}(K_{A, from} - spent, 4)$
- 전환 획득액: $gained = 	ext{round}(spent 	imes 	ext{symbolic\_conversion\_rate}, 4)$
- 목표 자본 가산: $K_{A, to} \leftarrow 	ext{round}(K_{A, to} + gained, 4)$

#### 2) 상징 폭력 콘테스트 (`SYMBOLIC_VIOLENCE_CONTEST`)
참여자 $p_1, p_2$ 간의 대결에서:
- 장내 권력이 큰 쪽을 지배자 $dom$, 작은 쪽을 피지배자 $sub$로 정합니다 ($P_{dom} \ge P_{sub}$).
- 패권 지배 조건: $P_{dom} \ge P_{sub} 	imes 	ext{hegemony\_dominance\_ratio}$
  - **조건 충족 시 (Hegemony Achieved)**:
    - 지배자가 피지배자에게 문화적 자의성을 관철함.
    - 이전 상징 자본량: $transfer = 	ext{round}(\min(K_{sub, symb}, 10.0), 4)$
    - $K_{sub, symb} \leftarrow 	ext{round}(K_{sub, symb} - transfer, 4)$
    - $K_{dom, symb} \leftarrow 	ext{round}(K_{dom, symb} + transfer, 4)$
    - 결과 상태: `"MECONNAISSANCE_REINFORCED"` (오인 강화 및 복종 수용)
  - **조건 미충족 시 (Resistance)**:
    - 상징 자본 변동 없음 ($transfer = 0.0$).
    - 결과 상태: `"CONTESTED_RESISTANCE"` (상징적 헤게모니 미성립)

#### 3) 장 평가 (`FIELD_EVALUATION`)
지정된 참여자들의 장내 권력을 계산하고, 권력 내림차순으로 정렬한 `field_standings` 목록을 기록합니다.

### 3. 최종 계급 위치 및 분파 분석 (Final Agent Analysis)
시뮬레이션 종료 후, 기본(제1) 장(`fields[0]`)을 기준으로:
1. **자본 구성 비율 (Capital Composition Ratio)**:
   $$Ratio = 	ext{round}\left(rac{K_{cult}}{K_{econ} + 10^{-6}}, 4ight)$$
   - $Ratio \ge 1.25 \implies$ `"INTELLECTUAL_FRACTION"` (지식인/학자/예술가 지배분파)
   - $Ratio \le 0.80 \implies$ `"BOURGEOIS_FRACTION"` (상업/산업/금융 부르주아 지배분파)
   - 그 외 $\implies$ `"BALANCED_FRACTION"` (균형 분파)
2. **장내 계급 위치 (Field Class Position)**:
   모든 주체를 기본 장의 $Power$ 기준 내림차순 정렬 ($rank = 0, 1, \dots, N-1$):
   - $rank == 0$ 또는 백분위수 $rac{rank + 1}{N} \le 0.34 \implies$ `"DOMINANT_CLASS"` (지배 계급)
   - $rac{rank + 1}{N} \le 0.67 \implies$ `"PETITE_BOURGEOISIE"` (중간 계급 / 쁘띠 부르주아)
   - 그 외 $\implies$ `"WORKING_CLASS"` (민중 계급 / 노동 계급)

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "hegemony_dominance_ratio": 1.40,
    "symbolic_conversion_rate": 0.25
  },
  "fields": [
    {
      "field_id": "ACADEMIC_FIELD",
      "capital_weights": {
        "economic": 0.10,
        "cultural": 0.50,
        "social": 0.15,
        "symbolic": 0.25
      }
    }
  ],
  "agents": [
    {
      "agent_id": "PROF-01",
      "name": "Eminent Professor",
      "capitals": {
        "economic": 50.0,
        "cultural": 95.0,
        "social": 60.0,
        "symbolic": 90.0
      },
      "habitus_type": "academic_bourgeoisie"
    }
  ],
  "interactions": [
    {
      "field_id": "ACADEMIC_FIELD",
      "type": "CAPITAL_CONVERSION",
      "agent_id": "PROF-01",
      "from_capital": "economic",
      "to_capital": "cultural",
      "amount": 10.0
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "primary_field_id": "ACADEMIC_FIELD",
    "total_agents": 1,
    "dominant_class_count": 1,
    "total_interactions_processed": 1
  },
  "interaction_history": [
    {
      "interaction_index": 1,
      "field_id": "ACADEMIC_FIELD",
      "type": "CAPITAL_CONVERSION",
      "details": {
        "agent_id": "PROF-01",
        "from_capital": "economic",
        "to_capital": "cultural",
        "amount_converted": 10.0,
        "capital_gained": 2.5
      }
    }
  ],
  "agent_analysis": [
    {
      "agent_id": "PROF-01",
      "name": "Eminent Professor",
      "final_capitals": {
        "economic": 40.0,
        "cultural": 97.5,
        "social": 60.0,
        "symbolic": 90.0
      },
      "primary_field_power": 84.25,
      "capital_composition_ratio": 2.4375,
      "class_fraction": "INTELLECTUAL_FRACTION",
      "field_class_position": "DOMINANT_CLASS"
    }
  ]
}
```

---

## 제약 조건

- $1 \le 	ext{total\_agents} \le 100$
- $1 \le 	ext{interactions} \le 50$
- 모든 부동 소수점 수치는 소수점 넷째 자리까지 반올림(`round(v, 4)`)하여 기록합니다.
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
