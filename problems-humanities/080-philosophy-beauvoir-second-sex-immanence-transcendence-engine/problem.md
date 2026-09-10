# 시몬 드 보부아르의 제2의 성: 타자로서의 여성, 내재성 대 초월성 및 실존적 해방 엔진 (Simone de Beauvoir's The Second Sex: Woman as Other, Immanence vs Transcendence Engine)

## 문제 설명

20세기 현대 철학 및 페미니즘 이론의 가장 찬란한 금자탑을 쌓은 **시몬 드 보부아르(Simone de Beauvoir, 1908~1986)**는 1949년 기념비적 명저 『제2의 성(Le Deuxième Sexe)』에서 인간 조건에 대한 실존주의적 통찰을 성(Gender)의 영역으로 확장했습니다.

> **"여성은 태어나는 것이 아니라, 만들어지는 것이다." (On ne naît pas femme: on le devient.)**

보부아르는 인류 역사 전체를 관통하는 남성 중심 가부장제 질서의 본질을 **'비대칭적 타자화(Asymmetrical Othering)'**로 규명했습니다:
- 남성은 인류의 보편적 기준이자 자율적 **주체(The One / Subject)**로 자신을 정립합니다.
- 반면 여성은 오직 남성과의 관계 속에서만 규정되는 부차적이고 결핍된 **타자(The Other)**로 전락합니다.
- 실존주의에서 모든 참된 인간은 능동적으로 미래를 향해 자신을 기투(Project)하는 **'초월성(Transcendence)'**을 추구해야 합니다. 그러나 가부장제는 여성을 끝없이 반복되는 가사 노동, 육체적 치장, 수동성의 닫힌 원환인 **'내재성(Immanence)'**의 굴레에 감금합니다.
- 나아가 보부아르는 피억압자가 가부장적 보호와 안락함이라는 달콤한 유혹에 굴복하여 스스로 자유와 초월을 포기하는 **자기기만과 공모(Bad Faith / Mauvaise Foi)**의 실존적 위험을 냉철하게 경고합니다.

진정한 해방은 생물학적 환원주의나 수동적 피해자성에 안주하는 것이 아니라, **경제적 자립(Economic Autonomy)과 창조적 기투(Existential Project)**를 통해 내재성의 장벽을 부수고, 남성과 여성이 상호 동등한 자유로운 주체로 마주하는 **상호 주체성(Reciprocal Intersubjectivity)**을 회복하는 것입니다.

당신은 철학적 인문 컴퓨팅 연구원으로서, **타자화 지수($OtherIndex$), 내재성 감금도($CaptivityScore$), 실존적 해방 지수($LiberationScore$)를 추적하고 주체의 실존적 상태($ExistentialState$) 전이를 판정하는 시몬 드 보부아르 실존주의 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|     Simone de Beauvoir: The Second Sex Existentialist Engine            |
+-------------------------------------------------------------------------+
| [Patriarchal Symbolic Order / Asymmetrical Othering]                   |
|   - Man = The Sovereign Subject / Universal Measure                    |
|   - Woman = The Absolute Other (Relative, Inessential, Lacking)         |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Immanence vs Transcendence / The Trap of Bad Faith]                    |
|   - Immanence (Enclosure in Repetitive Domestic Spheres & Passivity)    |
|   - Temptation of Bad Faith (Trading Existential Freedom for Protection)|
|   - Captivity in Immanence ---> Existential Mutilation                  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [The Path to Sovereign Freedom: Transcendence & Project]                |
|   - Economic Autonomy (Independent Livelihood & Self-Sufficiency)       |
|   - Creative & Existential Projects (Hurling Oneself into the Future)   |
|   - Reciprocal Intersubjectivity: Mutual Recognition of Free Freedoms   |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 주체 상태 파라미터 (`config`)
- `subject_id`: 여성 주체 식별자 (문자열)
- `initial_immanence`: 초기 가부장적 내재성 감금 수준 $I_{imm} \in [0.0, 1.0]$
- `initial_transcendence`: 초기 주체적 미래 기투 및 초월성 수준 $T_{trans} \in [0.0, 1.0]$
- `initial_economic_autonomy`: 초기 경제적 자립도 $A_{econ} \in [0.0, 1.0]$
- `initial_bad_faith`: 초기 안락한 보호에 안주하는 자기기만/공모도 $C_{bad} \in [0.0, 1.0]$
- `initial_patriarchal_pressure`: 초기 가부장제 타자화 규범 압력 $P_{other} \in [0.0, 1.0]$

모든 파라미터는 매 단계 $[0.0, 1.0]$ 범위로 엄격히 클램핑됩니다.

### 2. 핵심 지표 계산 수식

1. **타자화 지수 ($OtherIndex$)**:
   - 주체적 독립성이 박탈되고 남성의 상대적 타자로 규정되는 정도:
     $$OtherIndex = \min\left(1.0, P_{other} 	imes (1.0 - A_{econ}) 	imes 0.6 + I_{imm} 	imes 0.4ight)$$
2. **내재성 감금도 ($CaptivityScore$)**:
   - 미래로의 초월이 차단되고 반복적 수동성의 원환에 갇힌 척도:
     $$CaptivityScore = \min\left(1.0, I_{imm} 	imes (1.0 - T_{trans}) + C_{bad} 	imes 0.3ight)$$
