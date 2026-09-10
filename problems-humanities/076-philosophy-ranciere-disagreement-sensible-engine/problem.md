# 자크 랑시에르의 불화(Disagreement)와 감각적인 것의 나눔(Le Partage du sensible) 시뮬레이션 엔진

## 문제 설명

프랑스의 현대 정치철학자이자 미학자인 **자크 랑시에르(Jacques Rancière)**는 저작 *《불화: 정치와 철학(La Mésentente: Politique et philosophie, 1995)》*과 *《감각적인 것의 나눔(Le Partage du sensible, 2000)》*을 통해 서구 정치철학의 근원적 전제를 전복시켰습니다.

랑시에르는 사회 질서를 유지하고 관리하는 행위를 **'치안(La Police / Police)'**이라 부르고, 이에 맞서 평등을 실증하는 예외적 사건만을 진정한 **'정치(La Politique / Politics)'**로 엄격히 구별합니다:

1. **치안(Police)**:
   - 국가 행정, 법률, 선거 제도, 치안 유지 등 사회의 몫(Parts)과 역할을 사전에 분배하고 고정하는 감각적 구획 체제.
   - 치안의 본질은 "각자의 자리로 돌아가라(Move along, there is nothing to see here)", "누가 말할 자격이 있고, 누구의 목소리는 단순한 동물적 소음(Noise / Phōnē)인가"를 결정하는 것입니다.
2. **몫 없는 자들의 몫(The Part of Those Who Have No Part / La part des sans-part)**:
   - 치안의 계산 장부에서 배제된 계층(고대 로마의 플레브스, 근대의 프롤레타리아, 현대의 비정규직 노동자, 서류 없는 이주민 등).
   - 이들의 목소리는 공론장에서 이해 가능한 언어(Logos / Speech)로 간주되지 못하고 고통의 비명이나 불평(Noise)으로 치부됩니다.
3. **불화(Disagreement / La Mésentente)**:
   - 단순한 이해관계의 충돌이나 말다툼이 아닙니다.
   - 한쪽은 상대방을 "말을 할 수 있는 동등한 존재"로 인정하지 않고, "상대방의 말이 언어인가 소음인가", "상대방이 공론장에 존재할 권리가 있는가"라는 **말하는 주체 자체의 가시성과 자격에 대한 근원적 충돌**입니다.
4. **정치적 주체화(Subjectivation)와 평등의 실증(Verification of Equality)**:
   - 몫 없는 자들이 치안이 부여한 자리를 박탈하고 광장으로 나와 "우리의 소음은 언어(Logos)이며 우리는 당신들과 본래적으로 동등하다"고 선언하는 행위.
   - 이로 인해 기존의 감각적 분배가 파열되며 진정한 민주주의적 불일치(**이견 / Dissensus**)가 폭발합니다.

본 문제에서는 랑시에르의 감각적 분배와 불화 모델을 수학적으로 정식화하여, 사회 주체들의 역량($Capacity$)과 치안이 공인한 몫($AssignedPart$), 가시성($Visibility$), 언어 인정 비율($SpeechRatio$), 불화 지수($DisagreementIndex$) 및 공론장 체제 전이($Regime$)를 정밀하게 시뮬레이션하는 엔진을 구현합니다.

---

## 철학적 아키텍처 및 수학적 공식

```
                     [ 치안 질서 (Police Order) ]
              "각자의 자리에 머물라" / 감각적인 것의 나눔
                                │
               ┌────────────────┴────────────────┐
               │                                 │
     [ 공인된 시민/엘리트 ]            [ 몫 없는 자들 (Sans-Part) ]
     - AssignedPart >= 0.50            - AssignedPart < 0.25
     - Speech: Logos (언어로 인정)       - Speech: Noise (소음으로 폄하)
     - High Visibility/Audibility      - Invisibility & Silence
               │                                 │
               │         불화 (La Mésentente)     │
               └───────────────┬─────────────────┘
                               │
            평등의 실증 (Verification of Equality)
            소음을 언어로 전환하는 정치적 주체화
                               ▼
               ┌─────────────────────────────────┐
               │    민주적 불화 (Dissensus)      │
               │    기존 감각적 나눔의 재구성     │
               └─────────────────────────────────┘
```

