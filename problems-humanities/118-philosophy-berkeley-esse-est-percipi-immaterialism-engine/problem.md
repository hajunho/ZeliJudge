# 조지 버클리: 비물질주의(Immaterialism), "존재하는 것은 지각되는 것이다(Esse est percipi)" 및 신적 지각 보증 엔진

## 문제 설명

18세기 아일랜드의 철학자이자 주교인 **조지 버클리(George Berkeley, 1685~1753)**는 존 로크(John Locke)의 경험주의를 철저히 밀고 나가, 서양 철학사상 가장 대담하고 급진적인 명제를 제시했습니다:
> **"존재하는 것은 지각되는 것이다 (Esse est percipi / To be is to be perceived)."**

버클리는 1710년 『인간 지식의 원리론(A Treatise Concerning the Principles of Human Knowledge)』과 1713년 『하일라스와 필로누스의 세 대화(Three Dialogues between Hylas and Philonous)』를 통해, 마음 외부에 독립적으로 실재한다는 소위 **"물질적 기체(Material Substratum)"**라는 개념이 사유 불가능한 허구이자 자기모순임을 논증했습니다.

```
 [전통적 소박 실재론 / 로크의 물질관]
 [관찰자의 마음] <=== (감각 표상) === [물질적 실체 (Material Substratum)] <--- 보이지도 만져지지도 않는 허구!
                                    - 제1성질: 연장, 형태, 운동 (객관적)
                                    - 제2성질: 색, 맛, 냄새, 소리 (주관적)

 [버클리의 비물질주의 / 주관적 관념론]
 [인간 관찰자] (Mortal Observer)  ---> 시야 내 대상 직접 지각 (PERCEIVED_BY_MORTAL_MIND)
             \                          - 제1성질과 제2성질 모두 '마음속 관념(Ideas)'으로 붕괴!
              \                         - 물질적 기체는 완전 소멸 (ANNIHILATED_FICTION)
               +--------+
                        |
 [영원한 신적 지각자] (Divine Mind) ---> 인간이 보지 않는 숲속의 나무도 항상 지각 (SUSTAINED_BY_DIVINE_PERCEPTION)
 (상시적 우주 렌더링 유지)               (신이 없으면 독아론적 비존재의 공허로 소멸!)
```

### 핵심 철학 원리
1. **제1성질과 제2성질의 동일한 관념화 (Collapse of Primary Qualities)**:
   - 로크는 색과 열(제2성질)은 주관적이지만 연장과 형태(제1성질)는 물질 자체에 속한다고 보았습니다.
   - 버클리는 크기와 형태 역시 관찰자의 거리와 시각에 따라 상대적으로 변하므로, 연장(Extension)과 운동 역시 마음에 지각되는 '관념(Idea)'에 불과함을 입증했습니다.
2. **물질적 기체(Material Substratum)의 완전 소멸**:
   - 감각되는 모든 성질(색, 촉감, 크기)을 제거하고 남는 순수한 '물질 자체'는 아무런 성질도 없는 무(Nothing)이며, 따라서 물질적 실체는 언어적 기만에 불과합니다.
3. **신의 상시적 지각 보증 (Divine Guarantee)**:
   - "숲속에서 아무도 보지 않을 때 나무는 존재하는가?"
   - 버클리의 해답: 인간이 잠들거나 외면할 때도, 전지한 신(Omnipresent Perceiver)이 언제나 우주 전체를 끊임없이 지각하고 있기 때문에 세계의 연속성과 객관적 자연법칙이 유지됩니다.
   - 신적 보증이 차단될 경우, 지각되지 않는 모든 사물은 즉시 비존재(`ANNIHILATED_NON_EXISTENT`)로 소멸합니다.

현대 컴퓨터 그래픽스에서 플레이어의 시야각(Frustum)에 들지 않는 폴리곤을 메모리에서 컬링(Culling)하여 렌더링하지 않는 메커니즘은 버클리의 "Esse est percipi"와 완벽하게 일치합니다.

