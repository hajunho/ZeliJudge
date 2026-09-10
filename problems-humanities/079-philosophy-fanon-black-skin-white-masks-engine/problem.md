# 프란츠 파농의 검은 피부, 하얀 가면: 식민주의적 소외, 표피화(Epidermalization) 및 탈소외 실천 엔진 (Frantz Fanon's Black Skin, White Masks: Colonial Alienation, Epidermalization & Disalienation Engine)

## 문제 설명

20세기 중반 탈식민주의(Post-colonialism) 및 정신의학의 독보적 사상가 **프란츠 파농(Frantz Fanon, 1925~1961)**은 1952년 고전 『검은 피부, 하얀 가면(Peau noire, masques blancs)』을 통해 제국주의와 식민 지배가 피식민자의 내면과 신체에 남긴 정신적 트라우마와 실존적 소외(Alienation)를 정신분석학적으로 해부했습니다.

파농은 식민주의가 단순한 군사적·경제적 지배에 그치지 않고, 피식민자의 주관적 자아 구조를 근본적으로 왜곡한다고 보았습니다. 백인 지배 사회의 객체화하는 시선(**"저기 봐, 깜둥이야!(Tiens, un nègre!)"**) 아래에서 흑인의 신체는 살아 숨 쉬는 주체적 신체 도식(Corporeal Schema)을 박탈당하고, 피부색이라는 생물학적 기표로 고정되는 **인종적 표피 도식(Historial-Racial / Epidermal Schema)**으로 붕괴합니다(**표피화, Epidermalization**). 

이에 피식민 주체는 식민자의 언어(프랑스어)를 유창하게 구사하고 지배자의 문화를 모방(Mimicry)함으로써 열등감을 지우고 '하얀 가면'을 쓰려는 충동(**유백화/락티피카시옹, Lactification**)에 사로잡히지만, 지배자는 그를 결코 동등한 주체로 인정하지 않습니다. 결국 피식민자는 자아 분열과 신경증(Colonial Neurosis)의 나락으로 떨어집니다. 헤겔의 주노 변증법에서 주인이 노예에게 '인정'을 갈구하지 않는 식민지적 단절 속에서, 파농은 거짓 가면을 벗어던지고 역사적 주체로서 혁명적 실천(**Decolonial Praxis**)을 감행하는 자만이 비로소 진정한 **탈소외(Disalienation)**와 보편적 인간주의를 쟁취할 수 있음을 선언합니다.

당신은 문화비평 및 정신의학적 시뮬레이션 엔지니어로서, **표피화 지수($EpidermalIndex$), 하얀 가면 모방 신경증($NeurosisIndex$), 식민지적 상호 인정 결손($MutualRecognition$), 그리고 혁명적 탈소외 지수($DisalienationScore$)를 추적하고 주체의 실존적 상태($ExistentialState$) 전이를 판정하는 시뮬레이션 엔진**을 구축해야 합니다.

