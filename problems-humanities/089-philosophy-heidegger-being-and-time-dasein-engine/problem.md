# 마르틴 하이데거의 존재와 시간: 현존재(Dasein), 도구 연관망(Zuhandenheit)의 파열, 세인(Das Man) 및 죽음에 이르는 존재(Sein-zum-Tode) 엔진

## 문제 설명

20세기 서양 철학의 패러다임을 바꾼 마르틴 하이데거(Martin Heidegger)의 1927년 주저 **『존재와 시간(Sein und Zeit)』**은 서구 존재론이 수천 년 동안 '존재자(Seiende)'와 '존재(Sein)'의 차이를 망각해 왔다는 비판에서 출발합니다. 데카르트 이래 근대 철학은 인간을 세계 외부에서 대상을 관찰하는 고립된 '의식 주체(res cogitans)'로 규정했으나, 하이데거는 인간의 근본 실존 양식을 언제나 이미 구체적인 의미의 관계망 속에 던져져 살아가는 **'세계-내-존재(In-der-Welt-sein)'**이자 **'현존재(Dasein)'**로 정식화했습니다.

하이데거의 실존론적 분석론(Existenziale Analytik)은 크게 세 가지 핵심 축으로 구성됩니다:

1. **도구 연관망(Zeugganzheit)과 파열(Unzuhandenheit)**:
   우리는 사물을 이론적 관찰 대상(눈앞에 있음, *Vorhandenheit*)으로 대하기 전에, 행위의 맥락 속에서 실용적으로 사용합니다(손안에 있음, *Zuhandenheit*). 도구는 단독으로 존재하지 않고 상호 의존적인 목적 연관망 속에서 작동하며, 정상 작동할 때 도구 자체는 의식에서 '투명(transparent)'해집니다. 그러나 도구가 손상되거나(*Auffälligkeit*, 눈에 띔), 부품이 결여되거나(*Aufdringlichkeit*, 불가결함), 통로를 가로막을 때(*Aufsässigkeit*, 거치적거림) 투명성은 깨어지고 배경에 물러서 있던 세계 전체가 비로소 모습을 드러내며 대상화됩니다.
2. **세인(Das Man)과 일상성의 퇴락(Verfallen)**:
   현존재는 매일의 삶 속에서 독자적인 자기로 살아가지 못하고, "사람들이 보통 그러하듯" 행동하는 익명적 평균성의 지배를 받습니다. 이는 무비판적인 잡담(*Gerede*), 산만한 호기심(*Neugier*), 피상적 모호성(*Zweideutigkeit*)이라는 세 가지 일상적 퇴락 양식으로 나타나며, 현존재의 본래적 결단을 은폐합니다.
3. **불안(Angst)과 죽음에 이르는 존재(Sein-zum-Tode)**:
   세계 내부의 특정 대상에 대한 두려움인 공포(*Furcht*)와 달리, **불안(Angst)**은 세계의 모든 의미 연관이 무의미해지는 '무(Nothingness)'와의 마주침입니다. 불안 속에서 세인의 거짓 안온함은 산산이 부서지며, 현존재는 타인에게 양도할 수 없는 가장 고유하고 극복 불가능한 가능성인 **자신의 죽음(Tod)**과 대면하게 됩니다. 죽음을 회피하지 않고 미리 앞서 달려가 자각하는 '선구(Vorlaufen in den Tod)'를 통해 현존재는 세인의 노예 상태에서 벗어나 유한한 시간 속에서 자기 삶을 결단하는 **본래적 실존(Eigentlichkeit)**을 획득합니다.

본 문제에서는 하이데거의 『존재와 시간』 실존 분석론을 모델링한 **현존재 실존 역학 엔진**을 구현해야 합니다.

---

## 시스템 아키텍처 및 실존 분석 도식

