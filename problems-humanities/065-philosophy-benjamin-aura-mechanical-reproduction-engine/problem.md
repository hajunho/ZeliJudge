# 발터 벤야민 기술복제시대의 예술: 아우라(Aura) 붕괴, 제의가치 대 전시가치 전이 및 광학적 무의식 엔진 (Walter Benjamin Aura & Mechanical Reproduction Engine)

## 문제 설명

20세기 최고의 비판 철학자이자 미디어 미학자인 **발터 벤야민(Walter Benjamin, 1892~1940)**은 1935~1936년에 발표한 기념비적 에세이 **『기술복제시대의 예술작품』(Das Kunstwerk im Zeitalter seiner technischen Reproduzierbarkeit)**을 통해 사진과 영화라는 대량 복제 기술이 인류의 지각 방식과 예술의 존재론을 어떻게 근본적으로 재편했는지를 탐구했습니다.

전통적인 고전 예술작품은 시간과 공간에 유일무이하게 닻을 내린 **지금-여기(Hier und Jetzt / Hic et Nunc)**의 진품성(Authenticity)과 역사적 증언력을 지니고 있었습니다. 벤야민은 이를 **아우라(Aura)**라고 부르며, *"아무리 가까이 있더라도 어떤 먼 것의 일회적 나타남(Einmalige Erscheinung einer Ferne, so nah sie sein mag)"*으로 정의했습니다.

그러나 인쇄술, 사진, 그리고 활동사진(영화)의 등장은 원본을 그 고유한 전통과 물리적 장소의 맥락으로부터 탈취하여, 수만 명의 대중이 손끝에서 소비할 수 있도록 대량 복제합니다:

```
[ 기술복제에 의한 예술의 존재론적 변천도 ]

고전적 제의 예술 (Classical Ritual Art)
- 진품의 시공간적 일회성: Hic et Nunc 보존
- 공간적 거리감 유지 (Distance Factor D 고공)
- 제의가치 (Cult Value) 극대화 / 전시가치 (Exhibition Value) 최소화
- 아우라(Aura) 보존: 제단화, 동굴 벽화, 비너스 신상
                  |
                  v [사진 및 영화 기술복제의 침투 (Reproduction Count N 급증)]
                  |
기술복제시대 대중 예술 (Mechanically Reproduced Art)
- 원본성 상실 및 대량 복제 유통
- 대중적 접근성(Accessibility A) 극대화 -> 아우라의 붕괴 (Decay of Aura)
- 전시가치 (Exhibition Value)의 압도적 우위
- 카메라 렌즈(클로즈업, 슬로모션)를 통한 "광학적 무의식(Optical Unconscious)" 발견!
```

벤야민은 아우라의 소멸을 단순한 상실로 한탄하지 않고, 대중 해방의 가능성으로 통찰했습니다:
1. **제의가치(Cult Value)에서 전시가치(Exhibition Value)로의 전이**: 예술이 소수 성직자나 귀족의 신비주의적 제의 독점에서 벗어나, 대중의 공공적 비판과 향유의 장으로 이동합니다.
2. **광학적 무의식 (The Optical Unconscious, Das optische Unbewusste)**: 인간의 육안으로는 포착할 수 없는 보행 순간의 근육 떨림이나 미세한 시선 변화를 카메라의 클로즈업과 초고속/슬로모션이 폭로함으로써, 프로이트의 정신분석학이 본능의 무의식을 열었듯 영화는 광학적 무의식의 세계를 열어젖힙니다.
3. **정치의 심미화 vs 예술의 정치화**: 파시즘이 대중의 계급 모순을 해결하지 않은 채 대규모 전당대회와 전쟁을 스펙터클로 소비하게 하는 **정치의 심미화(Aestheticization of Politics)**를 꾀할 때, 혁명적 진보 예술은 기술복제를 대중의 비판적 각성과 연대의 무기로 전환하는 **예술의 정치화(Politicization of Art)**로 맞서야 합니다.

