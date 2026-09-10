# 질 들뢰즈의 영화철학: 운동-이미지(Movement-Image) 대 시간-이미지(Time-Image), 감각-운동 도식의 단절 및 결정-이미지(Crystal-Image) 엔진

## 문제 설명

20세기 후반 프랑스를 대표하는 철학자 **질 들뢰즈(Gilles Deleuze, 1925–1995)**는 앙리 베르그송(Henri Bergson)의 시간 철학을 영화 매체에 결합하여 영화철학의 기념비적 명저인 **『시네마 1: 운동-이미지』(Cinéma 1: L'Image-Mouvement, 1983)**와 **『시네마 2: 시간-이미지』(Cinéma 2: L'Image-Temps, 1985)**를 저술했습니다.

들뢰즈는 제2차 세계대전을 기점으로 영화사와 인간 사유에 거대한 존재론적 단절(Rupture)이 발생했다고 분석합니다:

```
[ 전전(Pre-WWII) 고전 영화: 운동-이미지 ]
  자극(S) ─────────────► 행위(A) ─────────────► 새로운 상황(S')
       (감각-운동 도식: Sensory-Motor Schema, SMS 유기적 결합)
       - 행동-이미지 (Action-Image): 서부극, 갱스터, 영웅적 대결
       - 유기적이고 결정된 공간 (Organic Space)
       - 행위자 주체 (Actor)

                       ⚡ 제2차 세계대전의 충격 (전쟁의 폐허, 도시 파괴)
                       감각-운동 도식의 단절 (Rupture of the SMS)

[ 전후(Post-WWII) 현대 영화: 시간-이미지 ]
  자극(S) ─────X (행위 단절) ─────► 봄과 들음의 순수한 지속 (Opsign / Sonsign)
       - 어떤-공간이든 (Espace Quelconque / Any-Space-Whatever): 폐허, 공터, 방황
       - 행위자에서 '보는 자'(Seer / Voyant)로의 전락 (네오리얼리즘, 누벨바그)
       - 결정-이미지 (Crystal-Image): 실제(Actual)와 가상(Virtual)의 불가분적 거울 쌍방 회로
```

