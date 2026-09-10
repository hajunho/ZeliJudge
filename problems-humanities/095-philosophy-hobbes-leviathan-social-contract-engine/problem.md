# 토머스 홉스의 리바이어던: 자연상태(만인에 대한 만인의 투쟁), 사회계약 및 주권자의 칼 엔진

## 문제 설명

1651년 영국 내전의 참화 속에서 출간된 **토머스 홉스(Thomas Hobbes, 1588–1679)**의 『리바이어던(Leviathan)』은 근대 정치철학과 국가론의 기초를 놓은 기념비적 고전입니다.

공통의 통치 권력이 없는 상태, 즉 **자연상태(Status Naturalis)**에서 인간은 누구나 자기보존(Self-preservation)을 위해 모든 수단을 동원할 수 있는 무제한의 **자연권(Jus Naturale)**을 갖습니다. 그러나 인간의 신체적·정신적 능력은 대체로 평등하여, 가장 약한 자라도 계략이나 동맹을 통해 가장 강한 자를 살해할 수 있습니다.

이로부터 인간 본성의 세 가지 주요 분쟁 원인이 폭발합니다:
1. **경쟁(Competition)**: 이익과 재화를 얻기 위한 침략.
2. **불신(Diffidence)**: 안전을 지키기 위한 선제 공격.
3. **공명심(Glory)**: 명예와 평판을 지키기 위한 폭력.

그 결과 자연상태는 필연적으로 **"만인에 대한 만인의 투쟁(Bellum omnium contra omnes)"**으로 전락하며, 그 속에서 인간의 삶은 *"고독하고 가난하며 험악하고 잔인하며 짧은(solitary, poor, nasty, brutish, and short)"* 비참한 상태에 처하게 됩니다.

홉스는 죽음의 공포와 이성의 인도에 따라 인간이 자연법(Lex Naturalis)을 발견하고, 상호 간에 자신의 권리를 포기하여 단 하나의 인격인 **주권자(리바이어던, Leviathan)**에게 양도하는 **사회계약(Social Contract)**을 맺는다고 역설합니다:

> *"칼(Sword)이 없는 규약(Covenants)은 한낱 말(Words)에 불과하며, 인간을 안전하게 지킬 힘이 전혀 없다."*

```
                           +-------------------------------------+
                           |    공통 권력이 부재한 자연상태        |
                           +-------------------------------------+
                                              |
                                              v
         +-------------------------------------------------------------------------+
         |           만인에 대한 만인의 투쟁 (Bellum omnium contra omnes)          |
         |           경쟁(0.4) + 불신(0.35) + 공명심(0.25) -> 분쟁 지수(War Index)  |
         |           죽음의 공포 (Fear of Violent Death) 급증                       |
         +-------------------------------------------------------------------------+
                                              |
                                              v
         +-------------------------------------------------------------------------+
         |             사회계약(Covenant) 체결 & 주권자(Leviathan) 설립             |
         |             사회계약 비율(Covenant Ratio) * 주권자의 칼(Sword Power)    |
         +-------------------------------------------------------------------------+
                                              |
                         +--------------------+--------------------+
                         |                                         |
                 [주권자의 칼 결여]                        [강력한 칼과 독점적 강제력]
                Sword < 0.4 & 계약 체결                   Enforcement >= 0.65
                         |                                         |
                         v                                         v
              "칼 없는 규약은 말일 뿐"                   "리바이어던 질서 확립"
              (내전 및 약탈 재발)                        (평화 및 문명 지수 극대화)
```

본 문제에서는 홉스의 자연상태 갈등 역학, 상호 불신, 사회계약 서명, 그리고 주권자의 강제 집행력(칼)을 정밀하게 모사하는 **홉스 리바이어던 사회계약 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. 행위자(Agent) 파라미터
- `id`: 행위자 고유 식별자.
- `power` ($P_i \in [0.1, 1.0]$): 신체적/지적 능력.
- `distrust` ($D_i \in [0.0, 1.0]$): 타인에 대한 의심과 불신(Diffidence).
- `glory` ($G_i \in [0.0, 1.0]$): 명예와 공명심(Glory).
- `covenant_signed`: 사회계약 서명 여부 (초기값: `false`).

