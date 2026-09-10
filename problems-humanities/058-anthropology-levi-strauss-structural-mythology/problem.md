# 문제 058: 클로드 레비스트로스의 구조인류학: 신소(Mytheme) 2원 대립 분석 및 신화의 카논 변형 공식(Canonical Formula) 엔진 (Claude Lévi-Strauss's Structural Mythology Engine)

## 문제 배경
20세기 구조주의(Structuralism)의 거장이자 문화인류학자인 **클로드 레비스트로스(Claude Lévi-Strauss, 1908~2009)**는 『슬픈 열대』(1955), 『구조인류학』(1958), 그리고 4부작 대작 『신화학(Mythologiques)』(1964~1971)을 통해 전 세계 수천 개 원주민 신화의 이면에 인간 정신의 보편적 무의식 구조가 관통하고 있음을 입증했습니다.

레비스트로스의 신화 분석 방법론은 다음의 4대 원리로 요약됩니다:
1. **신소 (Mytheme, 신화의 최소 구성 단위)**:
   - 언어가 음소(Phoneme)와 형태소(Morpheme)의 결합이듯, 신화는 하나의 고유한 관계 사건을 나타내는 최소 서사 단위인 '신소'들로 분해됩니다.
2. **2원 대립 (Binary Opposition)**:
   - 신화의 기본 축은 인간이 현실에서 겪는 근원적 실존 모순(자연 대 문화, 날것 대 익힌 것 Raw/Cooked, 생명 대 죽음, 천상 대 지하)을 양극 대립 쌍으로 정식화합니다.
3. **매개 (Mediation)**:
   - 모순되는 두 대립항의 타는 듯한 긴장을 완화하기 위해, 신화는 양쪽의 성질을 모두 갖는 중간 매개체(Mediator, 예: 날것과 썩은 고기 사이의 '익힌 고기', 수렵동물과 초식동물 사이에서 썩은 고기를 먹는 '코요테/까마귀', 인간과 신 사이의 '트릭스터')를 도입합니다.
4. **신화의 카논 변형 공식 (Canonical Formula of Myth)**:
   - 레비스트로스가 1955년에 제시한 신화 변형의 대수학 공식:
     $$F_x(a) : F_y(b) \simeq F_x(b) : F_{a^{-1}}(y)$$
   - "기능 $x$를 수행하는 주체 $a$와 기능 $y$를 수행하는 주체 $b$의 관계는, 기능 $x$를 수행하는 주체 $b$와 역전된 주체 $a^{-1}$에 의해 수행되는 기능 $y$의 관계와 구조적으로 동형(Homologous)이다."
   - 예: 아마존 보로로족 신화(불을 가진 재규어 $a$와 날고기를 먹는 인간 $b$)가 이웃 제족 신화(불을 쟁취한 인간 $b$와 날고기 포식자로 전락한 재규어 $a^{-1}$)로 전이되는 구조적 변형 법칙.

본 문제에서는 신화 서사를 신소로 분해하고, 2원 대립 축에 따른 구조적 프로필(평균값, 긴장도, 매개체)을 도출하며, 카논 변형 공식에 입각한 이종 문화 간 신화 변이형의 구조적 동형성(Isomorphism)을 검증하는 **레비스트로스 구조인류학 엔진**을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. 2원 대립 축 및 신소 프로파일링
- 각 2원 대립 축(`binary_axes`)은 고유 ID `axis_id`, 음극(`pole_negative`, -1.0)과 양극(`pole_positive`, +1.0)을 가집니다.
- 신소(`mythemes`)는 주체(`term`), 수행 기능(`function`), 각 축에 대한 정규화 점수 `axis_values`($-1.0 \le v \le +1.0$)를 가집니다.
- 각 신화(`myths`)에 대해:
  - 각 축별 **평균값(`mean`)**과 **긴장도(`tension` = $\max(v) - \min(v)$)**를 계산합니다 (소수점 4자리 반올림).
  - **매개체 (Mediators)** 탐지: 신화에 포함된 신소 중, 모든 활성 축의 절대값이 $0.25$ 이하($|v| \le 0.25$)인 신소를 매개체로 식별합니다.

### 2. 신화의 카논 변형 공식 검증 (Canonical Inquiry)
신화 $M_1$(Source)과 신화 $M_2$(Target), 그리고 매핑 $(a, b, x, y)$에 대해:
- 공식: $F_x(a) : F_y(b) \simeq F_x(b) : F_{a^{-1}}(y)$
- 검증 조건:
  1. $M_1$에 $\text{term} == a$ 이고 $\text{function} == x$ 인 신소가 존재하는가?
  2. $M_1$에 $\text{term} == b$ 이고 $\text{function} == y$ 인 신소가 존재하는가?
  3. $M_2$에 $\text{term} == b$ 이고 $\text{function} == x$ 인 신소가 존재하는가?
  4. $M_2$에 ($\text{term} == \text{"\{a\}\_inv"}$ 또는 $\text{term\_inverted} == a$) 이고 $\text{function} == y$ 인 신소가 존재하는가?
