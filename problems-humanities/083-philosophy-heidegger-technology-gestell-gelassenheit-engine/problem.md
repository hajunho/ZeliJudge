# 마르틴 하이데거의 기술론: 닦달(Gestell), 상비용재(Bestand) 및 초연함(Gelassenheit) 엔진

## 문제 설명

20세기 실존철학의 거장 **마르틴 하이데거(Martin Heidegger, 1889~1976)**는 1953년 강연 **『기술에 대한 질문(Die Frage nach der Technik / The Question Concerning Technology)』**과 1959년 **『초연함(Gelassenheit / Discourse on Thinking)』**을 통해, 현대 문명이 직면한 기술의 본질을 존재론적으로 파헤쳤습니다.

하이데거는 "기술의 본질은 결코 기술적인 것이 아니다(Das Wesen der Technik ist ganz und gar nichts Technisches)"라고 선언하며, 기술을 단순한 수단이나 중립적 도구로 보는 통속적 관점을 거부했습니다:

1. **탈은폐(Aletheia / Unconcealment / Entbergung)**:
   - 고대 그리스의 기술(Techne)은 감추어져 있던 존재의 진리를 세상에 피어나게 하는 **포이에시스(Poiēsis, 산출/창조)**적 탈은폐였습니다. 풍차는 바람의 힘에 순응하여 곡식을 빻고, 옛 목교는 라인강의 흐름을 거스르지 않고 강과 인간을 이어주었습니다.
2. **현대 기술의 본질: 닦달/몰아세움 (Gestell / Enframing)**:
   - 현대 기술의 탈은폐는 자연을 도발(Herausfordern)하고 다그쳐 에너지를 추출합니다.
   - 모든 존재(자연, 사물, 심지어 인간까지도)를 언제든지 주문하면 꺼내 쓸 수 있는 **부품/상비용재(Bestand / Standing-Reserve)**로 환원합니다.
   - 라인강은 더 이상 유구한 자연의 강이 아니라, 수력 발전소에 수압을 제공하는 에너지원으로 격하됩니다. 인간 또한 존엄한 실존이 아니라 '인적 자원(Human Resources)'이라는 주문품으로 닦달당합니다.
3. **위험과 구원의 힘**:
   - 인간이 닦달의 체제에 갇혀 모든 것을 계산 가능한 자원으로만 보는 **존재 망각(Seinsvergessenheit)**에 빠질 때 최대의 위험이 닥칩니다. 그러나 하이데거는 횔덜린의 시구를 인용합니다: **"위험이 있는 곳에 구원의 힘 또한 자란다(Wo aber Gefahr ist, wächst Das Rettende auch)."**
4. **사물들에 대한 초연함 (Gelassenheit zu den Dingen / Releasement towards things)**:
   - 계산적 사유(Rechnendes Denken)에 맞서는 **사색적 사유(Besinnliches Denken)**입니다.
   - 기술 문명을 맹목적으로 파괴하는 러다이트가 아니라, 기술 장치를 사용하되 그것에 영혼을 빼앗기지 않고 "사물들을 사물들 자체로 놓아두는(Letting-be)" 자유로운 거리두기 태도입니다.
5. **신비에의 열림 (Offenheit für das Geheimnis)**:
   - 모든 것을 파악하고 통제하려는 오만을 내려놓고, 기술의 지평 너머에 존재하는 계산 불가능한 존재의 신비에 마음을 여는 실존적 결단입니다.