본 문제는 예술작품의 메타데이터(시공간적 일회성 보존 여부, 복제 부수, 공간적 거리감, 대중 접근성, 클로즈업/슬로모션 계수, 제의 맥락도, 정치 프로파간다도)를 입력받아 아우라 잔존도, 제의가치 대 전시가치 역학, 광학적 무의식 해금 여부, 그리고 사회적 정치 모드를 정밀 판정하는 발터 벤야민 미학 분석 엔진을 구현하는 것입니다.

```
       [ 벤야민 미학 시뮬레이션 파이프라인 아키텍처 ]

   [ 입력 데이터 ]
   - hic_et_nunc, reproduction_count
   - distance_factor, accessibility
   - close_up_factor, slow_motion_factor
   - ritual_context, spectacle_propaganda
               |
               +-----------------------------------+
               |                                   |
               v                                   v
   [ 1. 아우라(Aura) 산출 ]               [ 2. 가치 전이 역학 분석 ]
   - hic=False -> Aura = 0.0             - Cult Value: V_cult
   - hic=True -> Aura = D * R / (1+0.001N)- Exhibit Value: V_exhibit
   - PRESERVED / FADING / DECAYED         - CULT_DOMINANT / EXHIBITION_DOMINANT
               |                                   |
               +-----------------+-----------------+
                                 |
                                 v
   [ 3. 광학적 무의식 & 정치 모드 판정 ]
   - Optical Unconscious: O = 0.5 * C + 0.5 * S (O >= 0.60 -> UNLOCKED)
   - Political Mode:
     * P >= 0.70 -> AESTHETICIZATION_OF_POLITICS (파시즘 스펙터클)
     * A >= 0.70 & O >= 0.50 -> POLITICIZATION_OF_ART (비판적 대중 예술)
     * Else -> AUTONOMOUS_AESTHETICS (순수 예술)
                                 |
                                 v
   [ 4. 미디어 생태계 시대 진단 (Epoch Diagnosis) ]
   - AGE_OF_MECHANICAL_REPRODUCTION / CLASSICAL_RITUAL / TRANSITIONAL
```

---

## 알고리즘 및 상태 전이 명세

### 1. 아우라 지수 (Aura Index, $\mathcal{A}$)
- 진품의 시공간적 일회성(`hic_et_nunc`)이 `False`인 경우:
  $$\mathcal{A} = 0.0$$
- `hic_et_nunc == True`인 경우:
  $$\mathcal{A} = 	ext{round}\left(D 	imes R 	imes rac{1.0}{1.0 + 0.001 	imes N_{	ext{repro}}}, 4ight)$$
- 아우라 상태 분류:
  - $\mathcal{A} \ge 0.70$: `"AURA_PRESERVED"` (신성한 원본 아우라 보존)
  - $0.30 \le \mathcal{A} < 0.70$: `"AURA_FADING"` (복제와 순환으로 아우라 감쇄 중)
  - $\mathcal{A} < 0.30$: `"AURA_DECAYED"` (아우라의 완전한 붕괴)

### 2. 제의가치($\mathcal{V}_{	ext{cult}}$) 대 전시가치($\mathcal{V}_{	ext{exhibit}}$)
- 제의가치: 종교적 비의성과 거리감에 비례하고 대중 접근성에 반비례합니다.
  $$\mathcal{V}_{	ext{cult}} = 	ext{round}\left(R 	imes rac{1.0}{1.0 + 0.0005 	imes N_{	ext{repro}}} 	imes (1.0 - 0.5 	imes A), 4ight)$$
- 전시가치: 대중 접근성과 복제 순환 규모에 비례합니다.
  $$	ext{repro\_factor} = \min\left(1.0, rac{N_{	ext{repro}}}{1000.0}ight)$$
  $$\mathcal{V}_{	ext{exhibit}} = \min\left(1.0, 	ext{round}\left(A 	imes (0.3 + 0.7 	imes 	ext{repro\_factor}), 4ight)ight)$$
- 지배 가치 판정:
  - $\mathcal{V}_{	ext{cult}} > \mathcal{V}_{	ext{exhibit}}$: `"CULT_VALUE_DOMINANT"`
  - $\mathcal{V}_{	ext{cult}} < \mathcal{V}_{	ext{exhibit}}$: `"EXHIBITION_VALUE_DOMINANT"`
  - 그 외: `"TRANSITIONAL_EQUILIBRIUM"`