3. **실존적 해방 지수 ($LiberationScore$)**:
   - 주체적 기투, 경제적 자립, 타자화 극복 및 자기기만 청산의 결합:
     $$Score = T_{trans} 	imes 0.45 + A_{econ} 	imes 0.35 + (1.0 - OtherIndex) 	imes 0.20 - C_{bad} 	imes 0.15$$
     $$LiberationScore = \min\left(1.0, \max\left(0.0, Scoreight)ight)$$
   (모든 계산값은 소수점 4자리로 반올림)

### 3. 실존적 상태 ($ExistentialState$) 판정 우선순위
1. $LiberationScore \ge 0.70$ 이고 $T_{trans} \ge 0.60$: **`"SOVEREIGN_SUBJECT"`** (내재성을 극복하고 초월을 성취한 주권적 주체)
2. $CaptivityScore \ge 0.65$: **`"CONFINED_IMMANENCE"`** (가사 노동과 수동성의 내재성에 갇힌 상태)
3. $OtherIndex \ge 0.65$: **`"ABSOLUTE_OTHER"`** (가부장적 규범에 의해 절대적 타자로 물화된 존재)
4. $C_{bad} \ge 0.50$: **`"COMPLICIT_BAD_FAITH"`** (보호와 안락함을 대가로 자유를 포기한 자기기만 상태)
5. 그 외: **`"BECOMING_WOMAN"`** (생성 중인 실존적 주체 - "여성은 태어나는 것이 아니라 만들어지는 것이다")

### 4. 시뮬레이션 이벤트 액션
- `PATRIARCHAL_ENFORCEMENT` (가부장적 규범 강제, 강도 $I$):
  - $P_{other} \leftarrow \min(1.0, P_{other} + I 	imes 0.3)$
  - $I_{imm} \leftarrow \min(1.0, I_{imm} + I 	imes 0.25)$
- `DOMESTIC_CONFINEMENT` (가정 내 감금 및 수동화, 강도 $I$):
  - $I_{imm} \leftarrow \min(1.0, I_{imm} + I 	imes 0.35)$
  - $T_{trans} \leftarrow \max(0.0, T_{trans} - I 	imes 0.3)$
- `BAD_FAITH_SURRENDER` (자기기만적 굴복과 공모, 강도 $I$):
  - $C_{bad} \leftarrow \min(1.0, C_{bad} + I 	imes 0.4)$
  - $A_{econ} \leftarrow \max(0.0, A_{econ} - I 	imes 0.25)$
- `ECONOMIC_INDEPENDENCE` (경제적 독립 쟁취, 강도 $I$):
  - $A_{econ} \leftarrow \min(1.0, A_{econ} + I 	imes 0.45)$
  - $P_{other} \leftarrow \max(0.0, P_{other} - I 	imes 0.25)$
  - $C_{bad} \leftarrow \max(0.0, C_{bad} - I 	imes 0.3)$
- `EXISTENTIAL_PROJECT` (실존적 미래 기투 및 창조, 강도 $I$):
  - $T_{trans} \leftarrow \min(1.0, T_{trans} + I 	imes 0.5)$
  - $I_{imm} \leftarrow \max(0.0, I_{imm} - I 	imes 0.4)$
  - $C_{bad} \leftarrow \max(0.0, C_{bad} - I 	imes 0.35)$
- `RECIPROCAL_SOLIDARITY` (상호 주체성 연대, 강도 $I$):
  - $P_{other} \leftarrow \max(0.0, P_{other} - I 	imes 0.35)$
  - $T_{trans} \leftarrow \min(1.0, T_{trans} + I 	imes 0.25)$

---

## 입력 형식

표준 입력(`sys.stdin`)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "subject_id": "YOUNG_STUDENT_PARIS_01",
    "initial_immanence": 0.4,
    "initial_transcendence": 0.3,
    "initial_economic_autonomy": 0.3,
    "initial_bad_faith": 0.1,
    "initial_patriarchal_pressure": 0.5
  },
  "events": [
    {"action": "PATRIARCHAL_ENFORCEMENT", "intensity": 0.4}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 공백 없는 압축 JSON(`separators=(',', ':')`)을 출력합니다:
```json
{
  "final_metrics": {
    "captivity_score": 0.38,
    "existential_state": "BECOMING_WOMAN",
    "liberation_score": 0.3329,
    "other_index": 0.4604
  },
  "parameters": {
    "bad_faith_complicity": 0.1,
    "economic_autonomy": 0.3,
    "immanence_level": 0.5,
    "patriarchal_pressure": 0.62,
    "transcendence_project": 0.3
  },
  "subject_id": "YOUNG_STUDENT_PARIS_01",
  "trajectory": [
    {
      "captivity_score": 0.31,
      "event": "INIT",
      "existential_state": "BECOMING_WOMAN",
      "liberation_score": 0.366,
      "other_index": 0.37,
      "step": 0
    },
    {
      "captivity_score": 0.38,
      "event": "PATRIARCHAL_ENFORCEMENT",
      "existential_state": "BECOMING_WOMAN",
      "liberation_score": 0.3329,
      "other_index": 0.4604,
      "step": 1
    }
  ]
}
```
