# 아르투어 쇼펜하우어의 의지와 표상: 삶의 진자(고통 대 권태), 미적 관조 및 의지의 부정 엔진

## 문제 설명

1818년 독일의 철학자 **아르투어 쇼펜하우어(Arthur Schopenhauer, 1788–1860)**는 서양 철학사상 가장 독창적이면서도 염세적인 걸작 『의지와 표상으로서의 세계(Die Welt als Wille und Vorstellung)』를 발표했습니다.

칸트의 '물자체(Ding an sich)'를 비합목적적이고 맹목적인 **'살려는 의지(Wille zum Leben)'**로 규명한 쇼펜하우어는, 인간이 공간·시간·인과율이라는 개별화의 원리(Principium Individuationis / 마야의 베일)에 갇혀 끊임없는 욕망의 충족과 결핍 사이에서 고통받는다고 보았습니다:

> *"모든 의욕은 결핍에서, 즉 자신의 상태에 대한 불만족에서 생겨나므로 그것이 채워지지 않는 한 고통이다. 그러나 어떠한 만족도 지속되지 않으며, 하나의 욕망이 채워지면 즉시 또 다른 욕망이 생긴다. 결국 삶은 고통(Pain)과 권태(Boredom) 사이를 시계추처럼 왔다 갔다 하는 진자(Pendel) 운동에 불과하다."*

쇼펜하우어는 이 맹목적인 의지의 형벌에서 벗어날 수 있는 세 가지 구원의 길을 제시했습니다:
1. **예술과 미적 관조(Ästhetische Kontemplation)**: 특히 의지의 직접적 모사인 **음악(Music)**을 통해, 고통받는 개별 주체에서 벗어나 **순수한 무의지적 인식의 주체(reines, willenloses Subjekt des Erkennens)**로 일시적 해탈을 경험하는 것.
2. **동포애적 연민(Mitleid / Tat Tvam Asi)**: 개별화의 환상인 마야(Maya)의 베일을 찢고, 타인의 고통이 곧 나의 고통이며 모든 생명체가 단 하나의 거대한 의지의 현현임을 깨닫는 윤리적 자각.
3. **살려는 의지의 부정(Verneinung des Willens zum Leben)**: 금욕주의(Asceticism)와 무소유를 통해 의지의 갈망 자체를 소멸시키고 성스러운 평정과 열반(Nirvana)에 도달하는 궁극적 해탈.

```
                           +-------------------------------------+
                           |    맹목적 물자체: 살려는 의지 (W)    |
                           +-------------------------------------+
                                              |
                                              v
         +-------------------------------------------------------------------------+
         |                 삶의 진자(Pendel): 결핍과 충족의 끝없는 동요             |
         |                 고통 P = W * (1 - F)  vs  권태 B = W * F * 0.75         |
         |                 순수 고통도 Net Suffering = min(1.0, P + 0.6 * B)        |
         +-------------------------------------------------------------------------+
                                              |
               +------------------------------+------------------------------+
               |                              |                              |
               v                              v                              v
      [1. 미적 관조 / 음악]         [2. 윤리적 연민 (Mitleid)]     [3. 의지의 부정 (금욕)]
      alpha * Art_Power >= 0.5      (1 - Maya) >= 0.5             Quietive >= 0.55
      순수 무의지적 주체 전환        "Tat Tvam Asi (네가 그것이다)"   마야의 베일 완전 해체
      고통의 일시적 정지             만물일체적 자비와 고통 공유     성스러운 열반(Nirvana)
```

본 문제에서는 쇼펜하우어 형이상학과 삶의 진자 운동, 그리고 3단계 해탈의 메커니즘을 정밀하게 수리적으로 모델링한 **쇼펜하우어 의지와 표상 시뮬레이션 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. 주체 파라미터
- `will_intensity` ($W \in [0.0, 1.0]$): 주체를 지배하는 맹목적 생의 의지 강도.
- `fulfillment_ratio` ($F \in [0.0, 1.0]$): 현재 욕망의 충족도 (0: 완전 결핍, 1: 완전 충족).
- `maya_illusion` ($M \in [0.0, 1.0]$): 개별화의 원리(Principium Individuationis)에 대한 맹신도 (기본값: 0.8).
- `aesthetic_attunement` ($lpha \in [0.0, 1.0]$): 예술적 감수성 및 미적 몰입 역량 (기본값: 0.5).
- `ascetic_discipline` ($eta \in [0.0, 1.0]$): 금욕적 자기부정 및 의지 억제 규율 (기본값: 0.3).
- `art_genre`: 예술 장르 문자열 (`ARCHITECTURE`: 0.4, `SCULPTURE`: 0.5, `PAINTING`: 0.6, `POETRY`: 0.7, `TRAGEDY`: 0.8, `MUSIC`: 1.0, 기본값: `MUSIC`).