당신은 기술철학 및 인문 컴퓨팅 연구원으로서, **계산적 충동, 상비용재 압력, 닦달 지수($GI$), 상비용재 전락도($SRS$), 초연함 점수($GS$) 및 구원의 힘($SPI$)을 추적하고 문명의 존재론적 체제($ExistentialRegime$) 전이를 시뮬레이션하는 하이데거 기술론 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|     Martin Heidegger: Technology, Gestell & Gelassenheit Engine         |
+-------------------------------------------------------------------------+
| [Modern Enframing / Gestell]                                            |
|   - Calculative Drive (Maximizing Efficiency & Total Enclosure)         |
|   - Reduction to Standing-Reserve (Bestand: Nature & Human as Resources)|
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [The Danger & The Turning: Seinsvergessenheit vs Das Rettende]          |
|   - Extreme Risk: Oblivion of Being & Total Instrumentality             |
|   - "Where danger lies, grows that which saves also" (Hölderlin)        |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Gelassenheit / Releasement & Poetic Dwelling]                          |
|   - Meditative Thinking (Besinnliches Denken)                           |
|   - Releasement towards Things: Using technology without bondage        |
|   - Openness to Mystery & Poetic Dwelling on Earth                      |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 상태 파라미터 (`config`)
- `system_id`: 시스템 식별자 (문자열)
- `calculative_drive`: 계산적 사유 및 효용 극대화 충동 $C_{calc} \in [0.0, 1.0]$
- `standing_reserve_pressure`: 모든 존재를 부품/상비용재로 환원하려는 압력 $P_{bestand} \in [0.0, 1.0]$
- `meditative_capacity`: 사색적·본질적 사유 역량 $M_{medit} \in [0.0, 1.0]$
- `poetic_attunement`: 자연과 존재의 진리를 부드럽게 드러내는 포이에시스적 조율 $P_{poetic} \in [0.0, 1.0]$
- `openness_to_mystery`: 계산 불가능한 신비에 대한 열림 $O_{mystery} \in [0.0, 1.0]$

모든 파라미터는 $[0.0, 1.0]$ 범위로 클램핑되며, 지표는 소수점 4자리로 반올림합니다.

### 2. 핵심 지표 산출 공식

1. **닦달 지수 (Gestell Index: $GI$)**:
   계산 충동과 부품화 압력이 지배하고 사색이 억압되는 정도:
   $$GI = \text{clamp}(C_{calc} \times 0.6 + P_{bestand} \times 0.4 - 0.2 \times M_{medit},\, 0.0,\, 1.0)$$

2. **상비용재 전락도 (Standing Reserve Score: $SRS$)**:
   사물과 인간이 고유한 존재성을 잃고 주문 가능한 자원으로 환원되는 정도:
   $$SRS = \text{clamp}\left(P_{bestand} \times \frac{1.0 + C_{calc}}{2.0} - 0.25 \times P_{poetic},\, 0.0,\, 1.0\right)$$

3. **초연함 점수 (Gelassenheit Score: $GS$)**:
   기술에 종속되지 않고 사물과의 자유로운 관계를 회복하는 탈-도구적 해방도:
   $$GS = \text{clamp}(M_{medit} \times 0.5 + O_{mystery} \times 0.3 + P_{poetic} \times 0.2 \times (1.0 - 0.5 \times GI),\, 0.0,\, 1.0)$$

4. **구원의 힘 지수 (Saving Power Index: $SPI$)**:
   초연함과 신비에의 열림이 결합하여 자라나는 존재론적 구원의 가능성:
   $$SPI = \text{clamp}(0.5 \times GS + 0.5 \times O_{mystery},\, 0.0,\, 1.0)$$

### 3. 문명 존재 체제 (`existential_regime`) 전이 조건

우선순위에 따라 체제를 판정합니다:
1. `GESTELL_TOTALITARIANISM`:
   - 조건: $GI \ge 0.75$ 이고 $SRS \ge 0.70$
   - 판정: 모든 존재가 데이터와 부품으로 몰아세워지는 완전한 기술적 닦달 전체주의.
2. `POETIC_DWELLING`:
   - 조건: $P_{poetic} \ge 0.70$ 이고 $O_{mystery} \ge 0.70$ 이고 $GI < 0.40$
   - 판정: 자연의 섭리와 예술적 조화 속에서 인간이 대지 위에 시적으로 거주하는 상태.
