# 데이비드 흄의 인간 본성론과 회의주의 엔진: 귀납의 문제, 항구적 결합 및 자아의 다발설

## 문제 설명

스코틀랜드 계몽주의의 거두 **데이비드 흄(David Hume, 1711–1776)**은 1739년 『인간 본성에 관한 논고』(A Treatise of Human Nature)와 1748년 『인간 오성의 탐구』(An Enquiry Concerning Human Understanding)를 통해 서양 철학사에서 가장 치명적이고 급진적인 경험론적 회의주의를 전개했습니다.

임마누엘 칸트(Immanuel Kant)로 하여금 **"나를 독단의 잠(Dogmatischer Schlummer)에서 깨워준 은인"**이라고 고백하게 만든 흄의 철학은 지식의 기원, 인과율의 본질, 자아의 실체성에 대한 전통적 형이상학의 환상을 무자비하게 해체했습니다.

```
                  [ 인간 마음의 모든 지각 (Perceptions) ]
                                    │
               ┌────────────────────┴────────────────────┐
               ▼                                         ▼
       인상 (Impressions)                         관념 (Ideas)
   - 생생함과 강렬함 극대 (Vivacity)         - 기억과 상상의 희미한 잔상
   - 감각 인상, 내적 정념 인상              - [카피 원리 (Copy Principle)]
                                              인상 없는 관념 = 허구(Fiction)!
                                    │
                                    ▼
                          [ 흄의 갈래 (Hume's Fork) ]
         ┌──────────────────────────┴──────────────────────────┐
         ▼                                                     ▼
   관념의 관계 (Relations of Ideas)                      사실의 문제 (Matters of Fact)
   - 기하학, 대수학, 산술                               - 경험적 관찰 및 인과 추론
   - 선험적(A Priori), 필연적 확실성                    - 경험적(A Posteriori), 우연적
   - 부정 시 논리적 모순 발생                           - 부정해도 모순 없음 ("내일 해가 안 뜬다")
                                    │
                                    ▼
                     [ 인과성과 귀납의 문제 (Induction) ]
                 1. 공간적 인접성 (Contiguity)
                 2. 시간적 선후성 (Priority in Time)
                 3. 항구적 결합 (Constant Conjunction)
                 * "필연적 결합(Necessary Connexion)"은 지각 불가!
                 * 반복 경험이 낳은 심리적 습관(Custom/Habit)과 신념(Belief)일 뿐!
                                    │
                                    ▼
                    [ 자아의 다발설 (Bundle Theory of Self) ]
                 - 고정불변의 영혼/사유실체(Substance) 인상은 전무함
                 - 쉼 없이 스쳐 지나가는 지각들의 다발(Bundle)이자 극장(Theater)
```

본 시스템은 흄의 인식론적 원리들을 엄격히 형식화하여 검증하는 **흄의 지성 및 회의주의 시뮬레이션 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 카피 원리 (The Copy Principle)
- 모든 정당한 관념(`IDEA`)은 그에 선행하는 생생한 인상(`IMPRESSION`, `vivacity >= 0.5`)의 복사본이어야 합니다.
- 원천 인상이 누락되었거나(`source_impression_id` 부재), 인상의 생생도가 기준 미달인 관념은 **`FICTION_OF_IMAGINATION` (허구적 관념)**으로 분류됩니다.

### 2. 흄의 갈래 (Hume's Fork)와 형이상학 서적 소각
제시된 주장(`claims`)을 세 가지 갈래로 엄격히 판정합니다:
1. **관념의 관계 (`RELATION_OF_IDEAS`)**: 수학적·논리적 명제. `negation_conceivable = false`, `action = "PRESERVE_AS_A_PRIORI_KNOWLEDGE"`.
2. **사실의 문제 (`MATTER_OF_FACT`)**: 경험적 사건. `negation_conceivable = true`, `action = "PROBABLE_INDUCTION_SUBJECT_TO_EXPERIENCE"`.
3. **형이상학적 실체 (`METAPHYSICAL_SUBSTANCE`)**: 경험적 인상도, 수량에 관한 추론도 없는 공허한 독단.
   - 흄의 유명한 명제: *"그것을 불속에 던져버려라(Commit it to the flames)! 그것은 궤변과 환상 이외의 아무것도 담고 있지 않기 때문이다."*
   - `action = "COMMIT_TO_THE_FLAMES"`

### 3. 인과성과 귀납의 문제 (Constant Conjunction & Induction)
- 두 사건 $A$와 $B$의 인과 추론은 세 가지 경험 조건에 기반합니다:
  - 공간적 인접성 (`spatial_contiguous = true`)
  - 시간적 선후성 (`temporal_priority = true`, 원인 $A$가 결과 $B$에 선행)
  - 항구적 결합률: $	ext{rate} = rac{	ext{conjoined count}}{	ext{total count}}$
- **습관 형성 조건**: `rate >= 0.75` 이고 관찰 횟수 $\ge 3$회일 때 마음에 심리적 습관(`habit_formed = true`, `status = "HABITUAL_EXPECTATION"`)이 형성됩니다.
- **필연적 결합 비판**: 자연 속에서 어떤 숨겨진 원인적 연결고리도 인상으로 지각될 수 없으므로, **`necessary_connexion_perceived`는 항상 `false`**입니다.

