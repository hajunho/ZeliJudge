# 한나 아렌트의 인간의 조건: 활동적 삶(Vita Activa), 다원성 및 탄생성 엔진

## 문제 설명

20세기의 독보적 정치철학자 **한나 아렌트(Hannah Arendt, 1906~1975)**는 1958년 출간된 불후의 명저 **『인간의 조건(The Human Condition)』**을 통해, 서구 사상사에서 사색적 삶(Vita Contemplativa)의 그늘에 가려져 있던 **활동적 삶(Vita Activa)**의 내적 위계를 근본적으로 재구성했습니다.

아렌트는 인간의 활동적 삶을 세 가지 차원으로 엄격히 구분했습니다:

1. **노동 (Labor / Arbeit)**:
   - 인간 신체의 생물학적 생존과 신진대사 과정에 묶인 필연적 활동입니다.
   - 빵을 굽고 먹는 것처럼, 노동의 생산물은 소비되는 즉시 소멸하며 어떠한 영속적인 자취도 남기지 못하는 닫힌 순환 고리입니다.
2. **작업 (Work / Herstellen)**:
   - 자연을 가공하여 도구, 주택, 기념비, 예술품 등 영속적인 인공적 세계(Human Artifacts)를 건축하는 활동입니다.
   - 호모 파베르(Homo Faber, 제작인)의 영역으로서 삶에 안정성과 지속성을 부여하지만, "목적이 수단을 정당화한다"는 공리주의적·도구주의적 범주에 갇히는 한계를 갖습니다.
3. **행위 (Action / Handeln)**:
   - 사물이나 물질의 매개 없이, 오직 **인간들 사이(Inter-est)**에서 **말과 행위(Speech and Action)**를 통해 자기가 누구인지를 세상에 드러내는 유일한 영역입니다.
   - 이것이야말로 진정한 자유(Freedom)와 정치(Politics)의 영역입니다.

아렌트 정치철학의 정점은 **다원성(Plurality)**과 **탄생성(Natality)**입니다:
- **다원성(Plurality)**: "인간(Man)이 아니라 인간들(Men)이 지구상에 살며 세상을 거주한다." 모든 인간은 평등하면서도 각자 대체 불가능한 고유성을 가집니다.
- **탄생성(Natality)**: 하이데거의 '죽음을 향한 존재'에 맞서 아렌트는 인간이 죽기 위해서가 아니라 새로운 시작(Beginning)을 열기 위해 태어났음을 역설합니다. 행위는 인과율의 닫힌 사슬을 깨뜨리고 예측 불가능한 기적을 촉발하는 시작의 능력입니다.
- **행위의 2대 딜레마와 치유책**:
  - **불가역성(Irreversibility)**: 한 번 일어난 행위는 되돌릴 수 없습니다 $\to$ **용서(Forgiveness)**를 통해 과거의 사슬을 끊고 다시 시작할 수 있습니다.
  - **예측불가능성(Unpredictability)**: 행위가 촉발한 결과는 통제할 수 없습니다 $\to$ **약속(Promising)**을 통해 미래의 불확실한 대양에 신뢰의 섬을 구축합니다.
- **근대의 비극: 활동적 삶의 전도**:
  - 고대 그리스 폴리스에서는 행위가 최상위였으나, 근대 소비 사회에서는 오직 생계와 물질적 소비만을 추구하는 **노동 동물(Animal Laborans)**이 세계를 장악하여 공론장이 질식당했습니다.

당신은 정치철학 및 사회과학 컴퓨팅 연구원으로서, **노동 동물 전락도($ALI$), 공공 영역 개방도($PRO$), 탄생성 지수($NI$), 활동적 삶 건강도($VAH$)를 추적하고 정치공동체의 실존 상태($VitaActivaState$) 전이를 판정하는 아렌트 인간의 조건 시뮬레이션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|     Hannah Arendt: The Human Condition (Vita Activa Engine)             |
+-------------------------------------------------------------------------+
| [Labor / Animal Laborans]                                               |
|   - Biological Metabolism, Consumption & Necessity (Zero Durability)    |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Work / Homo Faber]                                                     |
|   - Fabrication of Durable World Artifacts, Means-Ends Utilitarianism   |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Action / The Political Polis]                                          |
|   - Speech & Action among Plural Humans (Disclosure of "Who" one is)    |
|   - Natality: The Power of Beginning the Unprecedented                  |
|   - Remedies: Forgiveness (Irreversibility) & Promising (Unpredictability)|
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 상태 파라미터 (`config`)
- `polity_id`: 공동체 식별자 (문자열)
- `labor_metabolism_load`: 생물학적 생계 노동 부하 $L \in [0.0, 1.0]$
- `work_fabrication_durability`: 인공 세계 구축 및 지속성 $W \in [0.0, 1.0]$
- `action_plurality_engagement`: 공론장에서의 말과 행위, 다원적 참여 $A \in [0.0, 1.0]$
- `forgiveness_capacity`: 과거의 불가역성을 해소하는 용서 역량 $F \in [0.0, 1.0]$
- `promising_fidelity`: 미래의 예측불가능성을 묶는 약속의 신의 $P \in [0.0, 1.0]$

모든 파라미터는 $[0.0, 1.0]$ 범위로 클램핑되며, 지표는 소수점 4자리로 반올림합니다.

### 2. 핵심 지표 산출 공식

1. **노동 동물 전락도 (Animal Laborans Index: $ALI$)**:
   생계 노동 부담이 높고 공적 행위가 결손되며 인공 세계의 내구성이 부족할 때 상승:
   $$ALI = \text{clamp}(L \times 0.7 + (1.0 - A) \times 0.3 - 0.2 \times W,\, 0.0,\, 1.0)$$