### 2. 자연상태 분쟁 지수 계산 (`evaluate_state`)
$N$명의 행위자에 대해 가능한 모든 쌍 $(i, j)$ ($i < j$)의 분쟁 강도를 계산합니다:
- **능력의 평등에 기인한 경쟁(Competition)**:
  $$C_{ij} = 1.0 - |P_i - P_j|$$
- **상호 불신(Diffidence)**:
  $$\Delta_{ij} = rac{D_i + D_j}{2.0}$$
- **공명심(Glory)**:
  $$\Gamma_{ij} = rac{G_i + G_j}{2.0}$$
- 쌍별 분쟁 강도:
  $$	ext{Conflict}_{ij} = \min(1.0, \max(0.0, 0.40 	imes C_{ij} + 0.35 	imes \Delta_{ij} + 0.25 	imes \Gamma_{ij}))$$
- **전체 전쟁 지수(War Index)**:
  $$W = 	ext{round}\left(rac{1}{inom{N}{2}} \sum_{i < j} 	ext{Conflict}_{ij}, 4ight)$$
- **폭력적 죽음의 공포(Fear of Death)**:
  $$	ext{Fear} = 	ext{round}(\min(1.0, W 	imes 1.2), 4)$$

### 3. 사회계약 및 주권자의 칼
- **계약 체결 비율(Covenant Ratio)**:
  $$R_{	ext{cov}} = 	ext{round}\left(rac{	ext{서명자 수}}{N}, 4ight)$$
- **주권자의 칼(Sword Power, $S_{	ext{sword}} \in [0.0, 1.0]$)**: 주권자가 보유한 물리적 강제력.
- **실효적 집행력(Enforcement)**:
  $$	ext{Enforcement} = 	ext{round}(\min(1.0, S_{	ext{sword}} 	imes R_{	ext{cov}}), 4)$$
- **잔여 분쟁 지수(Residual Conflict)**:
  $$	ext{Conflict}_{	ext{res}} = 	ext{round}(\max(0.0, W 	imes (1.0 - 	ext{Enforcement})), 4)$$
- **문명 지수(Civilization Index)**:
  $$	ext{Civilization} = 	ext{round}(\min(1.0, 	ext{Enforcement} 	imes (1.0 - 	ext{Conflict}_{	ext{res}})), 4)$$

### 4. 체제 상태 분류 (`state`)
1. $	ext{Enforcement} \ge 0.65$:
   - `state`: `"LEVIATHAN_ORDER"`
   - `verdict`: `"리바이어던 확립: 주권자의 칼에 의한 절대 평화 및 사회계약 이행"`
2. $R_{	ext{cov}} \ge 0.50$ 이고 $S_{	ext{sword}} < 0.40$:
   - `state`: `"WORDS_WITHOUT_SWORD"`
   - `verdict`: `"칼 없는 규약은 한낱 말에 불과함: 강제력 결여로 인한 계약 불이행 및 내전 위험"`
3. 그 외:
   - `state`: `"BELLUM_OMNIUM_CONTRA_OMNES"`
   - `verdict`: `"만인에 대한 만인의 투쟁: 고독하고 가난하며 험악하고 잔인하며 짧은 삶"`

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "sovereign_sword_power": 0.0
  },
  "operations": [
    { "op": "ADD_AGENT", "id": "A", "power": 0.8, "distrust": 0.8, "glory": 0.7 },
    { "op": "ADD_AGENT", "id": "B", "power": 0.85, "distrust": 0.9, "glory": 0.6 },
    { "op": "EVALUATE_STATE" },
    { "op": "SIGN_COVENANT", "id": "A" },
    { "op": "SIGN_COVENANT", "id": "B" },
    { "op": "SET_SWORD", "sword_power": 0.95 },
    { "op": "EVALUATE_STATE" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- 행위자 수 $2 \le N \le 200$
- $0.0 \le 	ext{distrust}, 	ext{glory}, 	ext{sword\_power} \le 1.0$
- $0.1 \le 	ext{power} \le 1.0$
- 시간 복잡도: 각 상태 평가 $O(N^2)$, 전체 $O(M \cdot N^2)$ 이내.