```
+---------------------------------------------------------------------------------------------------+
|               Martin Heidegger: Being and Time (Sein und Zeit) Dasein Engine                     |
+---------------------------------------------------------------------------------------------------+

   [ In-der-Welt-sein: Equipmental Nexus ]           [ Everydayness: Das Man & Falling ]
   +---------------------------------------+         +---------------------------------------+
   | Tool Nodes: e_1, e_2, ..., e_n        |         | Gerede (Idle Talk)        -> G [0..1] |
   | Dependencies: e_i -> {e_j, e_k}       |         | Neugier (Curiosity)       -> N [0..1] |
   | Status: FUNCTIONAL / DAMAGED /        |         | Zweideutigkeit (Ambiguity)-> Z [0..1] |
   |         MISSING / OBSTRUCTING         |         |                                       |
   +---------------------------------------+         | Falling Index: F = (G + N + Z) / 3    |
                      |                              +---------------------------------------+
                      v                                                  |
     +----------------------------------+                                |
     | Breakdown / Unzuhandenheit:      |                                |
     | - Conspicuous (Auffaelligkeit)   |                                |
     | - Obtrusive (Aufdringlichkeit)   |                                |
     | - Obstinate (Aufsaessigkeit)     |                                |
     |                                  |                                |
     | Transparency: T_z = func / total |                                |
     | World-Revelation: W_rev = 1 - T_z|                                |
     +----------------------------------+                                |
                      |                                                  |
                      |                                                  v
                      |                              +---------------------------------------+
                      |                              | Affective Mood: Fear vs Angst         |
                      |                              | - Furcht (Specific Object): Intraworld|
                      |                              | - Angst (Nothingness): Unheimlichkeit |
                      |                              |   F_eff = F * (1.0 - Angst)           |
                      |                              +---------------------------------------+
                      |                                                  |
                      +------------------+   +---------------------------+
                                         |   |
                                         v   v
                      +-------------------------------------------------------+
                      | Sein-zum-Tode & Authentic Resolve (Entschlossenheit)  |
                      | Anticipation: V = Mortality * Angst                   |
                      | Authenticity: Auth = V * (1 - F_eff) + 0.5 * W_rev    |
                      +-------------------------------------------------------+
                                                 |
                                                 v
                      [ Existential Regime Determination: 4 States ]
                      - AUTHENTIC_RESOLVE (본래적 결단성)
                      - EXISTENTIAL_ANXIETY (기이함과 세계의 붕괴)
                      - THEMATIC_BREAKDOWN (도구 연관망 파열 및 눈앞에 있음)
                      - FALLEN_EVERYDAYNESS (세인에 종속된 퇴락한 일상)
```

---

## 수리 및 실존론적 작동 공식

### 1. 도구 연관망 분석 및 파열 메커니즘
$N$개의 도구로 이루어진 집합 $E = \{e_1, e_2, \dots, e_N\}$에서 각 도구 $e_i$는 의존하는 선행 도구 목록(`dependencies`)과 상태(`status`)를 갖습니다.
- **도구 결함 판정**:
  - `status == "DAMAGED"`: 도구 자체의 파손 $\to$ 눈에 띔(**Conspicuous**, *Auffälligkeit*).
  - `status == "MISSING"`이거나, 의존하는 선행 도구 중 하나라도 `DAMAGED` 또는 `MISSING`인 경우: 연관망 단절 $\to$ 불가결함(**Obtrusive**, *Aufdringlichkeit*).
  - `status == "OBSTRUCTING"`: 작업 공간을 점유하고 방해함 $\to$ 거치적거림(**Obstinate**, *Aufsässigkeit*).
  - 위의 세 가지 결함에 해당하지 않는 도구만이 정상 기능(`functional`)으로 집계됩니다.
- **투명성 및 세계 개시성**:
  $$T_z = \frac{\text{functional\_count}}{|E|} \quad (\text{도구 투명성 지수})$$
  $$W_{\text{rev}} = 1.0 - T_z \quad (\text{세계 현현 및 탈맥락화 지수})$$
  - $W_{\text{rev}} < 0.50$이면 실용적 몰입 상태인 **손안에 있음(`ZUHANDENHEIT`)**, $W_{\text{rev}} \ge 0.50$이면 이론적 관찰 상태인 **눈앞에 있음(`VORHANDENHEIT`)**으로 판정합니다.

### 2. 세인(Das Man)의 퇴락도
현존재의 일상적 비본래성은 잡담($G$), 호기심($N$), 모호성($Z$)의 평균으로 정량화됩니다:
$$F = \frac{G + N + Z}{3}$$

### 3. 정서적 기분: 공포(Furcht) 대 불안(Angst)
- 위험 유형(`threat_type`)이 `"SPECIFIC_OBJECT"`인 경우: 일상적 세계 내부의 위험에 대한 반응으로 $\text{Fear} = \text{intensity}$, $\text{Angst} = 0.0$.
- 위험 유형이 `"NOTHINGNESS_IN_THE_WORLD"`인 경우: 세계 전체의 의미가 침묵하는 실존적 불안으로 $\text{Angst} = \text{intensity}$, $\text{Fear} = 0.0$.
- 불안은 세인의 일상적 안온함을 깨뜨리므로 유효 퇴락도($F_{\text{eff}}$)를 감소시킵니다:
  $$F_{\text{eff}} = F \times (1.0 - \text{Angst})$$