### 1. 주체 상태 및 불화 지수 ($DisagreementIndex$)

각 주체 $i$는 본래적 지적·인간적 역량 $Capacity_i \in [0, 1]$과 치안 체제가 공인한 몫 $AssignedPart_i \in [0, 1]$를 가집니다:
- **몫 없는 자 판별**: $AssignedPart_i < 0.25$ 이면 `is_sans_part = True` 입니다.
- **치안 압력에 의한 침식**:
  - 만약 주체가 몫 없는 자이고 치안 포화도 $PoliceSaturation > 0.30$ 이면:
    $$	ext{suppression} = (PoliceSaturation - 0.30) 	imes 0.4$$
    $$SpeechRatio_i \leftarrow \max(0.0, \min(1.0, SpeechRatio_i - 	ext{suppression} 	imes 0.5))$$
    $$Visibility_i \leftarrow \max(0.0, \min(1.0, Visibility_i - 	ext{suppression} 	imes 0.4))$$
    $$Audibility_i \leftarrow \max(0.0, \min(1.0, Audibility_i - 	ext{suppression} 	imes 0.4))$$
- **발화 성격 판정**:
  - $SpeechRatio_i \ge 0.50$: `is_speech = True`, `is_noise = False` (로고스/언어)
  - $SpeechRatio_i < 0.50$: `is_speech = False`, `is_noise = True` (단순한 비명/소음)
- **개별 불화 지수 ($\mathcal{D}_i$)**:
  - 본래적 역량과 공인된 몫 사이의 불일치($Gap_i = \max(0.0, Capacity_i - AssignedPart_i)$)에 발화 및 감각적 배제도를 곱하여 산출합니다:
    $$\mathcal{D}_i = 	ext{round}\Big(	ext{clamp}ig(Gap_i 	imes (1.0 - SpeechRatio_i 	imes 0.6) 	imes (1.0 - Visibility_i 	imes Audibility_i 	imes 0.5), 0.0, 1.0ig), 4\Big)$$
- **사회 평균 불화 지수 ($\overline{\mathcal{D}}$)**:
  $$\overline{\mathcal{D}} = 	ext{round}\left(rac{1}{N}\sum_{i=1}^N \mathcal{D}_i, 4ight)$$

### 2. 이견 수위 ($DissensusLevel$) 및 공론장 체제 ($Regime$)

몫 없는 자들 중 자신의 발화를 언어($is\_speech = True$)로 입증한 주체들이 존재할 때, 민주주의적 불화(이견)가 발생합니다:
$$	ext{speech\_power} = rac{1}{|S_{sans}|} \sum_{i \in S_{sans}} (SpeechRatio_i 	imes Visibility_i)$$
$$	ext{DissensusLevel} = 	ext{round}\Big(\minig(1.0, 	ext{speech\_power} 	imes (1.0 - PoliceSaturation 	imes 0.4)ig), 4\Big)$$
(단, 언어로 입증한 몫 없는 자가 없으면 $	ext{DissensusLevel} = 0.0$)

공론장 지배 체제($Regime$)는 다음과 같이 전이됩니다:
- $	ext{DissensusLevel} \ge 0.40$: `"DEMOCRATIC_DISSENSUS"` (민주적 불화: 몫 없는 자들의 평등 실증)
- $PoliceSaturation \ge 0.70$ 이고 $	ext{DissensusLevel} < 0.15$: `"CONSENSUS_POST_POLITICS"` (합의적 탈정치: 치안에 의해 모든 불일치가 관리로 흡수된 상태)
- 그 외의 경우: `"OLIGARCHIC_POLICE_ORDER"` (과두제적 치안 질서)

### 3. 명령 명세 (Commands)

