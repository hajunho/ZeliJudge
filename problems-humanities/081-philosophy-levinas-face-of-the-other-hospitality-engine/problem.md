# 에마뉘엘 레비나스의 타자의 얼굴: 전체성과 무한, 무한 책임 및 환대 윤리학 엔진 (Emmanuel Levinas's Ethics of the Face: Totality and Infinity, Infinite Responsibility & Hospitality Engine)

## 문제 설명

20세기 서구 철학은 플라톤과 파르메니데스로부터 칸트, 헤겔, 하이데거에 이르기까지 존재(Being)를 인식하고 체계화한다는 명목하에, 모든 이질적인 것을 자아의 범주 즉 **'동일자(The Same / Le Même)'** 속으로 포섭하고 환원하는 거대한 **'전체성(Totality)'의 존재론**을 구축해 왔습니다. 리투아니아 출신의 프랑스 유대인 철학자 **에마뉘엘 레비나스(Emmanuel Levinas, 1906~1995)**는 홀로코스트의 비극을 겪으며, 타자를 나의 앎과 힘의 지배 아래 두려는 이 존재론적 사유 방식이야말로 인류 문명사적 폭력과 전체주의의 뿌리임을 폭로했습니다.

레비나스는 1961년 불후의 저작 『전체성과 무한(Totalité et Infini)』과 1974년 『존재와 다르게(Autrement qu'être)』를 통해, 존재론보다 윤리학이 앞서는 **"윤리학이야말로 제1철학(Ethics as First Philosophy)"**임을 선언했습니다:
1. **타자의 얼굴(The Face of the Other / Le Visage d'Autrui)**:
   - 타자의 얼굴은 감각적 외모나 시각적 대상이 아닙니다. 그것은 나의 주체적 세계를 뒤흔들며 다가오는 절대적 타자성(Alterity)이자 **무한(Infinity)**의 현현입니다.
   - 얼굴은 가난하고, 굶주리며, 발가벗겨진(Nakedness) 원초적 취약성 속에서 나를 향해 명령합니다: **"너는 살인하지 말라(Tu ne commettras point de meurtre)."**
2. **무한 책임과 대리(Substitution)**:
   - 타자의 얼굴을 마주한 순간, 나는 더 이상 자아도취적 향유에 머물 수 없으며 타자의 고통에 대해 핑계를 댈 수 없는 **윤리적 인질(Hostage)**이 됩니다. 타자가 나에게 빚진 것에 상관없이 나의 책임은 무한히 증폭됩니다.
3. **무조건적 환대(Unconditional Hospitality)**:
   - 나의 집(Dwelling)과 소유의 빗장을 풀고, 이방인과 고아와 과부를 기꺼이 맞아들이는 실존적 결단입니다.

당신은 철학적 인문 컴퓨팅 연구원으로서, **동일자의 전체성 지수($TotalityIndex$), 타자의 얼굴에 대한 책임 지수($ResponsibilityIndex$), 무조건적 환대 점수($HospitalityScore$)를 추적하고 주체의 윤리적 상태($EthicalState$) 전이를 판정하는 레비나스 윤리학 시뮬레이션 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|     Emmanuel Levinas: Ethics of the Face & Hospitality Engine           |
+-------------------------------------------------------------------------+
| [Egocentric Enjoyment / The Totalitarian Same]                          |
|   - Possession Drive & Economic Enclosure (Reducing Other to the Same)  |
|   - Totality: Denial of Alterity & Ontological Imperialism              |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Epiphany of the Face / Infinity Breaks In]                             |
|   - Nakedness & Extreme Vulnerability of the Other                      |
|   - The Injunction: "Thou Shalt Not Kill!" (Moral Shock)                |
|   - The Self as Ethical Hostage (Asymmetrical Infinite Responsibility)  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [The Ethical Summit: Substitution & Unconditional Hospitality]          |
|   - Opening the Dwelling to the Stranger, Widow, and Orphan             |
|   - Radical Substitution: Bearing the Suffering of the Other            |
|   - Ethical Subjecthood: "Here I Am!" (Me Voici)                        |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 수리적 모델링

### 1. 주체 상태 파라미터 (`config`)
- `subject_id`: 주체 식별자 (문자열)
- `initial_responsiveness`: 타자의 부름에 대한 주체의 초기 윤리적 응답성 $R_{resp} \in [0.0, 1.0]$
- `initial_possession_drive`: 자아의 초기 소유 및 동일화 충동 $P_{drive} \in [0.0, 1.0]$
- `initial_vulnerability`: 마주한 타자의 원초적 취약성 $V_{vuln} \in [0.0, 1.0]$
- `initial_appeal_intensity`: 타자의 얼굴이 보내는 호소의 강도 $A_{appeal} \in [0.0, 1.0]$
- `initial_substitution`: 타자를 대신하여 고통을 짊어지는 대리(Substitution) 수준 $S_{sub} \in [0.0, 1.0]$

모든 파라미터는 매 단계 $[0.0, 1.0]$ 범위로 엄격히 클램핑됩니다.

### 2. 핵심 지표 계산 수식

1. **전체성 지수 ($TotalityIndex$)**:
   - 타자의 이질성을 파괴하고 동일자의 지배권 아래 두려는 폭력성:
     $$TotalityIndex = \min\left(1.0, (1.0 - R_{resp}) 	imes 0.7 + P_{drive} 	imes 0.3ight)$$
2. **무한 책임 지수 ($ResponsibilityIndex$)**:
   - 타자의 취약성과 호소 앞에서 발생하는 비대칭적 윤리적 책무성:
     $$ResponsibilityIndex = \min\left(1.0, V_{vuln} 	imes A_{appeal} 	imes 0.6 + R_{resp} 	imes 0.4ight)$$
3. **무조건적 환대 점수 ($HospitalityScore$)**:
   - 소유의 폐쇄성을 극복하고 타자를 영접하는 환대의 실현도:
     $$Score = R_{resp} 	imes 0.45 + (1.0 - TotalityIndex) 	imes 0.35 + S_{sub} 	imes 0.20$$
     $$HospitalityScore = \min\left(1.0, \max\left(0.0, Scoreight)ight)$$
   (모든 계산값은 소수점 4자리로 반올림)

### 3. 윤리적 상태 ($EthicalState$) 판정 우선순위
1. $HospitalityScore \ge 0.70$ 이고 $ResponsibilityIndex \ge 0.60$: **`"INFINITE_HOSPITALITY"`** (타자를 향해 전면 개방된 무한 환대 상태)
2. $TotalityIndex \ge 0.65$: **`"TOTALITARIAN_APPROPRIATION"`** (타자를 동일자로 흡수·지배하는 전체주의적 폭력)
3. $ResponsibilityIndex \ge 0.60$: **`"ETHICAL_HOSTAGE"`** (타자의 고통 앞에서 윤리적 인질이 된 책임 주체)
4. $V_{vuln} \ge 0.65$: **`"VULNERABLE_FACE_REVEALED"`** (타자의 벌거벗은 취약성이 현현한 상태)
5. 그 외: **`"EGOCENTRIC_SELF"`** (자아 중심적 향유에 머무는 동일자 상태)

### 4. 시뮬레이션 이벤트 액션
- `EGOISTIC_ENJOYMENT` (자아도취적 소유와 향유, 강도 $I$):
  - $P_{drive} \leftarrow \min(1.0, P_{drive} + I 	imes 0.3)$
  - $R_{resp} \leftarrow \max(0.0, R_{resp} - I 	imes 0.35)$
- `EPIPHANY_OF_THE_FACE` (타자 얼굴의 현현, 강도 $I$):
  - $V_{vuln} \leftarrow \min(1.0, V_{vuln} + I 	imes 0.35)$
  - $A_{appeal} \leftarrow \min(1.0, A_{appeal} + I 	imes 0.4)$
  - $R_{resp} \leftarrow \min(1.0, R_{resp} + I 	imes 0.3)$
  - $P_{drive} \leftarrow \max(0.0, P_{drive} - I 	imes 0.25)$
- `COMMANDMENT_DO_NOT_KILL` ("살인하지 말라"는 절대적 금기, 강도 $I$):
  - $P_{drive} \leftarrow \max(0.0, P_{drive} - I 	imes 0.45)$
  - $R_{resp} \leftarrow \min(1.0, R_{resp} + I 	imes 0.35)$
  - $S_{sub} \leftarrow \min(1.0, S_{sub} + I 	imes 0.25)$
- `TOTALIZING_DOMINATION` (전체주의적 지배 시도, 강도 $I$):
  - $P_{drive} \leftarrow \min(1.0, P_{drive} + I 	imes 0.4)$
  - $R_{resp} \leftarrow \max(0.0, R_{resp} - I 	imes 0.4)$
  - $V_{vuln} \leftarrow \min(1.0, V_{vuln} + I 	imes 0.3)$
- `RADICAL_SUBSTITUTION` (타자를 대신하는 대리의 고통, 강도 $I$):
  - $S_{sub} \leftarrow \min(1.0, S_{sub} + I 	imes 0.45)$
  - $R_{resp} \leftarrow \min(1.0, R_{resp} + I 	imes 0.4)$
  - $P_{drive} \leftarrow \max(0.0, P_{drive} - I 	imes 0.4)$
- `UNCONDITIONAL_HOSPITALITY` (무조건적 환대의 개방, 강도 $I$):
  - $R_{resp} \leftarrow \min(1.0, R_{resp} + I 	imes 0.45)$
  - $P_{drive} \leftarrow \max(0.0, P_{drive} - I 	imes 0.35)$
  - $S_{sub} \leftarrow \min(1.0, S_{sub} + I 	imes 0.3)$

---

## 입력 형식

표준 입력(`sys.stdin`)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "subject_id": "ISOLATED_EGO_01",
    "initial_responsiveness": 0.4,
    "initial_possession_drive": 0.5,
    "initial_vulnerability": 0.3,
    "initial_appeal_intensity": 0.3,
    "initial_substitution": 0.1
  },
  "events": [
    {"action": "EGOISTIC_ENJOYMENT", "intensity": 0.4}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 공백 없는 압축 JSON(`separators=(',', ':')`)을 출력합니다:
```json
{
  "final_metrics": {
    "ethical_state": "TOTALITARIAN_APPROPRIATION",
    "hospitality_score": 0.2406,
    "responsibility_index": 0.158,
    "totality_index": 0.704
  },
  "parameters": {
    "appeal_intensity": 0.3,
    "other_vulnerability": 0.3,
    "possession_drive": 0.62,
    "responsiveness": 0.26,
    "substitution_level": 0.1
  },
  "subject_id": "ISOLATED_EGO_01",
  "trajectory": [
    {
      "ethical_state": "EGOCENTRIC_SELF",
      "event": "INIT",
      "hospitality_score": 0.339,
      "responsibility_index": 0.214,
      "step": 0,
      "totality_index": 0.57
    },
    {
      "ethical_state": "TOTALITARIAN_APPROPRIATION",
      "event": "EGOISTIC_ENJOYMENT",
      "hospitality_score": 0.2406,
      "responsibility_index": 0.158,
      "step": 1,
      "totality_index": 0.704
    }
  ]
}
```
