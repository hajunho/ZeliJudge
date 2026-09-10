# 에드워드 사이드의 오리엔탈리즘 담론적 타자화 및 텍스트적 표상 권력 엔진 (Edward Said Orientalism & Discursive Othering Engine)

## 문제 설명

비평이론 및 포스트식민주의(Postcolonialism)의 창시작인 에드워드 사이드(Edward W. Said)의 저작 『오리엔탈리즘(Orientalism, 1978)』은 서양(Occident)이 동양(Orient)을 단순한 지리적 이웃이 아니라, **"지배하고 재구성하며 권위를 행사하기 위한 담론적 구성물(Discursive Construct)"**로 발명해 낸 역사적 과정을 폭로합니다.

사이드에 따르면 오리엔탈리즘은 중립적인 학문적 호기심이 아니라, 미셸 푸코(Michel Foucault)의 권력-지식(Power-Knowledge) 연계망 속에서 작동하는 거대한 텍스트적 제도(Institutional Textual Apparatus)입니다.

```
+---------------------------------------------------------------------------------+
|                  에드워드 사이드의 오리엔탈리즘 담론 생산 아키텍처              |
+---------------------------------------------------------------------------------+
|  [ 서구 주체: Occident ]                                                         |
|  - 전략적 위치짓기(Strategic Location): 동양을 내려다보는 관찰자·지배자 시선     |
|  - 텍스트적 태도(Textual Attitude): 현실 경험 대신 정전 텍스트(Canon) 인용 의존   |
+---------------------------------------------------------------------------------+
                                         |
                                         | [ 담론적 투사: 4대 이항 대립 축 ]
                                         v
   +--------------------+---------------------+--------------------+--------------------+
   |   1. 이성(Reason)  |   2. 시간성(Time)   |   3. 주체성(Agency)|  4. 통치(Politics) |
   +--------------------+---------------------+--------------------+--------------------+
   | 서양: Rational     | 서양: Progressive   | 서양: Autonomous   | 서양: Democratic   |
   | 동양: Mystical     | 동양: Static        | 동양: Passive      | 동양: Despotic     |
   +--------------------+---------------------+--------------------+--------------------+
                                         |
                                         v
               +---------------------------------------------------+
               |  명시적 오리엔탈리즘 (Manifest Orientalism)       |
               |  - 여행기, 학술 논문, 제국주의 시정 방침 문헌     |
               |  - 타자화 지수(Othering Score >= 0.35) 산출       |
               +---------------------------------------------------+
                                         |
                                         | 누적 피드백 (축적)
                                         v
               +---------------------------------------------------+
               |  잠재적 오리엔탈리즘 (Latent Orientalism)         |
               |  - 서구 무의식에 각인된 불변의 본질주의(Essence)  |
               |  - 위치적 우월성: HEGEMONIC_DOMINANCE 판정        |
               +---------------------------------------------------+
                                         ^
                                         | [ 탈식민주의적 해체 ]
               +---------------------------------------------------+
               |  대항 담론 (Counter-Hegemonic Discourse)          |
               |  - 동양 주체의 자기 서사 및 실증적 현실 관찰      |
               |  - 잠재적 편향 감소 & DECONSTRUCTED_EGALITARIAN   |
               +---------------------------------------------------+
```

### 1. 4대 이항 대립 축 (Binary Oppositions)
오리엔탈리즘은 동양을 서양의 부정적 반사상(Negative Mirror)으로 규정하는 4대 축으로 조직됩니다:
1. **이성/합리성(Rationality)**:
   - 서양: `rational`, `scientific`, `logical`
   - 동양: `mystical`, `sensual`, `irrational`
2. **시간성/역사성(Temporality)**:
   - 서양: `progressive`, `dynamic`, `modern`
   - 동양: `static`, `ahistorical`, `timeless`
3. **주체성/행위능력(Agency)**:
   - 서양: `agentic`, `active`, `autonomous`
   - 동양: `passive`, `submissive`, `fatalistic`
4. **통치/도덕성(Governance)**:
   - 서양: `democratic`, `lawful`, `civilized`
   - 동양: `despotic`, `fanatical`, `barbaric`