### 3. 광학적 무의식 (Optical Unconscious, $\mathcal{O}$)
- 렌즈의 클로즈업 확대율($C$)과 시간 분할 슬로모션($S$)의 결합:
  $$\mathcal{O} = 	ext{round}(0.5 \cdot C + 0.5 \cdot S, 4)$$
- $\mathcal{O} \ge 0.60$인 경우: `"OPTICAL_UNCONSCIOUS_UNLOCKED"`
- $\mathcal{O} < 0.60$인 경우: `"CONVENTIONAL_VISION"`

### 4. 정치적 양식 (Political Mode)
- $P \ge 0.70$: `"AESTHETICIZATION_OF_POLITICS"` (정치의 심미화, 파시즘적 대중 최면)
- $A \ge 0.70$ 이고 $\mathcal{O} \ge 0.50$인 경우: `"POLITICIZATION_OF_ART"` (예술의 정치화, 프롤레타리아 비판 지각)
- 그 외: `"AUTONOMOUS_AESTHETICS"` (자율적 순수 예술)

### 5. 사회적 시대 진단 (Epoch Diagnosis)
- $	ext{decayed\_ratio} \ge 0.70$ 이고 $	ext{exhibition\_dominant\_ratio} \ge 0.70$: `"AGE_OF_MECHANICAL_REPRODUCTION"`
- $	ext{preserved\_ratio} \ge 0.70$: `"CLASSICAL_RITUAL_EPOCH"`
- 그 외: `"TRANSITIONAL_MEDIA_ECOLOGY"`

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 전달됩니다:

```json
{
  "config": {},
  "artworks": [
    {
      "id": "a1",
      "name": "샤르트르 대성당 제단 조각상",
      "hic_et_nunc": true,
      "reproduction_count": 0,
      "distance_factor": 0.95,
      "accessibility": 0.05,
      "close_up_factor": 0.0,
      "slow_motion_factor": 0.0,
      "ritual_context": 0.95,
      "spectacle_propaganda": 0.0
    },
    {
      "id": "a2",
      "name": "대량 인쇄된 모나리자 엽서",
      "hic_et_nunc": false,
      "reproduction_count": 50000,
      "distance_factor": 0.10,
      "accessibility": 0.95,
      "close_up_factor": 0.20,
      "slow_motion_factor": 0.0,
      "ritual_context": 0.10,
      "spectacle_propaganda": 0.0
    },
    {
      "id": "a3",
      "name": "지가 베르토프 <카메라를 든 사나이>",
      "hic_et_nunc": false,
      "reproduction_count": 10000,
      "distance_factor": 0.05,
      "accessibility": 0.85,
      "close_up_factor": 0.90,
      "slow_motion_factor": 0.80,
      "ritual_context": 0.0,
      "spectacle_propaganda": 0.10
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 분석 결과를 JSON 포맷으로 출력합니다:

```json
{
  "artwork_evaluations": [
    {
      "id": "a1",
      "name": "샤르트르 대성당 제단 조각상",
      "hic_et_nunc": true,
      "aura_index": 0.9025,
      "aura_status": "AURA_PRESERVED",
      "cult_value": 0.9262,
      "exhibition_value": 0.015,
      "dominant_value": "CULT_VALUE_DOMINANT",
      "optical_unconscious": 0.0,
      "optical_status": "CONVENTIONAL_VISION",
      "political_mode": "AUTONOMOUS_AESTHETICS"
    },
    ...
  ],
  "summary": {
    "total_artworks": 3,
    "aura_distribution": {
      "preserved": 1,
      "fading": 0,
      "decayed": 2
    },
    "value_distribution": {
      "cult_dominant": 1,
      "exhibition_dominant": 2,
      "equilibrium": 0
    },
    "optical_unconscious_unlocked_count": 1,
    "political_mode_counts": {
      "politicization_of_art": 1,
      "aestheticization_of_politics": 0,
      "autonomous_aesthetics": 2
    },
    "epoch_diagnosis": "TRANSITIONAL_MEDIA_ECOLOGY"
  }
}
```
