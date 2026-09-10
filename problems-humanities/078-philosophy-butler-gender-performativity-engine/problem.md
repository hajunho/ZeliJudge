# 주디스 버틀러의 젠더 트러블: 젠더 수행성(Performativity) 및 이성애 매트릭스 해체 엔진

## 문제 설명

현대 철학자이자 퀴어 이론의 개척자인 **주디스 버틀러(Judith Butler)**는 대표작 *《젠더 트러블: 페미니즘과 정체성의 전복(Gender Trouble: Feminism and the Subversion of Identity, 1990)》*과 *《바디스 댓 매터(Bodies That Matter, 1993)》*를 통해 성(Sex)과 젠더(Gender)에 관한 기존의 생물학적·본질주의적 전제를 근본적으로 해체했습니다.

버틀러의 핵심 통찰은 다음과 같습니다:

1. **젠더 수행성(Gender Performativity)**:
   - 젠더는 인간 내면에 본래부터 내재하는 선험적 실체(Essence)나 생물학적 성(Sex)의 자연스러운 발현이 아닙니다.
   - 젠더는 시간의 흐름 속에서 신체적 행위(말투, 옷차림, 걸음걸이, 태도)를 끝없이 **반복적으로 양식화(Stylized repetition of bodily acts)**함으로써 사후적으로 자연스러운 본질인 것처럼 '생산된 효과(Effect)'이자 환상입니다.
   > *"행위 배후에 행위자라는 본질은 없다. 행위자가 곧 행위 속에서 수행적으로 구성된다."*
2. **이성애 중심적 매트릭스(Heterosexual Matrix)**:
   - 가부장적 사회 규범은 `생물학적 성(Sex) -> 사회적 성(Gender) -> 이성애적 욕망(Desire)`이라는 3단계 선형적 인과관계를 필연적인 자연의 법칙으로 강제합니다.
   - 이 단일한 규범 궤적에서 벗어난 주체는 사회적 담론 속에서 **'이해 불가능한 신체(Unintelligible / Abject Bodies)'**로 낙인찍히고 배제됩니다.
3. **인용적 반복(Citation)과 전복적 불일치(Subversive Slippage)**:
   - 젠더 규범은 개인이 마음대로 연기하는 단순한 연극(Performance)이 아니라, 제도적 강제력을 지닌 규범을 '인용'하는 것입니다.
   - 그러나 모든 반복에는 필연적으로 틈새(Slippage)와 불일치가 발생합니다. 드래그(Drag), 젠더 패러디, 퀴어 실천과 같은 **전복적 신체 실천(Subversive Bodily Acts)**은 "애초에 자연스러운 원본 젠더란 존재하지 않으며, 모든 젠더가 원본 없는 복제의 모방에 불과하다"는 사실을 폭로합니다.

본 문제에서는 버틀러의 젠더 수행성 이론을 수리 모델로 정식화하여, 주체들의 지정 성별($AssignedSex$), 수행된 젠더($PerformedGender$), 성적 욕망 지향($Desire$), 규범 순응도($Conformity$), 젠더 트러블 지수($TroubleIndex$), 이해 가능성($Intelligibility$), 그리고 이성애 매트릭스의 지배 체제($MatrixState$) 전이를 시뮬레이션하는 엔진을 구현합니다.

---

## 아키텍처 및 수학적 공식

```
               [ 이성애 중심적 매트릭스 (Heterosexual Matrix) ]
             강제 규범: Sex(남/여) -> Gender(남성/여성) -> Desire(이성애)
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │                젠더 수행성 (Performativity)              │
       │         신체적 행위의 인용적 반복 (Iterative Citation)  │
       └────────────────────────────┬───────────────────────────┘
                                    │
               ┌────────────────────┴────────────────────┐
               │                                         │
     [ 규범적 순응 반복 ]                      [ 전복적 신체 실천 (Drag/Parody) ]
     - Normative Citation                      - Subversive Citation
     - 이성애 매트릭스 고착                      - 규범적 틈새 폭로 & 트러블 유발
     - TroubleIndex = 0                        - TroubleIndex 상승
               │                                         │
               ▼                                         ▼
     [ 규범적 헤게모니 유지 ]                  [ 전복적 파열 (Subversion Rupture) ]
     (NORMATIVE_HEGEMONY)                    (PARODIC_SUBVERSION_RUPTURE)
```

### 1. 젠더 불협화($Dissonance$) 및 트러블 지수 ($TroubleIndex$)

각 주체 $i$의 규범적 정합성 검사:
- **규범적 젠더 여부**:
  - `assigned_sex == "male" and performed_gender == "masculine"` 또는
  - `assigned_sex == "female" and performed_gender == "feminine"` 이면 정상 규범 부합.
  - 불일치 시: $Dissonance_i \leftarrow Dissonance_i + 0.55$.
- **규범적 욕망 여부**:
  - `desire_orientation == "hetero"` 이면 정상 규범 부합.
  - 불일치 시: $Dissonance_i \leftarrow Dissonance_i + 0.45$.
- **개별 젠더 트러블 지수 ($TroubleIndex_i$)**:
  $$TroubleIndex_i = 	ext{round}\Big(	ext{clamp}ig(Dissonance_i 	imes (1.0 - ConformityRatio_i 	imes 0.7), 0.0, 1.0ig), 4\Big)$$
