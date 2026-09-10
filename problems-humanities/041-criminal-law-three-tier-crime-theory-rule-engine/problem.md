# 문제 #041: 유죄인가, 정당방위인가? 형법학(Criminal Jurisprudence) & 리걸테크(Legal Tech): 대륙법계 3단계 범죄성립 체계론(Three-Tier Theory of Crime: 구성요건 해당성·위법성·책임) 및 사법 판정 룰 엔진 (Three-Tier Crime Theory & Legal Tech Rule Engine)

## 실무 및 법공학 배경: 형사 리걸테크 AI와 법적 삼단논법(Legal Syllogism)의 자동화
대한민국 법원 및 검찰청의 형사 사법 전산망 고도화 사업단과 리걸테크(Legal Tech) 스타트업 컨소시엄은 대법원 판례 및 형법 도그마틱(Rechtsdogmatik)을 기반으로 사건 수사와 판결을 보조하는 **형사 범죄 성립 판정 룰 엔진(Criminal Verdict Rule Engine)**을 구축하고 있습니다.

인간의 행위가 형벌을 부과할 수 있는 '범죄'가 되기 위해서는 단순한 직관이나 감정이 아닌, 독일과 프랑스를 비롯한 대륙법계(Civil Law) 국가들이 150여 년간 정립해 온 **3단계 범죄성립 체계론(Three-Tier Theory of Crime)**을 엄격하게 거쳐야 합니다:

```text
               [인간의 구체적 행위 (Human Conduct)]
                                 │
                                 ▼
   [제1단계: 구성요건 해당성 (Tatbestandsmäßigkeit)]
   - 객관적 구성요건: 행위, 결과 발생, 상당인과관계
   - 주관적 구성요건: 고의(직접·미필적), 과실, 사실의 착오
   ──▶ 탈락 시: 무죄 (NOT_GUILTY_NO_CONSTITUENT_ELEMENT)
                                 │ 충족 (위법성 추정)
                                 ▼
   [제2단계: 위법성 (Rechtswidrigkeit) 및 위법성 조각사유]
   - 정당방위 (형법 제21조), 긴급피난 (제22조), 피해자의 승낙 (제24조), 정당행위 (제20조)
   ──▶ 정당화 성공: 무죄 (NOT_GUILTY_JUSTIFIED_*)
   ──▶ 야간 공포 과잉방위: 벌하지 아니함 (NOT_PUNISHABLE_EXCULPATED_EXCESSIVE_DEFENSE_FEAR)
                                 │ 불조각 (위법성 확정)
                                 ▼
   [제3단계: 책임 (Schuld) 및 책임 조각·감경 사유]
   - 형사미성년자 (형법 제9조: 만 14세 미만) ──▶ 벌하지 아니함
   - 심신상실 (제10조 제1항) ──▶ 벌하지 아니함 (단, 원인에 있어서 자유로운 행위 시 배제)
   - 강요된 행위 (제12조), 법률의 착오 정당한 이유 (제16조) ──▶ 벌하지 아니함
   - 심신미약 (제10조 제2항) / 과잉방위 (제21조 제2항) ──▶ 형의 법정감경 (50% 감경)
                                 │ 비난가능성 인정
                                 ▼
   [최종 판결: 유죄 확정 (CRIME_ESTABLISHED_GUILTY) 및 선고형 산출]
```

형사법 전문 변호사이자 리걸테크 시스템 소프트웨어 엔지니어로서, 피고인의 연령·정신상태, 기소 죄명, 객관적·주관적 사실관계, 위법성 및 책임 조각 주장을 순차적으로 검증하여 최종 판결 및 법정 감경 형량을 결정하고, 다수 피고인에 대한 사법 양형 통계를 산출하는 엔진을 구현하십시오.

---

## 3단계 범죄성립 체계론 알고리즘 사양