1. `POLICE_ENFORCEMENT` (`intensity`):
   - 치안 포화도를 강화하여 감각적 배제를 심화합니다:
     $$PoliceSaturation \leftarrow \min(1.0, PoliceSaturation + intensity)$$
2. `VERIFY_EQUALITY` (`subject_id`, `effort`):
   - 몫 없는 자가 주체화(Subjectivation)를 단행하여 자신의 소음을 언어로 전환하고 공론장에 가시화합니다:
     $$SpeechRatio_i \leftarrow \min(1.0, SpeechRatio_i + effort 	imes 0.8)$$
     $$Visibility_i \leftarrow \min(1.0, Visibility_i + effort 	imes 0.6)$$
     $$Audibility_i \leftarrow \min(1.0, Audibility_i + effort 	imes 0.7)$$
     $$PoliceSaturation \leftarrow \max(0.0, PoliceSaturation - effort 	imes 0.25)$$
3. `REPARTITION_SHARES` (`subject_id`, `share_delta`):
   - 치안 질서 내부의 타협이나 제도 개혁을 통해 공인된 지분을 변경합니다:
     $$AssignedPart_i \leftarrow \min(1.0, \max(0.0, AssignedPart_i + share\_delta))$$
4. `STEP`:
   - 스텝 카운터를 1 증가시키고 상태를 갱신합니다.
5. `QUERY_DISAGREEMENT`:
   - 현재 시점의 스냅샷(`step`, `police_saturation`, `avg_disagreement`, `dissensus_level`, `regime`, `subjects`)을 `query_logs`에 기록합니다. (주체 딕셔너리는 `subject_id` 오름차순 정렬)

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "police_saturation": 0.40,
    "subjects": [
      {
        "subject_id": "senator",
        "name": "Menenius Agrippa",
        "category": "elite",
        "capacity": 0.80,
        "assigned_part": 0.75
      },
      {
        "subject_id": "plebeian_spokesperson",
        "name": "Tribune of the Plebs",
        "category": "sans_part",
        "capacity": 1.0,
        "assigned_part": 0.05
      }
    ]
  },
  "commands": [
    {"type": "VERIFY_EQUALITY", "subject_id": "plebeian_spokesperson", "effort": 0.80},
    {"type": "QUERY_DISAGREEMENT"},
    {"type": "STEP"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 한 줄로 출력합니다:
```json
{"total_steps":1,"police_saturation":0.2,"avg_disagreement":0.2188,"dissensus_level":0.5847,"regime":"DEMOCRATIC_DISSENSUS","subjects":{"plebeian_spokesperson":{"subject_id":"plebeian_spokesperson","name":"Tribune of the Plebs","category":"sans_part","capacity":1.0,"assigned_part":0.05,"visibility":0.63,"audibility":0.71,"speech_ratio":0.74,"is_sans_part":true,"is_speech":true,"is_noise":false,"disagreement_index":0.4137},"senator":{"subject_id":"senator","name":"Menenius Agrippa","category":"elite","capacity":0.8,"assigned_part":0.75,"visibility":0.8,"audibility":0.8,"speech_ratio":0.9,"is_sans_part":false,"is_speech":true,"is_noise":false,"disagreement_index":0.0238}},"query_logs":[{"step":0,"police_saturation":0.2,"avg_disagreement":0.2188,"dissensus_level":0.5847,"regime":"DEMOCRATIC_DISSENSUS","subjects":{"plebeian_spokesperson":{"subject_id":"plebeian_spokesperson","name":"Tribune of the Plebs","category":"sans_part","capacity":1.0,"assigned_part":0.05,"visibility":0.63,"audibility":0.71,"speech_ratio":0.74,"is_sans_part":true,"is_speech":true,"is_noise":false,"disagreement_index":0.4137},"senator":{"subject_id":"senator","name":"Menenius Agrippa","category":"elite","capacity":0.8,"assigned_part":0.75,"visibility":0.8,"audibility":0.8,"speech_ratio":0.9,"is_sans_part":false,"is_speech":true,"is_noise":false,"disagreement_index":0.0238}}}]}
```
