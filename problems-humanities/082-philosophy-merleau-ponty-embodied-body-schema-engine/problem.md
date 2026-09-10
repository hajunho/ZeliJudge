# 모리스 메를로-퐁티의 지각의 현상학: 신체-주체, 신체 도식 및 지향적 호(Intentional Arc) 엔진

## 문제 설명

근대 서구 철학은 데카르트(René Descartes)의 심신이원론 이래로 인간을 생각하는 정신인 **사유 실체(Res Cogitans)**와 물질적 기계에 불과한 **연장 실체(Res Extensa)**로 분리했습니다. 이에 따르면 신체는 영혼이 탑승한 기계이거나, 외부 자극을 수동적으로 수용하는 감각 수용기에 불과했습니다.

프랑스의 대표적 현상학자 **모리스 메를로-퐁티(Maurice Merleau-Ponty, 1908~1961)**는 1945년 불후의 주저 **『지각의 현상학(Phénoménologie de la perception)』**을 통해, 지성주의(Intellectualism)와 경험주의(Empiricism) 양쪽의 맹점을 통렬히 비판하며 **"신체-주체(Body-Subject / Le Corps Propre)"** 개념을 정립했습니다:

1. **살아있는 신체(The Lived Body / Le Corps Propre)**:
   - 신체는 객관적으로 관찰되는 대상(Object)이 아니라, 세계를 경험하고 주재하는 주체성 그 자체입니다. "나는 내 신체를 소유하는 것이 아니라, 바로 내 신체이다(Je suis mon corps)."
2. **신체 도식(Body Schema / Schéma Corporel) vs 신체 표상(Body Image)**:
   - 신체 표상이 거울에 비친 내 모습을 머릿속으로 떠올리는 반성적 표상이라면, **신체 도식**은 불을 끄고도 스위치로 손이 가고, 계단을 오를 때 발의 위치를 계산하지 않는 **전반성적(Pre-reflective)이고 즉각적인 운동 역량**입니다. 데카르트의 "나는 생각한다(Cogito / I think)"에 맞서 메를로-퐁티는 실존의 근원을 **"나는 할 수 있다(I can)"의 운동 지향성(Motor Intentionality)**에 둡니다.
