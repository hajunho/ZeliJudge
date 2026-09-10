# 프리드리히 니체의 차라투스트라: 정신의 3단 변용(낙타·사자·아이), 영원회귀 및 초인(Übermensch) 엔진

## 문제 설명

19세기 후반 서양 철학의 패러다임을 송두리째 뒤흔든 철학자 **프리드리히 니체(Friedrich Nietzsche, 1844–1900)**는 대표작 『차라투스트라는 이렇게 말했다』(Also sprach Zarathustra, 1883–1885)와 『즐거운 학문』(Die fröhliche Wissenschaft, 1882)을 통해, 플라톤 이래 2천 년간 서구를 지배해 온 초월적 이원론과 기독교 도덕의 종말("신의 죽음, Gott ist tot")을 선언했습니다.

초월적 신과 절대적 진리라는 형이상학적 닻이 사라진 세계에서 인간은 심각한 **허무주의(Nihilism)**에 직면합니다. 니체는 이 허무주의를 두 갈래로 구별했습니다:
- **수동적 허무주의 (Passive Nihilism)**: 모든 가치가 붕괴하자 삶의 의욕을 잃고, 오직 자잘한 안락과 무사안일만을 탐닉하는 멸종 직전의 비참한 인간군상인 **'마지막 인간(Der letzte Mensch)'**으로 전락하는 길.
- **능동적 허무주의 (Active Nihilism)**: 기존의 낡은 가치를 스스로 파괴하고 자신의 생명력을 폭발시키며 새로운 가치를 창조하는 **'초인(Übermensch)'**으로 도약하는 길.

니체는 인간 정신이 초인에 이르는 장엄한 자기 극복의 과정을 **정신의 세 가지 변용(Drei Verwandlungen)**으로 제시합니다:

```
        [ 1. 낙타 (Kamel) ]  "너는 마땅히 해야 한다 (Du sollst)"
          - 사막의 짐꾼: 전통 도덕, 율법, 사회적 의무를 묵묵히 짊어지는 인내의 정신.
          - 한계: 짐을 견딜 수는 있으나, 새로운 가치를 스스로 창조하지는 못함.
                         │
                         ▼ [ 사막 한가운데서의 결전: 거대한 용(Thou Shalt)과의 대결 ]
        [ 2. 사자 (Löwe) ]   "나는 원한다 (Ich will)"
          - 자유의 투사: "너는 마땅히 해야 한다"라는 황금빛 비늘의 용에 맞서 "거룩한 부정(Ein heiliges Nein)"을 포효.
          - 획득: 속박으로부터의 자유(Freedom from), 낡은 규범의 파괴.
          - 한계: 사자의 발톱은 파괴할 수는 있어도, 긍정적인 새 가치를 지어내지(Freedom to) 못함.
                         │
                         ▼ [ 망각과 순진무구함: 창조의 열린 공간으로의 비약 ]
        [ 3. 아이 (Kind) ]   "나는 존재하며 창조한다 (Ein heiliges Ja-sagen)"
          - 순진무구와 망각, 새로운 시작, 놀이, 스스로 굴러가는 바퀴(ein aus sich rollendes Rad), 최초의 운동, 거룩한 긍정.
          - 자신의 뜻을 자신의 세계로 삼아 자유롭게 새로운 가치를 직조함.
```

나아가 니체는 삶에 대한 궁극의 긍정 시험대로서 **영원회귀(Ewige Wiederkunft des Gleichen)** 사상을 던집니다:
> *"너의 삶이 영원히 수없이 반복된다면, 너는 그 무한한 고통과 환희의 고리를 두려움 없이 끌어안을 수 있는가?"* (가장 무거운 무게, Das schwerste Gewicht)

어떠한 후회나 도피 없이 자신의 삶과 운명을 통째로 긍정하고 사랑하는 **아모르 파티(Amor Fati, 운명애)**와 끊임없이 자신을 극복하는 **권력의지(Wille zur Macht)**를 달성한 자만이 진정한 **초인(Übermensch)**의 칭호를 얻습니다.