### 4. 죽음에 이르는 존재와 본래성(Eigentlichkeit) 지수
- 죽음에 대한 자각도($M$)와 불안($\text{Angst}$)의 결합을 통해 죽음의 선구도($V$)를 도출합니다:
  $$V = M \times \text{Angst}$$
- 본래성 지수($\text{Auth}$)는 세인의 퇴락을 극복한 죽음의 선구와 도구 파열을 통한 세계 자각의 가중합으로 계산되며 $[0.0, 1.0]$ 범위로 클램핑됩니다:
  $$\text{Auth} = \min(1.0, \max(0.0, V \times (1.0 - F_{\text{eff}}) + 0.5 \times W_{\text{rev}}))$$

### 5. 실존 레짐(Existential Regime) 4단계 분류
1. $\text{Auth} \ge 0.65$ 이고 $V \ge 0.35$인 경우:
   $$\to \mathbf{AUTHENTIC\_RESOLVE} \quad (\text{본래적 결단성: 죽음의 선구와 유한성의 주체적 인수})$$
2. 그렇지 않고 $\text{Angst} \ge 0.50$ 이고 $\text{Auth} \ge 0.35$인 경우:
   $$\to \mathbf{EXISTENTIAL\_ANXIETY} \quad (\text{실존적 불안과 기이함: 세인 연대의 붕괴})$$
3. 그렇지 않고 $W_{\text{rev}} \ge 0.50$인 경우:
   $$\to \mathbf{THEMATIC\_BREAKDOWN} \quad (\text{도구 연관망 파열 및 눈앞에 있음의 객체화})$$
4. 그 외의 모든 경우:
   $$\to \mathbf{FALLEN\_EVERYDAYNESS} \quad (\text{세인에 매몰된 일상적 퇴락})$$

---

## 입력 형식

표준 입력(stdin)으로 다음 구조를 갖는 단일 JSON 객체가 주어집니다:

```json
{
  "equipment_nexus": [
    {
      "name": "Hammer",
      "status": "FUNCTIONAL",
      "dependencies": ["Nail"]
    },
    {
      "name": "Nail",
      "status": "FUNCTIONAL",
      "dependencies": []
    }
  ],
  "das_man": {
    "gerede_idle_talk": 0.20,
    "neugier_curiosity": 0.15,
    "zweideutigkeit_ambiguity": 0.10
  },
  "affective_state": {
    "threat_type": "NOTHINGNESS_IN_THE_WORLD",
    "intensity": 0.85
  },
  "mortality_awareness": 0.90
}
```

---

## 출력 형식

표준 출력(stdout)으로 도구 분석, 실존 지표, 최종 실존 레짐을 담은 JSON 객체를 공백 없는 압축 형식(`separators=(',', ':')`)으로 출력합니다:

```json
{
  "equipment_analysis": {
    "total_tools": 2,
    "functional_count": 2,
    "transparency_index": 1.0,
    "world_revealed_index": 0.0,
    "breakdown_modes": {
      "conspicuous_damaged": [],
      "obtrusive_missing": [],
      "obstinate_obstructing": []
    },
    "ontological_mode": "ZUHANDENHEIT"
  },
  "existential_metrics": {
    "das_man_falling_index": 0.15,
    "effective_falling_index": 0.0225,
    "angst_score": 0.85,
    "fear_score": 0.0,
    "death_anticipation": 0.765,
    "authenticity_index": 0.7478
  },
  "existential_regime": "AUTHENTIC_RESOLVE"
}
```

(모든 부동소수점 지표는 소수점 4자리까지 반올림하여 표기합니다.)

---

## 제약 조건

- 도구 개수: $1 \le |E| \le 1,000$
- `status`: `"FUNCTIONAL"`, `"DAMAGED"`, `"MISSING"`, `"OBSTRUCTING"` 중 하나
- `threat_type`: `"NONE"`, `"SPECIFIC_OBJECT"`, `"NOTHINGNESS_IN_THE_WORLD"` 중 하나
- 모든 연속 수치 파라미터($G, N, Z, \text{intensity}, M$): $[0.0, 1.0]$ 범위의 실수
- 표준 라이브러리만을 사용하여 순수 파이썬으로 구현되어야 함