### 1. 제1단계: 구성요건 해당성 (Tatbestandsmäßigkeit)
1. **객관적 구성요건 (Objective Elements)**:
   - `act_committed == True` (실행행위 존재)
   - `result_occurred == True` (결과 발생)
   - `causality_established == True` (행위와 결과 간 상당인과관계 인정)
   - 셋 중 하나라도 `False`인 경우 즉시 탈락:
     - `stage_reached`: `"TIER_1_CONSTITUENT_ELEMENTS"`
     - `verdict`: `"NOT_GUILTY_NO_CONSTITUENT_ELEMENT"`
     - `guilty`: `False`, `final_penalty_months`: `0.0`
2. **주관적 구성요건 (Subjective Elements)**:
   - `mistake_of_fact == True` (사실의 착오, 형법 제15조 제1항):
     - 구성요건적 고의가 조각됨.
     - `mens_rea == "NEGLIGENCE"`이고 `charge.negligence_punishable == True`인 경우에만 과실범 구성요건 충족. 그 외에는 구성요건 탈락 (`NOT_GUILTY_NO_CONSTITUENT_ELEMENT`).
   - `mistake_of_fact == False`:
     - `mens_rea`가 `"INTENT_DIRECT"` 또는 `"INTENT_CONDITIONAL"`: 고의 인정, 구성요건 충족.
     - `mens_rea == "NEGLIGENCE"`:
       - `charge.negligence_punishable == True`인 경우에만 충족, 그렇지 않으면 형법 제14조에 의해 불벌 (`NOT_GUILTY_NO_CONSTITUENT_ELEMENT`).
     - `mens_rea == "NONE"`: 탈락 (`NOT_GUILTY_NO_CONSTITUENT_ELEMENT`).

---

### 2. 제2단계: 위법성 (Rechtswidrigkeit) 및 위법성 조각사유
구성요건 해당성이 인정되면 위법성은 원칙적으로 추정됩니다. 주장된 사유(`claimed_defense`)를 검토합니다:
1. `"NONE"`: 위법성 인정 $\implies$ 제3단계 진행.
2. `"SELF_DEFENSE"` (정당방위, 형법 제21조):
   - 성립요건: `unlawful_attack_imminent == True` AND `defensive_intent == True`.
   - 요건 충족 시:
     - `proportionality == True` (상당성 있음): 위법성 조각 $\implies$ `"NOT_GUILTY_JUSTIFIED_SELF_DEFENSE"`, 종결.
     - `proportionality == False` (과잉방위):
       - `nighttime_or_fear == True` (야간 공포·경악·당황, 제21조 제3항): 면책적 과잉방위 $\implies$ `"NOT_PUNISHABLE_EXCULPATED_EXCESSIVE_DEFENSE_FEAR"`, 종결.
       - `nighttime_or_fear == False`: 보통 과잉방위(위법성 미조각, 제21조 제2항 감경 대상 마킹) $\implies$ 제3단계 진행.
   - 요건 미충족 시: 정당방위 불성립 $\implies$ 제3단계 진행.
3. `"EMERGENCY_NECESSITY"` (긴급피난, 형법 제22조):
   - 성립요건: `imminent_danger == True` AND `superior_interest == True` AND `last_resort == True`.
   - 충족 시 위법성 조각 $\implies$ `"NOT_GUILTY_JUSTIFIED_NECESSITY"`, 종결.
   - 미충족 시 $\implies$ 제3단계 진행.
4. `"VICTIM_CONSENT"` (피해자의 승낙, 형법 제24조):
   - 성립요건: `valid_consent == True` AND `alienable_interest == True` (생명 등 불가처분 법익은 불가).
   - 충족 시 위법성 조각 $\implies$ `"NOT_GUILTY_JUSTIFIED_CONSENT"`, 종결.
   - 미충족 시 $\implies$ 제3단계 진행.