3. **지향적 호(Intentional Arc / L'arc intentionnel)**:
   - 인간의 삶을 지탱하는 보이지 않는 텐션입니다. 이것은 과거의 침전된 습관, 현재의 지각적 상황, 미래의 실천적 기투를 하나의 유기적 연속체로 엮어냅니다. 뇌 손상으로 지향적 호가 끊어진 **슈나이더 증례(Schneider's Case)** 환자는 모기에 물린 곳을 긁는 일상적 구체적 운동은 가능하지만, 군대식 경례나 지시받은 추상적 자세를 취하려면 시각적으로 신체를 일일이 확인해야 하는 인지적 분절을 겪습니다.
4. **최적 게슈탈트 파악(Optimum Grip / Prise Maximale)**:
   - 신체는 대상을 가장 명료하고 조화롭게 파악하기 위해 환경과의 거리와 각도를 스스로 조절하며 긴장을 해소합니다(미술관에서 그림을 감상하기 위해 무의식적으로 발걸음을 옮겨 최적의 거리에 서는 현상).
5. **도구의 신체화(Incorporation of Tools)**:
   - 시각장애인의 지팡이, 타이피스트의 키보드, 바이올리니스트의 활은 외부 사물이 아니라 신체 도식의 연장으로 체화(Embody)됩니다.

당신은 인지과학, HCI, 로보틱스 및 철학적 컴퓨팅 연구원으로서, **메를로-퐁티의 신체 도식, 지향적 호 지수($IAI$), 최적 게슈탈트 파악도($OGS$), 살아있는 신체성($LBI$) 및 데카르트적 소외도($CAI$)를 추적하고 신체-주체의 실존 상태($EmbodiedState$) 전이를 판정하는 지각 현상학 시뮬레이션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|      Maurice Merleau-Ponty: Embodied Cognition & Intentional Arc        |
+-------------------------------------------------------------------------+
| [The Lived Body / Le Corps Propre]                                      |
|   - Pre-reflective Motor Intentionality ("I can")                       |
|   - Habitual Sedimentation (Sedimented Skills in Flesh)                 |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Intentional Arc (L'arc intentionnel)]                                  |
|   - Binding Past Habits, Present Perception & Future Practical Projects |
|   - Tension of Optimal Grip (Perception-Action Coupling)                |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Embodied State Machine]                                                |
|   - OPTIMUM_EMBODIED_GRIP: Flawless Perceptual-Action Harmony           |
|   - PRE_REFLECTIVE_ACTION: Everyday Unreflective Coping                 |
|   - CARTESIAN_DISCORD: Intellectualist Alienation (Mind vs Body)        |
|   - INTENTIONAL_ARC_RUPTURE: Severe Break of Motor-Perceptual Tension   |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 주체 상태 파라미터 (`config`)
- `subject_id`: 주체 식별자 (문자열)
- `sensory_motor_coupling`: 감각-운동 결합도 $\alpha \in [0.0, 1.0]$
- `habitual_sedimentation`: 습관의 침전도 $\beta \in [0.0, 1.0]$ (신체에 각인된 숙련도)
- `motor_intentionality`: 운동 지향성 $M \in [0.0, 1.0]$ ("나는 할 수 있다"의 실천 역량)
- `environmental_affordance`: 환경적 어포던스/행동 유도성 $A \in [0.0, 1.0]$
- `spatial_situatedness`: 상황적 공간성 $S \in [0.0, 1.0]$

모든 수치는 $[0.0, 1.0]$ 범위로 클램핑(`clamp`)되며, 결과 지표는 소수점 4자리로 반올림합니다.

### 2. 핵심 지표 산출 공식

1. **지향적 호 지수 (Intentional Arc Index: $IAI$)**:
   과거의 습관($\beta$), 감각-운동 결합($\alpha$), 현재의 운동 지향성($M$), 공간 상황($S$)이 하나로 엮인 긴장도:
   $$IAI = \text{clamp}\left(\alpha \times M \times \frac{1.0 + \beta}{2.0} + 0.1 \times S,\, 0.0,\, 1.0\right)$$

2. **최적 게슈탈트 파악도 (Optimum Grip Score: $OGS$)**:
   신체의 지향적 운동 능력($M \times \alpha$)과 환경 어포던스($A$)의 불일치를 습관($\beta$)의 보정으로 극복하여 획득하는 최적 명료도:
   $$\Delta = |M \times \alpha - A|$$
   $$OGS = \text{clamp}\left(1.0 - \Delta \times (1.0 - 0.4 \times \beta),\, 0.0,\, 1.0\right)$$

3. **살아있는 신체성 지수 (Lived Body Index: $LBI$)**:
   지향적 호와 최적 파악도의 조화로운 가중 결합:
   $$LBI = \text{clamp}(0.5 \times IAI + 0.5 \times OGS,\, 0.0,\, 1.0)$$

4. **데카르트적 소외 지수 (Cartesian Alienation Index: $CAI$)**:
   신체가 주체성을 잃고 도구적 기계나 객체로 대상화되는 정도:
   $$CAI = \text{clamp}(1.0 - LBI,\, 0.0,\, 1.0)$$

### 3. 신체-주체 실존 상태 (`embodied_state`) 전이 조건

우선순위에 따라 상태를 판정합니다:
1. `INTENTIONAL_ARC_RUPTURE`:
   - 조건: $IAI < 0.35$ 또는 $M < 0.30$
   - 판정: 지향적 호가 끊어져 신체가 분절되고 추상적 운동 능력을 상실한 병리적 단절 상태(슈나이더 증례).
2. `OPTIMUM_EMBODIED_GRIP`:
   - 조건: $LBI \ge 0.75$ 이고 $OGS \ge 0.70$
   - 판정: 신체와 세계가 완벽히 일체화되어 최고의 숙련도와 명료성으로 대상과 상호작용하는 최적 파악 상태.
3. `PRE_REFLECTIVE_ACTION`:
   - 조건: $LBI \ge 0.50$
   - 판정: 계산 없이 자연스럽게 신체 도식이 작동하는 일상적 체화 실천 상태.
4. `CARTESIAN_DISCORD`:
   - 조건: 위 세 조건에 해당하지 않는 모든 경우 (기본적으로 $CAI \ge 0.50$)
   - 판정: 정신과 신체가 분리되어 자신의 신체를 낯설게 느끼고 반성적 사고로 조작하려는 데카르트적 불화 상태.

### 4. 동적 실천 행동 (`actions`)

각 행동은 주체의 파라미터를 점진적으로 변화시킵니다:
- `PERCEPTUAL_EXPLORATION` (지각 탐색):
  - 인자: `intensity` (기본 0.5), `target_affordance`, `target_spatial`
  - 변화:
    - $A \leftarrow \text{clamp}(A + (\text{target\_affordance} - A) \times \text{intensity} \times 0.5)$
    - $S \leftarrow \text{clamp}(S + (\text{target\_spatial} - S) \times \text{intensity} \times 0.5)$
    - $\alpha \leftarrow \text{clamp}(\alpha + 0.05 \times \text{intensity})$
- `MOTOR_HABIT_PRACTICE` (운동 습관 훈련):
  - 인자: `intensity`
  - 변화:
    - $\beta \leftarrow \text{clamp}(\beta + 0.15 \times \text{intensity})$
    - $M \leftarrow \text{clamp}(M + 0.12 \times \text{intensity})$
    - $\alpha \leftarrow \text{clamp}(\alpha + 0.08 \times \text{intensity})$
- `ENVIRONMENTAL_DISTURBANCE` (환경 교란 / 외상 충격):
  - 인자: `severity` (기본 0.5)
  - 변화:
    - $M \leftarrow \text{clamp}(M - 0.25 \times \text{severity})$
    - $\alpha \leftarrow \text{clamp}(\alpha - 0.20 \times \text{severity})$
    - $S \leftarrow \text{clamp}(S - 0.15 \times \text{severity})$
- `PHENOMENOLOGICAL_REDUCTION` (현상학적 환원 / 소매틱 회복):
  - 인자: `calm_factor` (기본 0.5)
  - 변화:
    - $\alpha \leftarrow \text{clamp}(\alpha + 0.15 \times \text{calm\_factor})$
    - $M \leftarrow \text{clamp}(M + 0.10 \times \text{calm\_factor})$
    - $\beta \leftarrow \text{clamp}(\beta + 0.05 \times \text{calm\_factor})$

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "subject_id": "artisan_novice_01",
    "sensory_motor_coupling": 0.60,
    "habitual_sedimentation": 0.50,
    "motor_intentionality": 0.65,
    "environmental_affordance": 0.40,
    "spatial_situatedness": 0.55
  },
  "actions": [
    {"type": "MOTOR_HABIT_PRACTICE", "intensity": 0.70}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 시뮬레이션 결과를 담은 JSON 객체를 공백 없이 한 줄로 출력합니다.

```json
{"subject_id":"artisan_novice_01","initial_state":{"intentional_arc_index":0.3475,"optimum_grip_score":0.992,"lived_body_index":0.6698,"cartesian_alienation_index":0.3302,"embodied_state":"INTENTIONAL_ARC_RUPTURE"},"final_state":{"intentional_arc_index":0.4498,"optimum_grip_score":0.8876,"lived_body_index":0.6687,"cartesian_alienation_index":0.3313,"embodied_state":"PRE_REFLECTIVE_ACTION"},"timeline":[{"action":"MOTOR_HABIT_PRACTICE","state":"PRE_REFLECTIVE_ACTION","lbi":0.6687,"iai":0.4498,"ogs":0.8876}],"parameters":{"alpha":0.656,"beta":0.605,"motor_intentionality":0.734,"environmental_affordance":0.4,"spatial_situatedness":0.55}}
```

---

## 제약 사항

- 모든 파라미터는 실수형이며 $[0.0, 1.0]$ 범위로 클램핑
- 행동 목록 크기 $K \le 1000$
- 시간 제한: 5.0초
- 메모리 제한: 512MB
