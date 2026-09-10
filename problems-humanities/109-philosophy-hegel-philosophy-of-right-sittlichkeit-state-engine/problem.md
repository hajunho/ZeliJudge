# 게오르크 헤겔의 법철학 강요: 추상법, 도덕성 및 인륜성(가족·시민사회·국가)의 자유 실현 엔진

## 문제 설명

독일 관념론의 집대성자 **G.W.F. 헤겔(G.W.F. Hegel, 1770–1831)**은 1820년 출간된 기념비적 주저 **『법철학 강요』(Grundlinien der Philosophie des Rechts)**를 통해, 서양 근대 철학사에서 자유(Freiheit)의 개념을 가장 정교하고 거대한 유기적 체계로 정립했습니다.

헤겔은 서문에서 유명한 명제를 던집니다:
> *"이성적인 것은 현실적인 것이요, 현실적인 것은 이성적인 것이다 (Was vernünftig ist, das ist wirklich; und was wirklich ist, das ist vernünftig)."*

헤겔에게 자유란 타인의 간섭 없이 내 마음대로 행동하는 '자의(Willkür, 소극적 자유)'가 아닙니다. 진정한 자유는 법률, 도덕, 가족, 시장 경제, 국가라는 객관적 사회 제도 속에서 자신을 단계적으로 실현하고 구체화하는 **"구체적 자유(Konkrete Freiheit)"**입니다.

```
                  [ 자유의지(Free Will)의 변증법적 자기 실현 ]
                                      │
     ┌────────────────────────────────┼────────────────────────────────┐
     ▼                                ▼                                ▼
[ 1. 추상법 (Abstract Right) ]  [ 2. 도덕성 (Moralität) ]   [ 3. 인륜성 (Sittlichkeit) ]
 - 인격과 외적 소유권           - 주관적 내면의 의지        - 객관적 제도 속의 구체적 자유
 - 상호 승인 계약               - 고의, 책임, 의도와 복리   ┌───────────────────────────────┐
 - 불법과 형벌                  - 칸트적 형식주의 비판      │ a. 가족: 사랑과 자연적 공동체 │
   ("부정의 부정")                                          │ b. 시민사회: 욕구 체계·분업·   │
                                                            │    사법·경찰·직능단체(빈곤 구제)│
                                                            │ c. 국가: 보편성과 개별성의   │
                                                            │    유기적 통일 ("신의 지상 행진")│
                                                            └───────────────────────────────┘
```

본 시스템은 헤겔의 법철학 발전 3단계를 정밀하게 모델링하여 개인의 행위가 공동체의 윤리적 삶 속에서 자유를 실현하는 과정을 평가하는 **헤겔 인륜성 및 국가철학 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 제1단계: 추상법 (Das abstrakte Recht)
- **소유권 (`ACQUIRE_PROPERTY`)**: 자유의지가 외적 물질에 자신을 투사하여 소유권을 확립합니다.
- **계약 (`SIGN_CONTRACT`)**: 두 인격이 상호 인정을 통해 공동의 의지를 형성합니다.
- **범죄와 형벌 (`COMMIT_CRIME` & `ENFORCE_PUNISHMENT`)**:
  - 범죄는 객관적 법의 부정입니다 (`severity`만큼 점수 차감).
  - 형벌은 범죄라는 부정에 가해지는 보복적 재부정, 즉 **"부정의 부정(Negation of Negation)"**으로서 법의 실재성을 회복합니다 (`crimes_negated` 증가 및 점수 회복).

### 2. 제2단계: 도덕성 (Die Moralität)
- **주관적 의도 (`INTERNAL_INTENTION`)**:
  - 행위의 결과뿐 아니라 주관적 동기와 선(Good)의 실현 의지를 평가합니다.
  - 칸트식 공허한 형식주의나 위선(`is_empty_formalism: true`)인 경우 도덕적 점수가 감점됩니다.

### 3. 제3단계: 인륜성 (Die Sittlichkeit)
주관적 도덕성과 객관적 법이 화해하여 제도화된 세 가지 유기적 층위:
1. **가족 (`FAMILY_LOVE`)**: 개별성을 양도하고 사랑과 신뢰로 결합된 직접적·자연적 윤리 공동체.
2. **시민사회 (`MARKET_TRANSACTION` & `CORPORATION_MUTUAL_AID`)**:
   - 욕구의 체계(System of Needs): 사익 추구와 시장 분업.
   - 직능단체(Corporation)와 공공 권력: 시장의 맹목적 양극화와 **빈곤(Pauperismus)**을 복지와 연대로 치유.
3. **국가 (`STATE_CIVIC_DUTY`)**:
   - 개인의 특수한 이익과 보편적 공공의 선이 완벽하게 일치하는 최고위의 인륜적 실체 ("지상에 존재하는 신의 행진").

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "subject_id": "Hegel_Scholar",
  "actions": [
    {"type": "ACQUIRE_PROPERTY", "params": {"value": 20.0}},
    {"type": "SIGN_CONTRACT", "params": {"value": 20.0}},
    {"type": "COMMIT_CRIME", "params": {"severity": 5.0}},
    {"type": "ENFORCE_PUNISHMENT", "params": {"severity": 5.0}},
    {"type": "INTERNAL_INTENTION", "params": {"moral_clarity": 10.0, "is_empty_formalism": false}},
    {"type": "FAMILY_LOVE", "params": {"solidarity": 10.0}},
    {"type": "MARKET_TRANSACTION", "params": {"utility": 15.0}},
    {"type": "CORPORATION_MUTUAL_AID", "params": {"welfare_support": 10.0}},
    {"type": "STATE_CIVIC_DUTY", "params": {"patriotic_rationality": 10.0}}
  ]
}
```

---

## 출력 형식

계산된 지표와 단계별 자유 실현 점수, 상세 행위 로그를 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "subject_id": "Hegel_Scholar",
  "metrics": {
    "abstract_right_score": 20.0,
    "morality_score": 15.0,
    "sittlichkeit_score": 44.5,
    "total_freedom_realization_score": 79.5,
    "properties_owned": 1,
    "contracts_ratified": 1,
    "crimes_negated": 1,
    "civil_market_trades": 1,
    "civic_duties_rendered": 1
  },
  "verdict": "CIVIL_SOCIETY_PARTICULARITY",
  "action_log": [
    {
      "type": "ACQUIRE_PROPERTY",
      "domain": "ABSTRACT_RIGHT",
      "status": "PROPERTY_EMBODIED_WILL",
      "desc": "External object appropriated as sphere of personality"
    }
  ]
}
```

---

## 점수 산출 및 판정 공식

1. **영역별 최대 상한**:
   - 추상법 점수: $\le 30.0$
   - 도덕성 점수: $\le 25.0$
   - 인륜성 점수: $\le 45.0$ (가족 최대 10, 시민사회 최대 15, 국가 최대 20)
   - 총 자유 실현 점수 = $	ext{abstract\_right} + 	ext{morality} + 	ext{sittlichkeit}$
2. **최종 판정 (`verdict`)**:
   - $\ge 80.0$: `"CONCRETE_FREEDOM_REALIZED"` (구체적 자유의 완성: 인륜적 국가)
   - $\ge 50.0$: `"CIVIL_SOCIETY_PARTICULARITY"` (시민사회적 개별성과 욕구의 체계)
   - $< 50.0$: `"ABSTRACT_LEGALISM_OR_FORMAL_MORALITY"` (추상적 법치 또는 형식적 도덕)
