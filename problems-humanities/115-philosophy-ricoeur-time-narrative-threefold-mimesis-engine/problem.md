# 폴 리쾨르: 시간과 서사(Temps et Récit), 3중 미메시스와 이야기 정체성(Idem vs Ipse) 시뮬레이션 엔진

## 문제 설명

20세기 프랑스 해석학의 거장 **폴 리쾨르(Paul Ricoeur, 1913~2005)**는 대표작인 『시간과 서사(Temps et Récit, 1983~1985)』와 『타자로서의 자기 자신(Soi-même comme un autre, 1990)』을 통해, 아우구스티누스의 "시간의 아포리아(시간은 도대체 무엇인가?)"와 아리스토텔레스의 『시학』에 나오는 "플롯 구성(Mise en intrigue / Mythos)"을 결합하여 인간 실존의 시간 경험과 정체성 문제를 해결했습니다.

리쾨르에 따르면 인간은 흘러가는 우주적 시간(Cosmological Time) 속에서 흩어지고 분절되는 유한한 존재이지만, **서사(Narrative)**라는 인간 고유의 상징적 능력을 통해 삶의 파편들을 하나의 일관된 역사로 엮어냅니다. 이 역동적 서사화 과정은 **3중 미메시스(Threefold Mimesis)**와 **이야기 정체성(Narrative Identity)** 모델로 체계화됩니다:

```
[Mimesis 1 : 선-형상화 (Prefiguration)]
  - 일상적 삶의 세계에 이미 존재하는 행위의 의미망, 동기, 가치
  - 시간적 분절과 개별 사건들의 연대기적 흩어짐
         ↓ (플롯 구성 : Mise en intrigue)
[Mimesis 2 : 형상화 (Configuration)]
  - 이질적인 것들의 종합 (Synthesis of the Heterogeneous)
  - 우연한 사건(Contingency)과 필연적 행위(Action)를 단일한 이야기 곡선으로 통합
  - '의심의 해석학' 통과: 위선, 허위의식, 이데올로기적 환상 폭로
  - '제2의 소박성(Second Naiveté)'에 의한 의미의 비판적 회복
         ↓ (독자의 수용과 삶의 변혁)
[Mimesis 3 : 재-형상화 (Refiguration)]
  - 텍스트의 세계와 독자의 세계가 만나는 실존적 지평의 확장
  - 현상학적 시간 팽창 (Phenomenological Time Dilation)
         ↓
[이야기 정체성 (Narrative Identity)]
  - 동일성 (Idem / Sameness) : 불변하는 성격과 물리적 연속성
  - 자기성 (Ipse / Selfhood) : 시간의 파도 속에서도 약속을 지키는 윤리적 결단 (Maintien de soi)
```