```
+-------------------------------------------------------------------------+
|      Frantz Fanon: Black Skin, White Masks Psycho-Social Engine         |
+-------------------------------------------------------------------------+
| [Colonial Social Order / The White Gaze]                                |
|  - "Look, a Negro!" (Interpellation & Racial Stereotype)                |
|  - Epidermalization: Corporeal Schema ---> Historical-Racial Schema     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Colonized Internal Psyche / The Trap of Mimicry]                       |
|  - Inferiority Complex & Lactification Impulse (Adopt White Mask)       |
|  - Linguistic Assimilation (Metropolitan French Diction)                |
|  - Self-Suppression of Indigenous Identity                              |
|  - Master's Rejection ---> Colonial Neurosis (Severe Internal Splitting)|
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Path of Disalienation / Revolutionary Action]                          |
|  - Critical Consciousness: Shattering the Hegelian Colonial Impasse     |
|  - Stripping the White Mask (Unmasking & Demystification)               |
|  - Decolonial Praxis: Universal Human Solidarity & Existential Freedom  |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 주체 상태 파라미터 (`config`)
- `subject_id`: 피식민 주체 식별자 (문자열)
- `initial_corporeal_autonomy`: 초기 주체적 신체 자율성 $A_{corp} \in [0.0, 1.0]$
- `initial_white_mask`: 초기 하얀 가면 모방 수준 $M_{white} \in [0.0, 1.0]$
- `initial_self_suppression`: 초기 본래적 정체성 억압도 $R_{self} \in [0.0, 1.0]$
- `initial_linguistic_assimilation`: 초기 지배 언어 동화율 $L_{assim} \in [0.0, 1.0]$
- `initial_praxis`: 초기 탈식민 실천 참여도 $Praxis \in [0.0, 1.0]$
- `master_acceptance_level`: 백인 지배자의 피식민자 인정도 $Acceptance_{master} \in [0.0, 1.0]$ (식민 체제 특성상 기본 $0.05 \sim 0.10$ 수준)

모든 파라미터는 매 단계 $[0.0, 1.0]$ 범위로 클램핑됩니다.

### 2. 핵심 지표 계산 수식

1. **표피화 지수 ($EpidermalIndex$)**:
   - 주체적 신체 도식이 붕괴되고 피부색 기표로 환원되는 정도:
     $$EpidermalIndex = \min\left(1.0, (1.0 - A_{corp}) 	imes 0.7 + R_{self} 	imes 0.3ight)$$
2. **식민지적 신경증 지수 ($NeurosisIndex$)**:
   - 하얀 가면을 썼음에도 지배자에게 인정받지 못하는 간극과 자아 억압 동화의 마찰:
     $$UnmaskGap = M_{white} 	imes (1.0 - Acceptance_{master})$$
     $$AssimFriction = R_{self} 	imes L_{assim}$$
     $$NeurosisIndex = \min\left(1.0, UnmaskGap 	imes 0.65 + AssimFriction 	imes 0.35ight)$$
3. **상호 인정 지표 ($MutualRecognition$)**:
   - 식민주의에서는 주인이 노예에게 노동만을 요구하고 인정을 갈망하지 않으므로 구조적 결손이 발생:
     $$MutualRecognition = \max\left(0.0, M_{white} 	imes Acceptance_{master} - 0.15ight)$$
4. **탈소외 지수 ($DisalienationScore$)**:
   - 표피적 굴레 극복, 탈식민 저항 실천, 허구적 백인 가면의 탈피:
     $$Unmasking = 1.0 - M_{white}$$
     $$DisalienationScore = \min\left(1.0, \max\left(0.0, (1.0 - EpidermalIndex) 	imes 0.35 + Praxis 	imes 0.45 + Unmasking 	imes 0.20ight)ight)$$
   (모든 계산값은 소수점 4자리로 반올림)

### 3. 실존적 상태 ($ExistentialState$) 판정 우선순위
1. $DisalienationScore \ge 0.70$ 이고 $Praxis \ge 0.60$: **`"LIBERATED_HUMAN"`** (탈소외를 쟁취한 진정한 보편적 인간)
2. $NeurosisIndex \ge 0.60$: **`"COLONIAL_NEUROSIS"`** (하얀 가면의 파탄으로 인한 식민지 신경증)
3. $EpidermalIndex \ge 0.65$: **`"EPIDERMALIZED_OBJECT"`** (타자의 시선에 의해 피부색으로 물화된 객체)
4. $M_{white} \ge 0.50$: **`"MIMICRY_ALIENATION"`** (지배자를 모방하며 자아를 분실한 모방 소외)
5. 그 외: **`"ALIENATED_SUBJECT"`** (식민지 체제 속의 일반적 소외 주체)

### 4. 시뮬레이션 이벤트 액션
- `COLONIAL_GAZE` (식민자의 객체화 시선, 강도 $I$):
  - $A_{corp} \leftarrow \max(0.0, A_{corp} - I 	imes 0.4)$
  - $R_{self} \leftarrow \min(1.0, R_{self} + I 	imes 0.25)$
- `ADOPT_WHITE_MASK` (하얀 가면 착용/유백화 충동, 강도 $I$):
  - $M_{white} \leftarrow \min(1.0, M_{white} + I 	imes 0.35)$
  - $L_{assim} \leftarrow \min(1.0, L_{assim} + I 	imes 0.4)$
  - $R_{self} \leftarrow \min(1.0, R_{self} + I 	imes 0.3)$
- `MASTER_REJECTION` (지배자의 배제 및 거부, 강도 $I$):
  - $Acceptance_{master} \leftarrow \max(0.0, Acceptance_{master} - I 	imes 0.2)$
  - $R_{self} \leftarrow \min(1.0, R_{self} + I 	imes 0.2)$
- `CRITICAL_CONSCIOUSNESS` (비판적 의식 각성, 강도 $I$):
  - $M_{white} \leftarrow \max(0.0, M_{white} - I 	imes 0.3)$
  - $A_{corp} \leftarrow \min(1.0, A_{corp} + I 	imes 0.3)$
  - $Praxis \leftarrow \min(1.0, Praxis + I 	imes 0.2)$
- `DECOLONIAL_PRAXIS` (탈식민 해방 실천, 강도 $I$):
  - $Praxis \leftarrow \min(1.0, Praxis + I 	imes 0.45)$
  - $M_{white} \leftarrow \max(0.0, M_{white} - I 	imes 0.4)$
  - $R_{self} \leftarrow \max(0.0, R_{self} - I 	imes 0.35)$
  - $A_{corp} \leftarrow \min(1.0, A_{corp} + I 	imes 0.35)$

---

## 입력 형식

표준 입력(`sys.stdin`)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "subject_id": "MARTINIQUE_STUDENT_01",
    "initial_corporeal_autonomy": 0.7,
    "initial_white_mask": 0.2,
    "initial_self_suppression": 0.2,
    "initial_linguistic_assimilation": 0.3,
    "initial_praxis": 0.0,
    "master_acceptance_level": 0.1
  },
  "events": [
    {"action": "COLONIAL_GAZE", "intensity": 0.5}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 공백 없는 압축 JSON(`separators=(',', ':')`)을 출력합니다:
```json
{
  "final_metrics": {
    "disalienation_score": 0.3534,
    "epidermal_index": 0.446,
    "existential_state": "ALIENATED_SUBJECT",
    "mutual_recognition": 0.0,
    "neurosis_index": 0.1388
  },
  "parameters": {
    "corporeal_autonomy": 0.5,
    "linguistic_assimilation": 0.3,
    "praxis_action": 0.0,
    "self_suppression": 0.325,
    "white_mask_level": 0.2
  },
  "subject_id": "MARTINIQUE_STUDENT_01",
  "trajectory": [
    {
      "disalienation_score": 0.379,
      "epidermal_index": 0.27,
      "event": "INIT",
      "existential_state": "ALIENATED_SUBJECT",
      "mutual_recognition": 0.0,
      "neurosis_index": 0.138
    },
    {
      "disalienation_score": 0.3534,
      "epidermal_index": 0.446,
      "event": "COLONIAL_GAZE",
      "existential_state": "ALIENATED_SUBJECT",
      "mutual_recognition": 0.0,
      "neurosis_index": 0.1388,
      "step": 1
    }
  ]
}
```