5. `"JUSTIFIED_ACT"` (정당행위, 형법 제20조):
   - 성립요건: `statutory_or_customary == True` (법령·업무·사회상규 위배 안 됨).
   - 충족 시 위법성 조각 $\implies$ `"NOT_GUILTY_JUSTIFIED_ACT"`, 종결.
   - 미충족 시 $\implies$ 제3단계 진행.

---

### 3. 제3단계: 책임 (Schuld) 및 책임 조각·감경 사유
1. **형사미성년자 (형법 제9조)**: `age < 14` $\implies$ `"NOT_PUNISHABLE_EXCULPATED_JUVENILE"`, 종결.
2. **강요된 행위 (형법 제12조)**: `coerced == True` AND `unavoidable_force_or_threat == True` $\implies$ `"NOT_PUNISHABLE_EXCULPATED_DURESS"`, 종결.
3. **법률의 착오 (형법 제16조)**: `mistake_claimed == True` AND `justifiable_ground == True` $\implies$ `"NOT_PUNISHABLE_EXCULPATED_MISTAKE_OF_LAW"`, 종결.
4. **심신장애 (형법 제10조)**:
   - `actio_libera_in_causa == True` (원인에 있어서 자유로운 행위, 제10조 제3항): 고의·과실로 심신장애를 자초한 자는 심신장애 감면 규정 적용 배제!
   - `actio_libera_in_causa == False`인 경우:
     - `mental_condition == "INSANITY"` (심신상실, 제10조 제1항): `"NOT_PUNISHABLE_EXCULPATED_INSANITY"`, 종결.
     - `mental_condition == "DIMINISHED"` (심신미약, 제10조 제2항): 심신미약 감경 대상 마킹 후 진행.

---

### 4. 최종 판결 및 선고형 산출 (`VERDICT_RENDERED`)
책임 조각사유가 없으면 비로소 유죄(`"CRIME_ESTABLISHED_GUILTY"`)가 선고됩니다:
- `guilty`: `True`
- 법정형 감경 적용 (형법 제55조: 유기징역형 감경 시 형기의 $1/2$로 감경):
  - 과잉방위 감경 대상인 경우: $\times 0.5$
  - 심신미약 감경 대상인 경우: $\times 0.5$
  - 감경이 둘 다 적용되면 $\times 0.25$가 됨.
- `final_penalty_months`: 최종 형량 (소수점 둘째 자리까지 반올림: `round(penalty, 2)`).

---

## 입력 및 출력 사양

### 입력 형식 (`sys.stdin`)
JSON 객체로 주어지며 `mode`에 따라 두 가지 형식입니다:
1. `mode == "EVALUATE_CASE"`:
   단일 사건 심리 객체 `case`를 평가합니다.
2. `mode == "BATCH_TRIAL_ANALYTICS"`:
   다수 피고인 사건 목록 `cases`에 대해 일괄 심리를 수행하고 통계를 산출합니다.

### 출력 형식 (`sys.stdout`)
- `EVALUATE_CASE`:
  `case_id`, `stage_reached`, `verdict`, `guilty`, `reasoning_chain`, `sentencing`을 포함한 단일 JSON 객체 한 줄.
- `BATCH_TRIAL_ANALYTICS`:
  - `total_cases`: 총 사건 수
  - `conviction_rate`: 유죄 선고율 (`guilty_count / total_cases`, 소수점 4자리 반올림)
  - `justification_rate`: 위법성 조각률 (소수점 4자리 반올림)
  - `exculpation_rate`: 책임 조각률 (소수점 4자리 반올림)
  - `constituent_failure_rate`: 구성요건 탈락률 (소수점 4자리 반올림)
  - `average_sentence_months`: 유죄 판결 피고인들의 평균 선고형 (개월수, 소수점 2자리 반올림; 유죄 없으면 0.0)
  - `verdicts_summary`: 판결 코드별 빈도수 딕셔너리
  - `verdict_list`: 각 사건별 상세 판결 객체 리스트