### 2. 텍스트적 태도(Textual Attitude)와 타자화 지수(Othering Score)
1. **텍스트적 태도 (Textual Attitude Index)**:
   현장의 실증적 관찰 사실(`empirical_facts`)보다 과거 정전(Dante, Renan, Lane, Balfour 등)의 권위에 의존하는 비율입니다:
   $$	ext{canon\_count} = \sum [r \in 	ext{canonical\_texts}]$$
   $$	ext{textual\_attitude} = rac{	ext{canon\_count}}{	ext{empirical\_facts} + 	ext{canon\_count}} \quad (	ext{분모 0이면 0.0})$$
2. **타자화 지수 (Othering Score)**:
   서구 화자가 동양 대상을 묘사할 때:
   $$	ext{axis\_diversity} = rac{	ext{고유 활성 대립축 수}}{4.0}$$
   $$	ext{raw} = (	ext{orient\_attr} 	imes 0.35) + (	ext{textual\_attitude} 	imes 0.35) + (	ext{latent\_bias} 	imes 0.2) + (	ext{axis\_diversity} 	imes 0.1)$$
   $$	ext{othering\_score} = 	ext{round}(\min(1.0, \max(0.0, 	ext{raw})), 4)$$
   - `othering_score >= 0.35`인 경우: `MANIFEST_ORIENTALISM`으로 분류되며, 잠재적 편향이 누적됩니다:
     $$	ext{latent\_bias} \leftarrow \min(1.0, 	ext{latent\_bias} + 	ext{round}(	ext{othering\_score} 	imes 0.15, 4))$$
   - 미만인 경우: `NEUTRAL`로 분류됩니다.
3. **대항 담론 (Counter-Hegemonic Discourse)**:
   동양 화자가 발화하거나(`speaker_origin == "Orient"`) 명시적 대항 담론(`is_counter_discourse == true`)인 경우:
   - 담론 유형은 `COUNTER_HEGEMONIC`으로 분류됩니다.
   - 현장 실증 사실에 비례하여 잠재적 편향을 해체합니다:
     $$\Delta 	ext{bias} = 	ext{round}(0.12 + (	ext{empirical\_facts} 	imes 0.04), 4)$$
     $$	ext{latent\_bias} \leftarrow \max(0.0, 	ext{latent\_bias} - \Delta 	ext{bias})$$

### 3. 담론 종합 평가 (Positional Superiority)
최종 축적된 `latent_bias`에 따라 서구 담론의 위치적 우월성을 진단합니다:
- `latent_bias >= 0.70`: `HEGEMONIC_DOMINANCE` (절대적 식민 지배 담론)
- `0.40 <= latent_bias < 0.70`: `PATERNALISTIC_SURVEILLANCE` (온정주의적 감시 및 후견 담론)
- `latent_bias < 0.40`: `DECONSTRUCTED_EGALITARIAN` (해체주의적 평등 담론)

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "canonical_texts": ["Renan", "Lane", "Balfour"],
    "initial_latent_bias": 0.1
  },
  "operations": [
    {
      "op": "ANALYZE_STATEMENT",
      "statement": {
        "statement_id": 101,
        "speaker_origin": "Occident",
        "subject_target": "Orient",
        "attributes": ["sensual", "mystical", "static"],
        "references": ["Renan", "Lane"],
        "empirical_facts": 0
      }
    }
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "evaluation": {
    "total_statements": 1,
    "manifest_orientalist_count": 1,
    "counter_hegemonic_count": 0,
    "neutral_count": 0,
    "average_textual_attitude": 1.0,
    "final_latent_bias": 0.2395,
    "max_othering_score": 0.93,
    "positional_superiority": "DECONSTRUCTED_EGALITARIAN"
  },
  "statements": [
    {
      "statement_id": 101,
      "speaker_origin": "Occident",
      "subject_target": "Orient",
      "discourse_type": "MANIFEST_ORIENTALISM",
      "textual_attitude": 1.0,
      "othering_score": 0.93,
      "latent_bias_after": 0.2395
    }
  ],
  "event_log": [...]
}
```