- **이해 가능성 ($Intelligibility_i$)**:
  매트릭스의 강제력($MatrixCoercion$) 하에서 규범 이탈도와 비순응도가 임계치를 초과하면 공적 사회에서 비가시화된 '이해 불가능한 신체'로 추방됩니다:
  $$	ext{abject\_pressure} = MatrixCoercion 	imes Dissonance_i 	imes (1.0 - ConformityRatio_i)$$
  $$	ext{is\_intelligible} = (	ext{abject\_pressure} < 0.45)$$

### 2. 매트릭스 지배 체제 ($MatrixState$)

사회 전체 평균 트러블 지수: $\overline{Trouble} = rac{1}{N}\sum_{i=1}^N TroubleIndex_i$
- $\overline{Trouble} \ge 0.55$: `"PARODIC_SUBVERSION_RUPTURE"` (패러디적 전복 파열: 이성애 매트릭스의 해체)
- $0.25 \le \overline{Trouble} < 0.55$: `"CONTESTED_GENDER_TROUBLE"` (경합하는 젠더 트러블: 규범과 저항의 길항)
- $\overline{Trouble} < 0.25$: `"NORMATIVE_HEGEMONY"` (규범적 헤게모니 고착)

### 3. 명령어 명세 (Commands)

1. `PERFORM_CITATION` (`subject_id`, `subversion_intensity`):
   - 주체가 젠더를 수행적으로 반복합니다:
     - `iterations` 1 증가.
     - `subversion_intensity > 0.0` (전복적 패러디/드래그):
       $$ConformityRatio_i \leftarrow \max(0.0, ConformityRatio_i - intensity 	imes 0.4)$$
       $$MatrixCoercion \leftarrow \max(0.0, MatrixCoercion - intensity 	imes 0.15)$$
     - `subversion_intensity == 0.0` (규범적 인용):
       $$ConformityRatio_i \leftarrow \min(1.0, ConformityRatio_i + 0.10)$$
2. `ENFORCE_MATRIX_NORMS` (`intensity`):
   - 제도가 이성애 중심 매트릭스 규범을 강화합니다:
     $$MatrixCoercion \leftarrow \min(1.0, MatrixCoercion + intensity)$$
     $$orall i, \; ConformityRatio_i \leftarrow \min(1.0, ConformityRatio_i + intensity 	imes 0.2)$$
3. `REASSIGN_PERFORMANCE` (`subject_id`, `new_gender`, `new_desire`):
   - 주체의 수행된 젠더와 욕망 지향을 재배치합니다.
4. `STEP`:
   - 스텝 카운터를 1 증가시키고 상태를 갱신합니다.
5. `QUERY_BUTLER_STATE`:
   - 현재 시점의 스냅샷(`step`, `matrix_coercion`, `avg_trouble`, `matrix_state`, `unintelligible_count`, `subjects`)을 `query_logs`에 저장합니다. (주체 딕셔너리는 `subject_id` 오름차순 정렬)

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "matrix_coercion": 0.80,
    "subjects": [
      {
        "subject_id": "cis_male",
        "name": "Conformist Man",
        "assigned_sex": "male",
        "performed_gender": "masculine",
        "desire_orientation": "hetero",
        "conformity_ratio": 0.95
      },
      {
        "subject_id": "drag_queen",
        "name": "Subversive Performer",
        "assigned_sex": "male",
        "performed_gender": "feminine",
        "desire_orientation": "homo",
        "conformity_ratio": 0.20
      }
    ]
  },
  "commands": [
    {"type": "PERFORM_CITATION", "subject_id": "drag_queen", "subversion_intensity": 0.80},
    {"type": "QUERY_BUTLER_STATE"},
    {"type": "STEP"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 한 줄로 출력합니다:
```json
{"total_steps":1,"matrix_coercion":0.68,"avg_trouble":0.5,"matrix_state":"CONTESTED_GENDER_TROUBLE","unintelligible_count":1,"subjects":{"cis_male":{"subject_id":"cis_male","name":"Conformist Man","assigned_sex":"male","performed_gender":"masculine","desire_orientation":"hetero","conformity_ratio":0.95,"iterations":0,"trouble_index":0.0,"is_intelligible":true},"drag_queen":{"subject_id":"drag_queen","name":"Subversive Performer","assigned_sex":"male","performed_gender":"feminine","desire_orientation":"homo","conformity_ratio":0.0,"iterations":1,"trouble_index":1.0,"is_intelligible":false}},"query_logs":[{"step":0,"matrix_coercion":0.68,"avg_trouble":0.5,"matrix_state":"CONTESTED_GENDER_TROUBLE","unintelligible_count":1,"subjects":{"cis_male":{"subject_id":"cis_male","name":"Conformist Man","assigned_sex":"male","performed_gender":"masculine","desire_orientation":"hetero","conformity_ratio":0.95,"iterations":0,"trouble_index":0.0,"is_intelligible":true},"drag_queen":{"subject_id":"drag_queen","name":"Subversive Performer","assigned_sex":"male","performed_gender":"feminine","desire_orientation":"homo","conformity_ratio":0.0,"iterations":1,"trouble_index":1.0,"is_intelligible":false}}}]}
```