- 위 4개 조건이 모두 만족되면 `isomorphism_valid = true`, `transformation_type = "CANONICAL_ISOMORPHISM"`.
- 하나라도 결손되면 `isomorphism_valid = false`, `transformation_type = "STRUCTURAL_DIVERGENCE"`.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {"isomorphism_tolerance": 0.10},
  "binary_axes": [
    {"axis_id": "nature_culture", "pole_negative": "자연 (Nature)", "pole_positive": "문화 (Culture)"},
    {"axis_id": "raw_cooked", "pole_negative": "날것 (Raw)", "pole_positive": "익힌것 (Cooked)"}
  ],
  "mythemes": [
    {
      "mytheme_id": "m_jaguar_master_of_fire",
      "term": "jaguar",
      "function": "fire_mastery",
      "axis_values": {"nature_culture": 0.8, "raw_cooked": 0.9}
    },
    {
      "mytheme_id": "m_human_eats_raw",
      "term": "human",
      "function": "raw_consumer",
      "axis_values": {"nature_culture": -0.7, "raw_cooked": -0.8}
    },
    {
      "mytheme_id": "m_human_master_of_fire",
      "term": "human",
      "function": "fire_mastery",
      "axis_values": {"nature_culture": 0.9, "raw_cooked": 0.9}
    },
    {
      "mytheme_id": "m_jaguar_beast_raw",
      "term": "jaguar_inv",
      "function": "raw_consumer",
      "axis_values": {"nature_culture": -0.9, "raw_cooked": -0.9}
    }
  ],
  "myths": [
    {
      "myth_id": "myth_bororo_fire",
      "culture": "보로로(Bororo) 인디언 신화",
      "mytheme_sequence": ["m_jaguar_master_of_fire", "m_human_eats_raw"]
    },
    {
      "myth_id": "myth_ge_fire",
      "culture": "제(Ge) 부족 신화",
      "mytheme_sequence": ["m_human_master_of_fire", "m_jaguar_beast_raw"]
    }
  ],
  "canonical_inquiries": [
    {
      "inquiry_id": "inq_bororo_to_ge",
      "source_myth_id": "myth_bororo_fire",
      "target_myth_id": "myth_ge_fire",
      "mapping": {
        "term_a": "jaguar",
        "term_b": "human",
        "func_x": "fire_mastery",
        "func_y": "raw_consumer"
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "total_myths_analyzed": 2,
    "total_inquiries": 1,
    "canonical_isomorphisms_confirmed": 1,
    "structural_divergences": 0
  },
  "myth_profiles": {
    "myth_bororo_fire": {
      "myth_id": "myth_bororo_fire",
      "culture": "보로로(Bororo) 인디언 신화",
      "total_mythemes": 2,
      "axis_scores": {
        "nature_culture": {"mean": 0.05, "tension": 1.5},
        "raw_cooked": {"mean": 0.05, "tension": 1.7}
      },
      "mediators": []
    },
    "myth_ge_fire": {
      "myth_id": "myth_ge_fire",
      "culture": "제(Ge) 부족 신화",
      "total_mythemes": 2,
      "axis_scores": {
        "nature_culture": {"mean": 0.0, "tension": 1.8},
        "raw_cooked": {"mean": 0.0, "tension": 1.8}
      },
      "mediators": []
    }
  },
  "inquiry_results": [
    {
      "inquiry_id": "inq_bororo_to_ge",
      "source_myth": "myth_bororo_fire",
      "target_myth": "myth_ge_fire",
      "canonical_formula": "F_fire_mastery(jaguar) : F_raw_consumer(human) ≃ F_fire_mastery(human) : F_jaguar^(-1)(raw_consumer)",
      "isomorphism_valid": true,
      "transformation_type": "CANONICAL_ISOMORPHISM",
      "verification_details": {
        "source_has_Fx_a": true,
        "source_has_Fy_b": true,
        "target_has_Fx_b": true,
        "target_has_Fa_inv_y": true
      }
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(binary_axes) <= 20`
- `1 <= len(mythemes) <= 500`
- `1 <= len(myths) <= 50`
- `0 <= len(canonical_inquiries) <= 20`
- `mediators` 배열은 오름차순으로 정렬되어 반환되어야 합니다.