본 문제에서는 관찰자들의 시야 필드, 신적 영구 지각자의 유지 여부, 제1/제2성질의 관념화 및 물질적 실체 소멸을 판정하는 버클리 존재론 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "observers": [
    {
      "id": "philonous",
      "role": "MORTAL_OBSERVER",
      "focus_field": ["ripe_cherry"],
      "active": true
    },
    {
      "id": "divine_mind",
      "role": "OMNIPRESENT_PERCEIVER",
      "focus_field": "ALL",
      "active": true
    }
  ],
  "candidate_entities": [
    {
      "id": "ripe_cherry",
      "qualities": {
        "primary": {"extension_m": 0.02, "figure": "SPHERE"},
        "secondary": {"color": "RED", "taste": "SWEET"}
      },
      "alleged_matter_substratum": true
    },
    {
      "id": "unseen_mountain",
      "qualities": {
        "primary": {"extension_m": 2000.0},
        "secondary": {"color": "BLUE"}
      },
      "alleged_matter_substratum": true
    }
  ],
  "epistemological_rules": {
    "collapse_primary_into_secondary": true,
    "reject_abstract_general_ideas": true,
    "divine_guarantee_enabled": true
  }
}
```

### 파라미터 규격
- `observers` (배열): 관찰자 목록.
  - `role`: `"MORTAL_OBSERVER"` (유한한 인간 관찰자) 또는 `"OMNIPRESENT_PERCEIVER"` (신적 지각자).
  - `focus_field`: 유한 관찰자의 경우 현재 바라보는 엔티티 ID 목록, 신적 지각자는 `"ALL"`.
  - `active`: 활성 상태 여부 (불리언).
- `candidate_entities` (배열): 존재 검증 대상 사물 목록.
  - `id`: 엔티티 식별자.
  - `qualities`: `primary`(연장, 형태) 및 `secondary`(색, 맛 등).
  - `alleged_matter_substratum`: 물질적 기체 가설 보유 여부 (불리언).
- `epistemological_rules` (객체):
  - `collapse_primary_into_secondary`: 제1성질의 관념화 규칙 적용 여부 (기본 `true`).
  - `divine_guarantee_enabled`: 신의 상시적 지각 보증 활성화 여부 (기본 `true`).

---

## 계산 명세

1. **지각 주체 판정 (`perceived_by`) 및 존재론적 상태 (`ontological_status`)**:
   - 엔티티 $E$가 활성 상태인 인간 관찰자의 `focus_field`에 포함되면:
     - `ontological_status = "PERCEIVED_BY_MORTAL_MIND"`, `perceived_by = "MORTAL"`.
   - 포함되지 않으나 신적 지각자(`OMNIPRESENT_PERCEIVER`)가 활성 상태이고 `divine_guarantee_enabled`가 참이면:
     - `ontological_status = "SUSTAINED_BY_DIVINE_PERCEPTION"`, `perceived_by = "DIVINE"`.
   - 둘 다 해당하지 않으면:
     - `ontological_status = "ANNIHILATED_NON_EXISTENT"`, `perceived_by = "NONE"`.

2. **제1성질 붕괴 및 물질적 기체 소멸**:
   - `all_qualities_are_ideas`: `collapse_primary_into_secondary`가 참이면 `true`, 아니면 `false`.
   - `material_substratum`: `alleged_matter_substratum`이 참이면 `"ANNIHILATED_FICTION"`, 거짓이면 `"NONE"`.

3. **최종 형이상학적 판정 (`metaphysical_verdict`)**:
   - 신적 보증이 없고 비존재로 소멸한 엔티티가 1개 이상이면:
     - `"SOLIPSISTIC_COLLAPSE_WITHOUT_DIVINITY"`
   - 모든 엔티티의 성질이 관념으로 붕괴되었고, 소멸된 물질적 기체가 1개 이상이면:
     - `"IMMATERIALIST_TRIUMPH_ESSE_EST_PERCIPI"`
   - 그 외:
     - `"DOGMATIC_MATERIALIST_RELAPSE"`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "metaphysical_verdict": "IMMATERIALIST_TRIUMPH_ESSE_EST_PERCIPI",
  "stats": {
    "total_entities": 2,
    "mortal_perceived_count": 1,
    "divine_sustained_count": 1,
    "non_existent_void_count": 0,
    "material_substrata_annihilated": 2
  },
  "entity_evaluations": [
    {
      "entity_id": "ripe_cherry",
      "ontological_status": "PERCEIVED_BY_MORTAL_MIND",
      "perceived_by": "MORTAL",
      "all_qualities_are_ideas": true,
      "material_substratum": "ANNIHILATED_FICTION"
    },
    {
      "entity_id": "unseen_mountain",
      "ontological_status": "SUSTAINED_BY_DIVINE_PERCEPTION",
      "perceived_by": "DIVINE",
      "all_qualities_are_ideas": true,
      "material_substratum": "ANNIHILATED_FICTION"
    }
  ]
}
```

---

## 제약 조건

- $1 \le \text{len(observers)} \le 20$
- $1 \le \text{len(candidate\_entities)} \le 50$
- 실행 시간 제한: 2.0초 이내
- 메모리 사용 제한: 256MB 이내