본 문제에서는 주어지는 인물의 생애 사건 스트림과 해석학적 설정(플롯 모드, 의심의 필터, 수용 지평)을 바탕으로, 리쾨르의 3중 미메시스 연쇄 계산 및 동일성(Idem)과 자기성(Ipse)의 긴장 관계를 거쳐 궁극적인 이야기 정체성 도달 여부를 판정하는 시뮬레이션 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "subject": {
    "name": "Jean_Valjean",
    "character_traits": ["convict", "hardworking", "penniless"]
  },
  "life_events": [
    {
      "id": "e1",
      "timestamp": 1,
      "event_type": "ACTION",
      "agent": "Jean_Valjean",
      "motive": "hunger",
      "goal": "survival",
      "description": "loaf of bread stolen",
      "valence": -0.5
    },
    {
      "id": "e2",
      "timestamp": 5,
      "event_type": "CONTINGENCY",
      "agent": "Myriel",
      "motive": "grace",
      "goal": "redemption",
      "description": "silver candlesticks gifted",
      "valence": 0.9,
      "trait_change": "redeemed"
    },
    {
      "id": "e3",
      "timestamp": 10,
      "event_type": "PROMISE",
      "agent": "Jean_Valjean",
      "motive": "duty",
      "goal": "become_honest_man",
      "description": "pledge to Bishop to live righteously",
      "fidelity_cost": 0.85
    }
  ],
  "interpretation_config": {
    "emplotment_mode": "TRAGIC_TO_REDEMPTIVE",
    "suspicion_filter_applied": true,
    "refiguration_horizon": "ETHICAL_RESPONSIBILITY"
  }
}
```

### 파라미터 규격
- `subject` (객체): 분석 대상 인물 정보 (`name`, `character_traits`).
- `life_events` (배열): 시간순으로 주어지는 사건 객체 목록.
  - `id` (문자열): 사건 고유 식별자.
  - `timestamp` (정수): 사건 발생 시점.
  - `event_type` (문자열): `"ACTION"`, `"CONTINGENCY"`, `"PROMISE"` 중 하나.
  - `motive` (문자열): 사건의 내적 동기.
  - `valence` (실수, -1.0 ~ 1.0): 사건의 정서적/윤리적 가치.
  - `trait_change` (선택적 문자열): 사건으로 인한 성격/성향 변화.
  - `fidelity_cost` (실수, 0.0 ~ 1.0, `PROMISE` 유형일 때): 약속 유지를 위해 감수해야 하는 실존적 대가.
- `interpretation_config` (객체): 서사 해석 설정.
  - `emplotment_mode`: `"TRAGIC_TO_REDEMPTIVE"` (배율 1.25), `"DIALECTICAL"` (배율 1.15), `"CHRONIC_EPISODIC"` (배율 0.85).
  - `suspicion_filter_applied` (불리언): 의심의 해석학 필터 적용 여부.
  - `refiguration_horizon`: `"ETHICAL_RESPONSIBILITY"` (부스트 1.2), `"EXISTENTIAL_LIBERATION"` (부스트 1.15), `"AESTHETIC_CONTEMPLATION"` (부스트 1.05).

---

## 계산 명세

1. **Mimesis 1 (선-형상화 / Prefiguration)**:
   - `chronological_span` = $\max(t) - \min(t)$ (사건이 없으면 0).
   - 각 이벤트 유형의 개수 집계: `actions_count`, `contingencies_count`, `promises_count`.
   - `prefig_score` = $\text{round}(\bar{v} \times 0.5 + (\text{actions\_count} / \max(1, N)) \times 0.5, 4)$ (여기서 $\bar{v}$는 `valence`의 평균).

2. **Mimesis 2 (형상화 / Configuration - 이질적인 것들의 종합)**:
   - 플롯 긴장도 `plot_tension` = $\text{round}(\sum_{i=1}^{N-1} |v_{i+1} - v_i|, 4)$.
   - 의심의 해석학 (`suspicion_filter_applied`가 참인 경우):
     - 동기(`motive`) 문자열(소문자)에 `"pride"`, `"vanity"`, `"hypocrisy"`, `"illusion"`, `"coercion"` 중 하나라도 포함된 사건을 `suspicious_events`로 분류.
     - `suspicion_index` = $\text{round}(\text{len(suspicious\_events)} / \max(1, N), 4)$.
   - 종합 점수 `synthesis_score`:
     - $\text{contingency\_integration} = (\text{contingencies} \times 0.2 + \text{promises} \times 0.3) / \max(1, N)$.
     - $\text{raw\_synthesis} = (0.5 + \text{contingency\_integration} - \text{suspicion\_index} \times 0.2) \times \text{mode\_mult}$.
     - $0.1 \le \text{synthesis\_score} = \text{round}(\min(1.0, \max(0.1, \text{raw\_synthesis})), 4) \le 1.0$.
   - 제2의 소박성 도달 여부 (`second_naivete_attained`):
     - `suspicion_filter_applied`가 참이고, `synthesis_score` $\ge 0.6$이며, 의심 사건 수가 $N // 2$ 이하인 경우 `true`, 아니면 `false`.

3. **Mimesis 3 (재-형상화 / Refiguration - 현상학적 시간과 세계 개시)**:
   - 현상학적 시간 팽창 계수 `phenomenological_time_factor`:
     - $\text{round}(1.0 + (\text{plot\_tension} \times 0.15) + (\text{promises\_count} \times 0.25), 4)$.
   - 세계 개시 심도 `world_disclosure_depth`:
     - $\text{round}(\min(1.0, \text{synthesis\_score} \times \text{horizon\_boost} \times (1.1 \text{ if second\_naivete else } 0.9)), 4)$.

4. **이야기 정체성 (Narrative Identity / Idem vs Ipse)**:
   - 동일성 안정도 `idem_stability` = $\text{round}(\max(0.1, 1.0 - (\text{trait\_modifications} \times 0.2)), 4)$.
   - 자기성 충실도 `ipse_fidelity`:
     - 약속(`PROMISE`)이 존재하면 $\min(1.0, \sum \text{fidelity\_cost} / \text{promises\_count})$, 없으면 0.5 (소수점 4자리 반올림).
   - 종합 이야기 정체성 지표 `narrative_identity_metric`:
     - $\text{round}(0.35 \times \text{idem\_stability} + 0.35 \times \text{ipse\_fidelity} + 0.30 \times \text{synthesis\_score}, 4)$.
   - 최종 상태 `identity_status`:
     - `metric` $\ge 0.75$ 이고 `ipse_fidelity` $\ge 0.7$ $\rightarrow$ `"NARRATIVE_IDENTITY_ACHIEVED"`
     - `ipse_fidelity` $< 0.5$ 이고 `idem_stability` $> 0.7$ $\rightarrow$ `"STAGNANT_IDEM_DOMINANCE"`
     - `metric` $< 0.5$ $\rightarrow$ `"EPISODIC_FRAGMENTATION"`
     - 그 외 $\rightarrow$ `"DIALECTICAL_TENSION_IN_PROGRESS"`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "subject_name": "Jean_Valjean",
  "mimesis_1_prefiguration": {
    "chronological_span": 9,
    "actions_count": 1,
    "contingencies_count": 1,
    "promises_count": 1,
    "prefig_score": 0.2333
  },
  "mimesis_2_configuration": {
    "emplotment_mode": "TRAGIC_TO_REDEMPTIVE",
    "plot_tension": 2.3,
    "suspicion_index": 0.0,
    "suspicious_event_ids": [],
    "synthesis_score": 0.8333,
    "second_naivete_attained": true
  },
  "mimesis_3_refiguration": {
    "refiguration_horizon": "ETHICAL_RESPONSIBILITY",
    "phenomenological_time_factor": 1.595,
    "world_disclosure_depth": 1.0
  },
  "narrative_identity": {
    "idem_stability": 0.8,
    "ipse_fidelity": 0.85,
    "narrative_identity_metric": 0.8275,
    "identity_status": "NARRATIVE_IDENTITY_ACHIEVED"
  }
}
```

---

## 제약 조건

- $1 \le \text{len(life\_events)} \le 500$
- $-1.0 \le \text{valence} \le 1.0$
- $0.0 \le \text{fidelity\_cost} \le 1.0$
- 모든 부동소수점 값은 규정된 반올림 규칙(`round(x, 4)`)을 따릅니다.
- 실행 시간 제한: 2.0초 이내
- 메모리 사용 제한: 256MB 이내