본 시스템은 니체의 정신 3단 변용 전이 상태 머신, 권력의지 및 마지막 인간 판정, 그리고 악마의 영원회귀 도전을 시뮬레이션하는 **니체 실존주의 지성 엔진**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 정신 상태 변용 머신 (`current_spirit`)
1. **낙타 (`CAMEL`)**:
   - `BEAR_BURDEN`: 주어진 `duty_weight`를 인내 점수(`endurance_score`)에 누적합니다.
   - 만약 `endurance_score >= 50.0` 이고 `encounter_dragon == true` 이면 즉시 **사자(`LION`)**로 질적 변용합니다.
2. **사자 (`LION`)**:
   - `ROAR_SACRED_NO`: "너는 마땅히 해야 한다"는 용을 향해 `defiance_intensity`를 뿜어내며 `lion_freedom_score`에 누적합니다.
   - 만약 `lion_freedom_score >= 40.0` 이고 `creates_open_space == true` 이면 즉시 **아이(`CHILD`)**로 변용합니다.
3. **아이 (`CHILD`)**:
   - `SACRED_YES_PLAY`: 거룩한 긍정(`sacred_yes == true`)을 통해 창조 점수(`creation_score += creativity_value`)를 획득합니다.

### 2. 권력의지와 마지막 인간
1. **권력의지 (`EXERCISE_WILL_TO_POWER`)**:
   - 자기극복의 노력(`self_overcoming_effort`)을 투입하여 `will_to_power_score`를 증대시킵니다.
2. **안락 추구 (`SEEK_PETTY_COMFORT`)**:
   - 고통과 성장을 기피하고 작은 쾌락을 추구하여 `comfort_seeking_accum += comfort_level`.

### 3. 영원회귀 시험 (`TEST_ETERNAL_RECURRENCE`)
1. 악마가 던지는 무한 반복의 물음에 대해:
   - `embrace_infinite_loop == true` 이고 `regret_level <= 0.15` 인 경우:
     - 영원회귀 통과(`eternal_recurrence_passed = true`).
     - 운명애 점수: `amor_fati_score = round(100.0 * (1.0 - regret_level), 2)`.
   - 거부하거나 회한이 큰 경우:
     - 가장 무거운 무게에 짓눌려 탈락 (`eternal_recurrence_passed = false`).
     - `amor_fati_score = round(max(0.0, 50.0 * (1.0 - regret_level)), 2)`.

### 4. 최종 판정 (`verdict`)
1. `comfort_seeking_accum >= 1.5` 이고 `will_to_power_score < 20.0` 인 경우: **`LAST_MAN`**
2. `current_spirit == "CHILD"` 이고 `eternal_recurrence_passed == true` 이며 `will_to_power_score >= 30.0` 인 경우: **`UBERMENSCH`**
3. 그 외 현재 정신 상태에 따라: `CREATIVE_CHILD`, `REBELLIOUS_LION`, `BURDENED_CAMEL`, `PASSIVE_NIHILIST`.

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "agent_id": "Friedrich_Nietzsche_Seeker",
  "initial_spirit": "CAMEL",
  "actions": [
    {"type": "BEAR_BURDEN", "params": {"duty_weight": 60.0, "encounter_dragon": true}},
    {"type": "ROAR_SACRED_NO", "params": {"defiance_intensity": 50.0, "creates_open_space": true}},
    {"type": "SACRED_YES_PLAY", "params": {"creativity_value": 40.0, "sacred_yes": true}},
    {"type": "EXERCISE_WILL_TO_POWER", "params": {"self_overcoming_effort": 45.0}},
    {"type": "TEST_ETERNAL_RECURRENCE", "params": {"embrace_infinite_loop": true, "regret_level": 0.0}}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "agent_id": "Friedrich_Nietzsche_Seeker",
  "metrics": {
    "current_spirit": "CHILD",
    "spirit_history": ["CAMEL", "LION", "CHILD"],
    "endurance_score": 60.0,
    "lion_freedom_score": 50.0,
    "creation_score": 40.0,
    "will_to_power_score": 45.0,
    "amor_fati_score": 100.0,
    "comfort_seeking_accum": 0.0,
    "eternal_recurrence_passed": true,
    "existential_authenticity_score": 100.0
  },
  "verdict": "UBERMENSCH",
  "action_log": [
    ...
  ]
}
```