3. `GELASSENHEIT_RELEASEMENT`:
   - 조건: $GS \ge 0.65$ 이고 $SPI \ge 0.60$
   - 판정: 기술을 활용하되 그것에 얽매이지 않고 사물을 놓아두는 초연함의 해방 상태.
4. `CALCULATIVE_DOMINANCE`:
   - 조건: 위 세 조건에 해당하지 않는 모든 경우
   - 판정: 일상적 실용성과 계산적 사유가 지배하는 일반 현대 문명 상태.

### 4. 동적 실천 행동 (`actions`)

- `RESOURCE_OPTIMIZATION` (자원 극대화):
  - $C_{calc} \leftarrow \text{clamp}(C_{calc} + 0.15 \times \text{intensity})$
  - $P_{bestand} \leftarrow \text{clamp}(P_{bestand} + 0.18 \times \text{intensity})$
  - $P_{poetic} \leftarrow \text{clamp}(P_{poetic} - 0.10 \times \text{intensity})$
- `MEDITATIVE_PAUSE` (사색적 멈춤):
  - $M_{medit} \leftarrow \text{clamp}(M_{medit} + 0.20 \times \text{intensity})$
  - $C_{calc} \leftarrow \text{clamp}(C_{calc} - 0.12 \times \text{intensity})$
  - $O_{mystery} \leftarrow \text{clamp}(O_{mystery} + 0.10 \times \text{intensity})$
- `POETIC_CREATION` (예술적 창조 / 포이에시스):
  - $P_{poetic} \leftarrow \text{clamp}(P_{poetic} + 0.22 \times \text{intensity})$
  - $O_{mystery} \leftarrow \text{clamp}(O_{mystery} + 0.15 \times \text{intensity})$
  - $P_{bestand} \leftarrow \text{clamp}(P_{bestand} - 0.12 \times \text{intensity})$
- `RADICAL_RELEASEMENT` (근원적 내맡김):
  - $O_{mystery} \leftarrow \text{clamp}(O_{mystery} + 0.25 \times \text{intensity})$
  - $M_{medit} \leftarrow \text{clamp}(M_{medit} + 0.15 \times \text{intensity})$
  - $P_{bestand} \leftarrow \text{clamp}(P_{bestand} - 0.20 \times \text{intensity})$
  - $C_{calc} \leftarrow \text{clamp}(C_{calc} - 0.18 \times \text{intensity})$

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "system_id": "industrial_metro_01",
    "calculative_drive": 0.75,
    "standing_reserve_pressure": 0.70,
    "meditative_capacity": 0.25,
    "poetic_attunement": 0.20,
    "openness_to_mystery": 0.15
  },
  "actions": [
    {"type": "RESOURCE_OPTIMIZATION", "intensity": 0.80}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 시뮬레이션 결과를 담은 JSON 객체를 공백 없이 한 줄로 출력합니다.

```json
{"system_id":"industrial_metro_01","initial_state":{"gestell_index":0.68,"standing_reserve_score":0.5625,"gelassenheit_score":0.1964,"saving_power_index":0.1732,"existential_regime":"CALCULATIVE_DOMINANCE"},"final_state":{"gestell_index":0.8096,"standing_reserve_score":0.7593,"gelassenheit_score":0.1824,"saving_power_index":0.1662,"existential_regime":"GESTELL_TOTALITARIANISM"},"timeline":[{"action":"RESOURCE_OPTIMIZATION","regime":"GESTELL_TOTALITARIANISM","gi":0.8096,"srs":0.7593,"gs":0.1824}],"parameters":{"calculative_drive":0.87,"standing_reserve_pressure":0.844,"meditative_capacity":0.25,"poetic_attunement":0.12,"openness_to_mystery":0.15}}
```

---

## 제약 사항

- 모든 파라미터는 실수형이며 $[0.0, 1.0]$ 범위로 클램핑
- 행동 수 $K \le 1000$
- 시간 제한: 5.0초
- 메모리 제한: 512MB
