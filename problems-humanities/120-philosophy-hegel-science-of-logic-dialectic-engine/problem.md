# 게오르크 빌헬름 프리드리히 헤겔: 대논리학(Wissenschaft der Logik) — 존재론·본질론·개념론, 척도의 마디선과 모순의 지양 엔진

## 문제 설명

독일 관념론의 완성자 **게오르크 빌헬름 프리드리히 헤겔(G.W.F. Hegel, 1770~1831)**은 1812~1816년에 걸쳐 출간한 불멸의 명저 **『대논리학(Wissenschaft der Logik)』**을 통해, 서양 2,500년 형이상학과 형식 논리학(아리스토텔레스의 동일률, 모순율, 배중률)을 완전히 해체하고, 사유와 존재가 자기 자신을 전개해 나가는 **사변적 변증법(Speculative Dialectic)**의 대체계를 완성했습니다.

헤겔 논리학은 단순한 주관적 사고의 형식적 규칙이 아니라, 실재(Reality)의 근본 범주들이 자신의 내적 모순을 통해 스스로를 운동시키고 고차원으로 지양(Aufhebung)해 나가는 존재론적 생명력의 자기 서술입니다:

```
               [ 게오르크 W.F. 헤겔의 대논리학 3대 권역 (Drei Sphären) ]
                                          |
          +-------------------------------+-------------------------------+
          |                               |                               |
          v                               v                               v
 [ 1. 존재론 (Lehre vom Sein) ]  [ 2. 본질론 (Lehre vom Wesen) ]  [ 3. 개념론 (Lehre vom Begriff) ]
 - 순수 존재와 순수 무           - 반성 규정 (Reflexionsbestimmungen) - 주관적 개념 (보편·특수·개별)
   -> 생성(Werden) -> 규정적      동일성 -> 차이 -> 대립 -> 모순      - 객관성 (기계론·화학론·목적론)
      존재(Dasein)                "모순은 모든 운동과 생명의 뿌리"      - 이념 (생명·인식)
 - 질(Quality)과 양(Quantity)     - 근거(Grund)와 현실성(Wirklichkeit) - 절대 이념 (Absolute Idee)
 - 척도와 마디선(Knotenlinie)                                      - 자기 자신을 이해하는 방법
   (양적 축적 -> 질적 비약)
```

### 핵심 철학 원리 및 상태 머신 메커니즘

1. **존재론(The Doctrine of Being)과 척도의 마디선 (`Knotenlinie von Maßverhältnissen`)**:
   - `DIALECTICAL_BECOMING`: 아무런 규정도 없는 순수 존재(Pure Being)는 그 공허함으로 인해 순수 무(Pure Nothing)로 전환되며, 둘의 통일인 **생성(Becoming)**을 거쳐 구체적 성질을 갖는 **규정적 존재(`DETERMINATE_BEING_DASEIN`)**로 정립됩니다.
   - `QUANTITATIVE_SHIFT`: 양은 질을 파괴하지 않고 증감할 수 있는 연속적 크기이지만, 척도(Maß)의 한계점인 **마디선(Knotenlinie)**에 도달하면 양적 변화가 돌연 단절되어 **질적 도약(`QUALITATIVE_NODAL_LEAP`)**을 일으킵니다 (예: 물의 $0^\circ	ext{C}$ 빙결 및 $100^\circ	ext{C}$ 기화 상전이).

2. **본질론(The Doctrine of Essence)과 모순(`Widerspruch`)의 심화**:
   - 본질은 단순한 직접성이 아니라 자기 자신으로의 반성(Reflexion)입니다.
   - `REFLECTIVE_CONTRADICTION` 연산은 반성의 4대 계기를 순차적으로 전개합니다:
     $$	ext{IDENTITY} \longrightarrow 	ext{DIFFERENCE} \longrightarrow 	ext{OPPOSITION} \longrightarrow 	ext{CONTRADICTION} \longrightarrow 	ext{GROUND}$$
   - 형식논리학은 모순을 기피하지만, 헤겔에게 모순은 **"모든 운동과 생명력의 뿌리(Wurzel aller Bewegung und Lebendigkeit)"**입니다. 모순이 정점에 달하면 사태는 붕괴하는 것이 아니라 자신의 바닥인 **근거(`GROUND`)**로 가라앉아 **현실성(`ACTUALITY_WIRKLICHKEIT`)**으로 지양됩니다.

3. **개념론(The Doctrine of the Concept)과 절대이념의 종합**:
   - `NOTION_MOMENT`: 개념은 **보편(Universal)**, **특수(Particular)**, **개별(Individual)**의 3대 계기를 가집니다.
   - 세 모멘트가 모두 결합되어 통일을 이룰 때, 대논리학의 궁극적 정점인 **절대이념(`ABSOLUTE_IDEA`)**으로 완성되며, 이는 변증법적 방법 그 자체가 스스로를 의식하는 절대적 사변적 진리(`ABSOLUTE_SPECULATIVE_TRUTH`)를 구성합니다.

본 문제에서는 존재론의 생성 및 마디선 질적 비약, 본질론의 반성 모순 전개, 개념론의 3대 계기 종합을 완벽히 모델링한 헤겔 대논리학 변증법 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "concept": "WATER_PHASE_TRANSITION",
  "sphere": "BEING",
  "quality": "LIQUID_WATER",
  "quantity": 20.0,
  "measure_nodes": [
    {"threshold": 100.0, "leap_quality": "GASEOUS_STEAM", "leap_sphere": "ESSENCE"}
  ],
  "operations": [
    {"op": "QUANTITATIVE_SHIFT", "delta": 30.0},
    {"op": "QUANTITATIVE_SHIFT", "delta": 60.0},
    {"op": "REFLECTIVE_CONTRADICTION"},
    {"op": "REFLECTIVE_CONTRADICTION"},
    {"op": "REFLECTIVE_CONTRADICTION"},
    {"op": "REFLECTIVE_CONTRADICTION"},
    {"op": "NOTION_MOMENT", "moment": "UNIVERSAL"},
    {"op": "NOTION_MOMENT", "moment": "PARTICULAR"},
    {"op": "NOTION_MOMENT", "moment": "INDIVIDUAL"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "concept": "WATER_PHASE_TRANSITION",
  "initial_state": {
    "sphere": "BEING",
    "quality": "LIQUID_WATER",
    "quantity": 20.0
  },
  "final_state": {
    "sphere": "ABSOLUTE_IDEA",
    "quality": "ABSOLUTE_IDEA_SELF_COMPREHENDING_METHOD",
    "quantity": 110.0,
    "reflection_stage": "GROUND",
    "notion_moments": {
      "universal": true,
      "particular": true,
      "individual": true
    },
    "negation_count": 3,
    "verdict": "ABSOLUTE_SPECULATIVE_TRUTH"
  },
  "stats": {
    "quantitative_increments": 2,
    "nodal_leaps": 1,
    "contradictions_surmounted": 1,
    "aufhebung_syntheses": 3
  },
  "op_log": [
    {
      "op": "QUANTITATIVE_SHIFT",
      "old_quantity": 20.0,
      "new_quantity": 50.0,
      "status": "GRADUAL_ACCUMULATION_NO_LEAP",
      "quality": "LIQUID_WATER"
    }
  ]
}
```