### 4. 자아의 다발설 (Bundle Theory of the Self)
- 내성(Introspection)을 통해 내면을 응시할 때, 고정된 '불변의 실체적 자아(Substantial Self)'는 결코 발견되지 않습니다 (`substantial_self_found = false`).
- 오직 시시각각 생멸하는 감각, 고통, 쾌락, 슬픔 등의 지각들의 다발(`THEATER_OF_PASSING_PERCEPTIONS`)만이 존재합니다.

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "agent_id": "David_Hume",
  "perceptions": [
    {"id": "IMP_HEAT", "type": "IMPRESSION", "content": "Sensation of heat from fire", "vivacity": 0.95},
    {"id": "IDEA_HEAT", "type": "IDEA", "content": "Memory of heat", "source_impression_id": "IMP_HEAT", "vivacity": 0.4},
    {"id": "IDEA_SUBSTANCE", "type": "IDEA", "content": "Hidden Substantial Essence", "source_impression_id": "NON_EXISTENT", "vivacity": 0.1}
  ],
  "observations": [
    {"event_a": "FLAME", "event_b": "HEAT", "spatial_contiguous": true, "temporal_priority": true, "conjoined": true},
    {"event_a": "FLAME", "event_b": "HEAT", "spatial_contiguous": true, "temporal_priority": true, "conjoined": true},
    {"event_a": "FLAME", "event_b": "HEAT", "spatial_contiguous": true, "temporal_priority": true, "conjoined": true}
  ],
  "claims": [
    {"id": "CLM_01", "type": "RELATION_OF_IDEAS", "statement": "3 times 5 equals 15"},
    {"id": "CLM_02", "type": "MATTER_OF_FACT", "statement": "The sun will rise tomorrow"},
    {"id": "CLM_03", "type": "METAPHYSICAL_SUBSTANCE", "statement": "An invisible occult power connects cause to effect"}
  ],
  "introspection": {
    "query_self": true,
    "introspection_stream": [
      {"perception": "Pain", "vivacity": 0.8},
      {"perception": "Joy", "vivacity": 0.7}
    ]
  }
}
```

---

## 출력 형식

평가된 지성 메트릭, 카피 원리 검증 결과, 흄의 갈래 평가, 인과 추론 결과, 자아 다발 분석을 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "agent_id": "David_Hume",
  "metrics": {
    "impressions_count": 1,
    "ideas_count": 2,
    "fiction_ideas_count": 1,
    "flames_committed_count": 1,
    "causal_habits_formed": 1,
    "epistemic_skepticism_score": 65.0
  },
  "verdict": "MODERATE_ACADEMIC_SKEPTICISM",
  "copy_principle": {
    "ideas": {
      "IDEA_HEAT": {"id": "IDEA_HEAT", "content": "Memory of heat", "vivacity": 0.4, "source_impression_id": "IMP_HEAT", "is_legitimate_copy": true},
      "IDEA_SUBSTANCE": {"id": "IDEA_SUBSTANCE", "content": "Hidden Substantial Essence", "vivacity": 0.1, "source_impression_id": "NON_EXISTENT", "is_legitimate_copy": false}
    },
    "fictions": ["IDEA_SUBSTANCE"]
  },
  "humes_fork_claims": [
    {"id": "CLM_01", "fork_branch": "RELATIONS_OF_IDEAS", "epistemic_status": "DEMONSTRATIVELY_CERTAIN", "negation_conceivable": false, "action": "PRESERVE_AS_A_PRIORI_KNOWLEDGE"},
    {"id": "CLM_02", "fork_branch": "MATTERS_OF_FACT", "epistemic_status": "CONTINGENT_EMPIRICAL", "negation_conceivable": true, "action": "PROBABLE_INDUCTION_SUBJECT_TO_EXPERIENCE"},
    {"id": "CLM_03", "fork_branch": "SOPHISTRY_AND_ILLUSION", "epistemic_status": "UNGROUNDED_METAPHYSICS", "negation_conceivable": true, "action": "COMMIT_TO_THE_FLAMES"}
  ],
  "causal_inferences": [
    {"pair": "FLAME->HEAT", "observations_count": 3, "constant_conjunction_rate": 1.0, "habit_formed": true, "customary_belief_strength": 0.3, "necessary_connexion_perceived": false, "status": "HABITUAL_EXPECTATION"}
  ],
  "bundle_self": {
    "substantial_self_found": false,
    "perceptions_in_flux": 2,
    "nature_of_mind": "THEATER_OF_PASSING_PERCEPTIONS",
    "description": "Mind is a bundle or collection of different perceptions which succeed each other with an inconceivable rapidity"
  }
}
```

---

## 점수 및 판정 공식

1. **인식론적 회의주의 점수 (`epistemic_skepticism_score`)**:
   - $	ext{copy\_score} = (	ext{valid\_copies} / 	ext{total\_ideas}) 	imes 40.0$ (관념이 없으면 기본 40.0)
   - $	ext{flames\_score} = \min(30.0, 	ext{flames\_count} 	imes 15.0)$
   - $	ext{induction\_score} = \min(30.0, 	ext{causal\_inferences\_count} 	imes 10.0)$
   - $	ext{skepticism\_score} = 	ext{round}(	ext{copy\_score} + 	ext{flames\_score} + 	ext{induction\_score}, 2)$
2. **인식 단계 판정 (`verdict`)**:
   - $\ge 80.0$: `"RADICAL_EMPIRICAL_SKEPTICISM"` (철저한 경험주의 회의론)
   - $\ge 50.0$: `"MODERATE_ACADEMIC_SKEPTICISM"` (온건한 아카데미파 회의론)
   - $< 50.0$: `"DOGMATIC_SLUMBER"` (독단의 잠)