2. **공공 영역 개방도 (Public Realm Openness: $PRO$)**:
   말과 행위가 살아 숨 쉬고, 제도가 안정적이며, 생계 압박을 넘어선 약속이 작동하는 정도:
   $$PRO = \text{clamp}(A \times 0.6 + W \times 0.2 + P \times 0.2 \times (1.0 - 0.5 \times L),\, 0.0,\, 1.0)$$

3. **탄생성 지수 (Natality Index: $NI$)**:
   새로운 시작을 열어젖히는 행위 역량과 이를 지탱하는 용서 및 약속의 결합도:
   $$NI = \text{clamp}(A \times 0.5 + F \times 0.25 + P \times 0.25,\, 0.0,\, 1.0)$$

4. **활동적 삶 건강도 (Vita Activa Health: $VAH$)**:
   공론장 개방, 탄생성, 노동의 예속으로부터의 해방이 이룬 총체적 조화:
   $$VAH = \text{clamp}(0.4 \times PRO + 0.4 \times NI + 0.2 \times (1.0 - ALI),\, 0.0,\, 1.0)$$

### 3. 실존 상태 (`vita_activa_state`) 전이 조건

우선순위에 따라 상태를 판정합니다:
1. `ANIMAL_LABORANS_DOMINANCE`:
   - 조건: $ALI \ge 0.70$ 이고 $PRO < 0.35$
   - 판정: 인간이 생물학적 생존과 소비 루프에 갇혀 공론장을 상실한 노동 동물 전락 상태.
2. `POLITICAL_POLIS_FLOURISHING`:
   - 조건: $PRO \ge 0.70$ 이고 $NI \ge 0.70$ 이고 $VAH \ge 0.70$
   - 판정: 다원성과 탄생성이 만개하여 자유로운 시민들이 공론장을 주재하는 진정한 정치 공동체(Polis) 상태.
3. `HOMO_FABER_INSTRUMENTALITY`:
   - 조건: $W \ge 0.65$ 이고 $A < 0.40$
   - 판정: 인공적 제작물과 기술은 번창하나 모든 정치적 결정을 수단-목적의 유용성으로 환원하는 제작인 상태.
4. `CONVENTIONAL_VITA_ACTIVA`:
   - 조건: 위 세 조건에 해당하지 않는 모든 경우
   - 판정: 노동, 작업, 행위가 미분화된 채 공존하는 일상적 상태.

### 4. 동적 실천 행동 (`actions`)

- `BIOLOGICAL_CONSUMPTION_CYCLE` (소비 순환 가속):
  - $L \leftarrow \text{clamp}(L + 0.18 \times \text{intensity})$
  - $A \leftarrow \text{clamp}(A - 0.15 \times \text{intensity})$
  - $F \leftarrow \text{clamp}(F - 0.10 \times \text{intensity})$
- `WORLD_FABRICATION` (인공 세계 및 제도 건축):
  - $W \leftarrow \text{clamp}(W + 0.20 \times \text{intensity})$
  - $P \leftarrow \text{clamp}(P + 0.10 \times \text{intensity})$
  - $L \leftarrow \text{clamp}(L - 0.08 \times \text{intensity})$
- `POLITICAL_SPEECH_AND_ACTION` (공론장 말과 행위 참여):
  - $A \leftarrow \text{clamp}(A + 0.22 \times \text{intensity})$
  - $P \leftarrow \text{clamp}(P + 0.12 \times \text{intensity})$
  - $L \leftarrow \text{clamp}(L - 0.12 \times \text{intensity})$
- `MUTUAL_FORGIVENESS_AND_PROMISE` (상호 용서와 약속의 결속):
  - $F \leftarrow \text{clamp}(F + 0.25 \times \text{intensity})$
  - $P \leftarrow \text{clamp}(P + 0.20 \times \text{intensity})$
  - $A \leftarrow \text{clamp}(A + 0.10 \times \text{intensity})$

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "polity_id": "consumer_society_01",
    "labor_metabolism_load": 0.80,
    "work_fabrication_durability": 0.30,
    "action_plurality_engagement": 0.15,
    "forgiveness_capacity": 0.20,
    "promising_fidelity": 0.25
  },
  "actions": [
    {"type": "BIOLOGICAL_CONSUMPTION_CYCLE", "intensity": 0.80}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 시뮬레이션 결과를 담은 JSON 객체를 공백 없이 한 줄로 출력합니다.

```json
{"polity_id":"consumer_society_01","initial_state":{"animal_laborans_index":0.755,"public_realm_openness":0.18,"natality_index":0.1875,"vita_activa_health":0.196,"vita_activa_state":"ANIMAL_LABORANS_DOMINANCE"},"final_state":{"animal_laborans_index":0.9088,"public_realm_openness":0.0987,"natality_index":0.1375,"vita_activa_health":0.1127,"vita_activa_state":"ANIMAL_LABORANS_DOMINANCE"},"timeline":[{"action":"BIOLOGICAL_CONSUMPTION_CYCLE","state":"ANIMAL_LABORANS_DOMINANCE","ali":0.9088,"pro":0.0987,"ni":0.1375,"vah":0.1127}],"parameters":{"labor":0.944,"work":0.3,"action":0.03,"forgiveness":0.12,"promising":0.25}}
```

---

## 제약 사항

- 모든 파라미터는 실수형이며 $[0.0, 1.0]$ 범위로 클램핑
- 행동 수 $K \le 1000$
- 시간 제한: 5.0초
- 메모리 제한: 512MB