### 2. 삶의 진자(Pendulum) 및 고통 계산
1. **결핍의 고통(Pain)**:
   $$P = \text{round}(W \times (1.0 - F), 4)$$
2. **충족의 권태(Boredom)**:
   $$B = \text{round}(W \times F \times 0.75, 4)$$
3. **순수 실존적 고통(Net Suffering)**:
   $$S = \text{round}(\min(1.0, P + 0.6 \times B), 4)$$

### 3. 구원 및 승화 지표
1. **미적 관조와 의지의 정지(Will Suspension)**:
   $$\text{will\_suspension} = \text{round}(\min(1.0, \alpha \times \text{Art\_Power}), 4)$$
   - 관조 중 체감 고통:
     $$\text{suffering\_in\_art} = \text{round}(S \times (1.0 - \text{will\_suspension}), 4)$$
2. **동포애적 연민(Compassion / Mitleid)**:
   - 개별화의 환상 $M$을 걷어내고 타자의 고통에 공감하는 지표:
     $$\text{compassion} = \text{round}(\min(1.0, (1.0 - M) \times (0.5 + 0.5 \times \beta)), 4)$$
3. **의지의 부정(Quietive of the Will)**:
   - 금욕을 통해 삶에 대한 갈망을 잠재우는 진정제(Quietiv) 지표:
     $$\text{quietive} = \text{round}(\min(1.0, \beta \times (1.0 - M) \times (1.0 - 0.3 \times W)), 4)$$

### 4. 실존 상태 판정 (`stance`)
다음 우선순위에 따라 주체의 최종 실존 상태를 결정합니다:
1. $\text{quietive} \ge 0.55$:
   - `stance`: `"ASCETIC_NIRVANA"`
   - `verdict`: `"의지의 부정(Verneinung des Willens zum Leben): 마야의 장막을 찢고 도달한 성스러운 무욕과 열반"`
2. $\text{will\_suspension} \ge 0.50$:
   - `stance`: `"AESTHETIC_TRANSCENDENCE"`
   - `verdict`: `"순수한 무의지적 인식의 주체: 예술과 음악을 통한 고통의 일시적 정지"`
3. $\text{compassion} \ge 0.50$:
   - `stance`: `"ETHICAL_COMPASSION"`
   - `verdict`: `"동포애적 연민(Mitleid): 타트 트밤 아시(Tat Tvam Asi), 타인의 고통을 나의 고통으로 체현"`
4. 그 외:
   - `stance`: `"PENDULUM_SUFFERING"`
   - `verdict`: `"의지의 진자(Pendel): 결핍의 고통과 충족의 권태 사이를 영구 방황하는 개별화의 망상"`

### 5. 진자 궤적 시뮬레이션 (`SIMULATE_PENDULUM`)
- 입력: `will_intensity`, `steps` (기본 5), 기타 파라미터.
- 각 단계 $i = 0, 1, \dots, \text{steps}-1$에서 충족도 $F$는 사인파 궤적을 따릅니다:
  $$F = \text{round}\left(0.5 + 0.5 \times \sin\left(i \times \frac{\pi}{2}\right), 2\right)$$
- 각 단계마다 `EVALUATE_SUBJECT`를 수행하고, $P > B$이면 `phase = "PAIN"`, 아니면 `phase = "BOREDOM"`으로 기록합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "default_art": "MUSIC"
  },
  "operations": [
    {
      "op": "EVALUATE_SUBJECT",
      "params": {
        "will_intensity": 0.85,
        "fulfillment_ratio": 0.15,
        "maya_illusion": 0.85,
        "aesthetic_attunement": 0.20,
        "ascetic_discipline": 0.10
      }
    },
    {
      "op": "SIMULATE_PENDULUM",
      "params": {
        "will_intensity": 0.75,
        "steps": 5
      }
    }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- $0.0 \le W, F, M, \alpha, \beta \le 1.0$
- $1 \le \text{steps} \le 1000$
- 시간 복잡도: 각 평가 $O(1)$, 궤적 $O(\text{steps})$, 전체 $O(N)$ 이내.