1. **고전 영화와 운동-이미지 (The Movement-Image)**:
   - **감각-운동 도식(Sensory-Motor Schema, SMS)**에 지배됩니다. 인물은 외부 환경의 자극($S$)을 지각하고, 이에 대응하여 목적 지향적인 신체적 행동($A$)을 취합니다 ($S \to A \to S'$).
   - 행동-이미지(Action-Image), 지각-이미지(Perception-Image), 정동-이미지(Affection-Image)로 분화되며, 공간은 인물의 행동에 의해 조직되는 **유기적 공간(Organic Space)**입니다.

2. **현대 영화와 시간-이미지 (The Time-Image)**:
   - 전쟁의 참화와 홀로코스트, 원폭 투하는 인간이 상황을 파악하고 즉각 행동으로 교정할 수 있다는 계몽주의적 믿음을 분쇄했습니다.
   - **감각-운동 도식의 단절(Rupture of the SMS)**: 주인공은 더 이상 능동적으로 행동하는 '행위자(Actor)'가 아니라, 무기력하게 바라볼 수밖에 없는 **'보는 자(Seer / Voyant)'**로 전락합니다 (예: 비토리오 데 시카의 『자전거 도둑』 속 방황하는 부자).
   - 공간은 지리적 인과성이 소멸된 **'어떤-공간이든(Espace Quelconque / Any-Space-Whatever)'**(폐허, 미로, 빈 부두, 도시의 틈새)으로 변모합니다.
   - 행동으로 이어지지 못하고 축적된 지각은 **순수 시각상(Opsign)과 순수 청각상(Sonsign)**을 형성합니다.
   - 나아가 기억(과거)과 현실(현재)이 거울 속 상처럼 서로를 비추며 얽히는 **결정-이미지(Crystal-Image)**를 통해 시간의 순수한 형태가 직접 제시됩니다 (예: 알랭 레네의 『지난해 마리앙바드에서』).

본 문제에서는 질 들뢰즈의 영화철학 개념 체계를 전산학적으로 추상화한 **들뢰즈 시네마 운동-이미지 vs 시간-이미지 분류 및 결정 회로 분석 엔진(Deleuzian Cinema Movement-Time Image Engine)**을 구축합니다.

---

## 입력 형식

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "film_scenes": [
    {
      "scene_id": "SCENE_STAGECOACH_1939",
      "historical_epoch": 1939,
      "sensory_stimulus_intensity": 0.90,
      "motor_action_response": 0.95,
      "space_definition": "organic",
      "character_role": "actor",
      "virtual_reflection_ratio": 0.05,
      "tags": ["western", "duel", "ford"]
    },
    {
      "scene_id": "SCENE_BICYCLE_THIEVES_1948",
      "historical_epoch": 1948,
      "sensory_stimulus_intensity": 0.85,
      "motor_action_response": 0.05,
      "space_definition": "any_space_whatever",
      "character_role": "seer",
      "virtual_reflection_ratio": 0.20,
      "tags": ["neorealism", "rome", "stolen"]
    }
  ],
  "cinematic_queries": [
    {
      "query_id": "Q_ACTION_REGIME",
      "target_scene_id": "SCENE_STAGECOACH_1939",
      "sms_rupture_threshold": 0.40,
      "crystal_threshold": 0.50
    }
  ],
  "engine_params": {
    "neorealism_sensitivity": 1.0
  }
}
```

### 필드 상세 설명
1. `film_scenes` (배열): 분석할 영화 씬 목록
   - `scene_id` (문자열): 씬 고유 식별자
   - `historical_epoch` (정수): 영화 제작 연도 (예: 1939, 1948, 1961 등)
   - `sensory_stimulus_intensity` (실수): 상황이 인물에게 가하는 감각적 자극 강도 ($0.0 \le S \le 1.0$)
   - `motor_action_response` (실수): 인물의 물리적 운동 행위 반응 강도 ($0.0 \le A \le 1.0$)
   - `space_definition` (문자열): 공간 유형 (`"organic"` [목적 지향적 유기적 공간], `"any_space_whatever"` [탈연결된 폐허/공터])
   - `character_role` (문자열): 인물 역할 (`"actor"` [행위자], `"seer"` [보는 자/목격자])
   - `virtual_reflection_ratio` (실수): 회상/환영 등 가상적 이미지의 침투 비율 ($0.0 \le V \le 1.0$)
   - `tags` (문자열 배열): 키워드 태그
2. `cinematic_queries` (배열): 특정 씬에 대한 들뢰즈주의적 비평 분석 질의
   - `query_id` (문자열): 질의 식별자
   - `target_scene_id` (문자열): 분석 대상 씬 ID
   - `sms_rupture_threshold` (실수): 감각-운동 도식 파열 판정 임계값
   - `crystal_threshold` (실수): 결정 회로 활성화 임계값
3. `engine_params` (객체):
   - `neorealism_sensitivity` (실수): 2차 대전 이후(1945년 이후) 단절 가중치 계수 ($M_{neo} \ge 0.1$)

---

## 엔진 처리 규칙 및 연산 공식

### 1. 씬별 감각-운동 도식 및 단절도 연산
각 씬 $sc$에 대해:
- **감각-운동 결합도 (SMS Coupling)**:
  $$SMS_{coupling} = \text{round}(S \times A, 4)$$
- **기초 단절도 (Base Rupture)**:
  자극은 강하나 운동 행위가 억제될수록 단절이 심화됩니다:
  $$\text{base\_rupture} = S \times (1.0 - A)$$
- **수정자(Modifiers) 가산**:
  - `character_role == "seer"`인 경우: $+0.20$ 가산 (보는 자는 행동하지 않음)
  - `space_definition == "any_space_whatever"`인 경우: $+0.15$ 가산 (어떤-공간이든은 방향성을 상실함)
  - `historical_epoch >= 1945`인 경우: $+(0.10 \times \text{neorealism\_sensitivity})$ 가산 (전후 세계의 실존적 파국)
- **최종 파열 지수 (Rupture Score)**:
  $$\text{rupture\_score} = \text{round}(\min(1.0, \max(0.0, \text{base\_rupture} + \text{modifiers})), 4)$$

### 2. 공간 엔트로피 지수 (Any-Space-Whatever Index)
- `space_definition == "any_space_whatever"`인 경우:
  $$ASW_{index} = \text{round}(\min(1.0, 0.60 + 0.40 \times \text{rupture\_score}), 4)$$
- 그렇지 않은 경우 (`"organic"`):
  $$ASW_{index} = \text{round}(\max(0.0, 0.40 \times (1.0 - SMS_{coupling})), 4)$$

### 3. 결정 회로 역능 (Crystal Circuit Potency)
- 가상적 이미지 비율 $V$와 파열 지수의 상호 상승 작용:
  $$\text{crystal\_potency} = \text{round}(V \times \text{rupture\_score}, 4)$$
- **결정 형성 여부**: $\text{crystal\_potency} \ge 0.30$ 이면 `is_crystal_formed = true`, 아니면 `false`.

### 4. 이미지 레짐(Regime) 및 하위 유형(Subtype) 분류
- **`rupture_score >= 0.50`** 인 경우 $\to$ **`TIME_IMAGE` (시간-이미지)**
  - $\text{is\_crystal\_formed} == \text{true}$ 이거나 $V \ge 0.60$ 이면: `"CRYSTAL_IMAGE"` (결정-이미지)
  - 그렇지 않고 $V \ge 0.30$ 이면: `"CHRONOSIGN_SHEET_OF_PAST"` (과거의 지층 크로노사인)
  - 그렇지 않으면: `"OPSIGN_SONSIGN_PURE_PERCEPTION"` (순수 시각상/청각상)
- **`rupture_score < 0.50`** 인 경우 $\to$ **`MOVEMENT_IMAGE` (운동-이미지)**
  - $A \ge 0.70$ 이면: `"ACTION_IMAGE"` (행동-이미지)
  - 그렇지 않고 $S \ge 0.70$ 이고 $A \le 0.30$ 이면: `"AFFECTION_IMAGE"` (정동-이미지)
  - 그렇지 않으면: `"PERCEPTION_IMAGE"` (지각-이미지)

### 5. 질의 평가 (Cinematic Queries Evaluation)
각 질의 $q$에 대해:
- 대상 씬이 없으면:
  `{"query_id": q["query_id"], "target_scene_id": tsid, "status": "SCENE_NOT_FOUND"}`
- 대상 씬이 존재하면:
  - `is_sms_ruptured`: $\text{rupture\_score} \ge q[\text{sms\_rupture\_threshold}]$
  - `is_crystal_circuit_active`: $\text{crystal\_potency} \ge q[\text{crystal\_threshold}]$
  - `philosophical_analysis`: `f"Scene '{tsid}' operates in {image_type} regime ({subtype})"`

### 6. 전체 영화 레짐 요약 (Dominant Regime Verdict)
- 전체 씬들의 `movement_image_count`, `time_image_count`, `crystal_image_count`를 집계합니다.
- `dominant_regime`:
  - `time_image_count > movement_image_count`: `"MODERN_POSTWAR_TIME_CINEMA"`
  - `time_image_count == movement_image_count`: `"TRANSITIONAL_HYBRID_CINEMA"`
  - `time_image_count < movement_image_count`: `"CLASSICAL_PREWAR_MOVEMENT_CINEMA"`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마를 갖는 단일 JSON 객체를 압축 공백 없이 출력합니다 (`json.dumps(..., separators=(',', ':'))`).

```json
{
  "scene_analysis": [
    {
      "scene_id": "SCENE_STAGECOACH_1939",
      "epoch": 1939,
      "sms_coupling": 0.855,
      "rupture_score": 0.045,
      "asw_index": 0.058,
      "crystal_circuit_potency": 0.0023,
      "is_crystal_formed": false,
      "image_type": "MOVEMENT_IMAGE",
      "subtype": "ACTION_IMAGE"
    }
  ],
  "cinematic_queries_evaluated": [
    {
      "query_id": "Q_ACTION_REGIME",
      "target_scene_id": "SCENE_STAGECOACH_1939",
      "status": "SUCCESS",
      "image_type": "MOVEMENT_IMAGE",
      "subtype": "ACTION_IMAGE",
      "rupture_score": 0.045,
      "is_sms_ruptured": false,
      "crystal_potency": 0.0023,
      "is_crystal_circuit_active": false,
      "philosophical_analysis": "Scene 'SCENE_STAGECOACH_1939' operates in MOVEMENT_IMAGE regime (ACTION_IMAGE)"
    }
  ],
  "deleuzian_regime_summary": {
    "total_scenes": 1,
    "movement_image_count": 1,
    "time_image_count": 0,
    "crystal_image_count": 0,
    "dominant_regime": "CLASSICAL_PREWAR_MOVEMENT_CINEMA"
  }
}
```

---

## 제약 사항

- $1 \le |\text{film\_scenes}| \le 50$
- $1 \le |\text{cinematic\_queries}| \le 30$
- $1895 \le \text{historical\_epoch} \le 2030$
- 모든 확률/비율 파라미터는 $[0.0, 1.0]$ 범위
- 시간 복잡도: $O(N + Q)$ 이내로 즉시 연산 완료되어야 합니다.
- 공간 복잡도: $O(N + Q)$ 이내.
