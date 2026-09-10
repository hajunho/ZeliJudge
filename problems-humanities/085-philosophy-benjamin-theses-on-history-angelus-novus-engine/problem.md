# 발터 벤야민의 『역사의 개념에 대하여』: 역사의 천사(Angelus Novus), 진보주의 비판 및 지금시간(Jetztzeit) 성좌 엔진

## 문제 설명

20세기 가장 심원하고 독창적인 사상가 중 한 명인 **발터 벤야민(Walter Benjamin, 1892–1940)**은 나치즘의 폭압을 피해 망명길에 올랐던 1940년 초, 그의 사상적 유언이자 20세기 비판철학의 정점이라 불리는 에세이 **『역사의 개념에 대하여』(Über den Begriff der Geschichte / Theses on the Philosophy of History)**를 남겼습니다.

벤야민은 서구 근대를 지배해 온 **부르주아적·사회민주주의적 진보주의(Historicism / Historicism)**를 단호히 거부합니다. 역사주의는 시간을 '균질하고 공허한 시간(homogeneous, empty time)'의 선형적 인과 연쇄로 파악하며, 역사를 언제나 승리자들의 행렬(triumphal procession)로 기념합니다. 이 관점에서 패배자들의 희생은 더 높은 문명으로 나아가기 위한 불가피한 비용으로 사상(捨象)됩니다.

그러나 벤야민은 **파울 클레(Paul Klee)**의 수채화 **〈새로운 천사(Angelus Novus)〉**를 통해 역사의 참된 모습을 폭로합니다 (제9테제):

```
                       [ 파라다이스 (Paradise) ]
                                  │
                                  ▼ 폭풍 (Storm of Progress)
                       ┌───────────────────────┐
                       │    역사의 천사        │
                       │   (Angelus Novus)     │
                       │  눈은 크게 뜨고,      │
                       │  입은 벌린 채,        │
                       │  날개는 펼쳐져 있음   │
                       └──────────┬────────────┘
                                  │  시선은 과거(과거의 잔해)를 향함
                                  │  날개는 미래로 밀려남
                                  ▼
           ══════════════════════════════════════════════
           과거의 잔해 더미 (Piles of Ruins / Catastrophe)
           - 부서진 삶들, 학살된 민중, 패배한 봉기
           - "단 하나의 거대한 파국(One Single Catastrophe)"
           ══════════════════════════════════════════════
                                  │
                                  ▼ [지금시간 (Jetztzeit)]
                       ⚡ 번개처럼 번뜩이는 과거의 상
                       (Flashes up in a moment of danger)
                       역사의 연속체를 폭파 (Blast open the continuum)
```

> "클레의 그림 〈새로운 천사〉에는 한 천사가 묘사되어 있다. 그는 마치 자신이 골똘히 응시하고 있는 어떤 것으로부터 막 멀어지려는 것처럼 보인다. 그의 눈은 크게 뜨여 있고, 입은 벌어져 있으며, 날개는 펼쳐져 있다. 역사의 천사도 필시 이렇게 생겼을 것이다. 그는 자신의 얼굴을 과거로 돌리고 있다. 우리 눈에 일련의 사건들의 연쇄가 나타나는 곳에서, 그는 단 하나의 파국만을 본다. 그 파국은 쉼 없이 잔해 위에 또 잔해를 쌓아 올리며 그것들을 그의 발 앞에 내던진다. 천사는 머물러 죽은 자들을 깨우고 산산이 부서진 것들을 맞추어 모으고 싶어한다. 그러나 낙원으로부터 폭풍이 불어와 그의 날개에 걸리고, 그 힘이 너무나 강력하여 천사는 더 이상 날개를 접을 수 없다. 이 폭풍은 그가 등을 돌리고 있는 미래를 향해 그를 거침없이 밀어붙이며, 그의 앞에는 잔해 더미가 하늘 높이 치솟는다. **우리가 진보라고 부르는 것, 그것이 바로 이 폭풍이다.**" (제9테제)

또한 벤야민은 제7테제에서 단언합니다:
> **"동시에 야만의 문서(Dokument der Barbarei)가 아닌 문명의 문서(Dokument der Kultur)란 결코 존재하지 않는다."**

따라서 역사적 유물론자의 사명은 승리자의 발자취를 추종하는 것이 아니라, **"역사의 결을 거슬러 빗질하는 것(die Geschichte gegen den Strich zu bürsten)"**입니다. 그리고 현재의 위기(moment of danger) 속에서 억압된 과거의 고통과 번개처럼 성좌(constellation)를 이루어 공허한 시간의 연속체를 폭파하는 **지금시간(Jetztzeit)**을 포착하고, 과거 세대로부터 위임받은 **약한 메시아적 힘(weak messianic power)**으로 역사를 구원하는 것입니다.

본 문제에서는 발터 벤야민의 역사철학 테제를 시스템화한 **벤야민 역사의 천사 및 지금시간 성좌 분석 엔진(Benjamin Angelus Novus & Jetztzeit Constellation Engine)**을 구축합니다.

---

## 입력 형식

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "historical_events": [
    {
      "id": "EVT_001",
      "epoch": 82,
      "description": "Arch of Titus constructed in Rome commemorating sack of Jerusalem and enslavement of captives",
      "narrative_type": "triumphal",
      "ruins_weight": 20.0,
      "cultural_document": "Arch of Titus",
      "barbarism_index": 0.85,
      "tags": ["monument", "triumph", "slavery", "imperial"]
    }
  ],
  "constellation_queries": [
    {
      "query_id": "Q_01",
      "present_crisis": "Authoritarian surveillance legislation sparks mass disobedience",
      "keywords": ["monument", "imperial"],
      "threshold_danger": 10.0
    }
  ],
  "engine_params": {
    "storm_of_progress_force": 1.5,
    "weak_messianic_power": 1.0
  }
}
```

### 필드 상세 설명
1. `historical_events` (배열): 기록된 역사적 사건 목록
   - `id` (문자열): 사건 고유 식별자
   - `epoch` (정수): 시대/연도 (연대순 좌표)
   - `description` (문자열): 사건에 대한 설명
   - `narrative_type` (문자열): 지배권력 승리 서사(`"triumphal"`) 또는 패배/억압된 자의 서사(`"subjugated"`)
   - `ruins_weight` (실수): 잔해와 파국의 원초적 무게 ($W_{base} \ge 0.0$)
   - `cultural_document` (문자열): 문명의 기념비/문화재 명칭 (없으면 빈 문자열 `""`)
   - `barbarism_index` (실수): 해당 기념비에 내재된 야만성 지수 ($0.0 \le b \le 1.0$)
   - `tags` (문자열 배열): 사건 분류 태그 (대소문자 무관)
2. `constellation_queries` (배열): 현재 시점의 위기에서 과거와의 성좌 형성을 요청하는 질의 목록
   - `query_id` (문자열): 질의 고유 식별자
   - `present_crisis` (문자열): 현재 직면한 정치·사회·실존적 위기 상황
   - `keywords` (문자열 배열): 현재 위기와 공명할 수 있는 과거 핵심 키워드 목록
   - `threshold_danger` (실수): 지금시간의 불꽃을 점화하기 위한 최소 위험 지수 임계값
3. `engine_params` (객체):
   - `storm_of_progress_force` (실수): 낙원으로부터 불어오는 진보의 폭풍 세기 계수
   - `weak_messianic_power` (실수): 과거가 현재에 건네준 약한 메시아적 힘의 승수

---

## 엔진 처리 규칙 및 연산 공식

### 1. 사건별 파국 및 야만성 변환 (Catastrophe & Barbarism Metrics)
모든 사건 $e$에 대해 다음 값을 계산합니다:
- **야만성 페널티 (Barbarism Penalty)**:
  $$B_{pen} = \text{round}(e[\text{barbarism\_index}] \times 10.0, 4)$$
- **피억압 보너스 (Subjugation Bonus)**:
  $e[\text{narrative\_type}] == \text{"subjugated"}$이면 $5.0$, 아니면 $0.0$.
- **유효 잔해량 (Effective Ruins)**:
  $$\text{effective\_ruins} = \text{round}(e[\text{ruins\_weight}] + B_{pen} + \text{subjugation\_bonus}, 4)$$
- **억압된 반향 (Suppressed Resonance)**:
  $e[\text{narrative\_type}] == \text{"subjugated"}$이면:
  $$\text{suppressed\_resonance} = \text{round}(e[\text{ruins\_weight}] \times (1.0 + e[\text{barbarism\_index}]), 4)$$
  그렇지 않으면 $0.0$.
- **위험 지수 (Danger Index)**:
  $$\text{danger\_index} = \text{round}(\text{effective\_ruins} \times (1.0 + e[\text{barbarism\_index}]), 4)$$

### 2. 역사의 천사의 시선 (Angelus Novus Gaze)
- **원초적 잔해 총합**: $\text{total\_raw\_ruins} = \text{round}(\sum e[\text{ruins\_weight}], 4)$
- **유효 잔해 총합**: $\text{total\_effective\_wreckage} = \text{round}(\sum \text{effective\_ruins}, 4)$
- **진보의 폭풍 변위 (Storm Displacement)**:
  $$\text{storm\_displacement} = \text{round}(\text{total\_effective\_wreckage} \times \text{storm\_of\_progress\_force}, 4)$$
- **천사의 자세 (Angel Posture)**:
  - $\text{storm\_displacement} \ge 100.0$ 이면: `"WINGS_IRRESISTIBLY_BLOWN_FORWARD"` (폭풍에 날개가 꺾여 미래로 거침없이 밀려남)
  - 그렇지 않으면: `"GAZING_FIXEDLY_AT_RUINS"` (과거의 잔해 더미를 응시함)
- **역사주의 진보 환상 비율 (Progress Illusion Ratio)**:
  - $\text{triumphal\_count}$ / 전체 사건 수 (전체 사건 수가 0이면 0.0), 소수점 4자리 반올림.

### 3. 역사의 결을 거슬러 빗질하기 (Brushing History Against the Grain)
- 사건 목록을 연대 역순으로 정렬합니다: `epoch` 내림차순, 동일할 경우 `id` 오름차순.
- **폭로된 문명의 기념비 (Unmasked Monuments)**:
  - `cultural_document`가 빈 문자열이 아니고 `barbarism_index >= 0.50`인 사건들을 역순 순회 순서대로 추출합니다.
  - 각 항목은 `{"event_id": e["id"], "monument": e["cultural_document"], "barbarism_index": e["barbarism_index"], "unmasked_verdict": "BARBARISM_DOCUMENTED"}` 형태로 기록합니다.
  - `unmasked_monuments_count`에 그 개수를 저장합니다.
- **패배한 자들의 목소리 보관소 (Vanquished Voices Archive)**:
  - 역순 순회 순서에서 `narrative_type == "subjugated"`인 사건들의 `id` 목록을 `vanquished_voices_ids`에 보관합니다.
  - `vanquished_voices_count`에 그 개수를 기록합니다.
  - `total_suppressed_resonance` = $\text{round}(\sum \text{suppressed\_resonance}, 4)$

### 4. 지금시간의 성좌 및 연속체 폭파 (Jetztzeit Constellations)
각 `constellation_queries`의 질의 $q$에 대해:
- 질의의 `keywords` 중 하나라도 사건의 `tags`(대소문자 무관)에 포함되어 있거나, `description`(대소문자 무관 소문자 변환)에 부분 문자열로 포함되어 있고,
- 해당 사건의 $\text{danger\_index} \ge q[\text{threshold\_danger}]$ 인 사건들을 후보군으로 선별합니다.
- 일치하는 후보가 있는 경우:
  - 우선순위: `danger_index` 내림차순 $\to$ `epoch` 내림차순 $\to$ `id` 오름차순으로 정렬하여 첫 번째 최적 사건(최고 위험 앵커)을 선택합니다.
  - **폭파 에너지 (Blast Energy)**:
    $$\text{blast\_energy} = \text{round}(\text{anchor}[\text{danger\_index}] \times \text{weak\_messianic\_power}, 4)$$
  - **연속체 폭파 여부**:
    $\text{blast\_energy} \ge 15.0$ 이면 $\text{continuum\_blasted} = \text{true}$, 아니면 $\text{false}$.
  - 결과 객체:
    ```json
    {
      "query_id": q["query_id"],
      "spark_found": true,
      "anchor_event_id": anchor["id"],
      "danger_index": anchor["danger_index"],
      "blast_energy": blast_energy,
      "continuum_blasted": continuum_blasted,
      "dialectical_image": "Past crisis '<anchor_id>' flashes up into present moment '<query_id>'"
    }
    ```
- 일치하는 후보가 없는 경우:
  ```json
  {
    "query_id": q["query_id"],
    "spark_found": false,
    "anchor_event_id": null,
    "danger_index": 0.0,
    "blast_energy": 0.0,
    "continuum_blasted": false,
    "dialectical_image": "No dialectical constellation formed; crisis absorbed into empty homogeneous time"
  }
  ```

### 5. 역사적 유물론 최종 판정 (Historical Materialism Verdict)
- `total_blast_energy` = 모든 질의의 `blast_energy` 합계 (소수점 4자리 반올림)
- **메시아적 구원 총합 지수 (Total Redemption Index)**:
  $$\text{total\_redemption\_index} = \text{round}(\text{total\_blast\_energy} + (\text{total\_suppressed\_resonance} \times \text{weak\_messianic\_power}), 4)$$
- **역사적 판정 (verdict)**:
  - 질의 중 하나라도 `continuum_blasted == true`인 경우: `"MESSIANIC_RUPTURE_OF_CONTINUUM"`
  - 그렇지 않고 `total_suppressed_resonance > 0.0`인 경우: `"LATENT_REVOLUTIONARY_TENSION"`
  - 둘 다 아닌 경우: `"HOMOGENEOUS_EMPTY_PROGRESSION"`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마를 갖는 단일 JSON 객체를 압축 공백 없이 출력합니다 (`json.dumps(..., separators=(',', ':'))`).

```json
{
  "angelus_novus_gaze": {
    "total_raw_ruins": 20.0,
    "total_effective_wreckage": 28.5,
    "storm_displacement": 42.75,
    "angel_posture": "GAZING_FIXEDLY_AT_RUINS",
    "progress_illusion_ratio": 1.0
  },
  "brushing_against_the_grain": {
    "unmasked_monuments_count": 1,
    "unmasked_monuments": [
      {
        "event_id": "EVT_ROME_ARCH",
        "monument": "Arch of Titus",
        "barbarism_index": 0.85,
        "unmasked_verdict": "BARBARISM_DOCUMENTED"
      }
    ],
    "vanquished_voices_count": 0,
    "vanquished_voices_ids": [],
    "total_suppressed_resonance": 0.0
  },
  "jetztzeit_constellations": [
    {
      "query_id": "Q_01",
      "spark_found": true,
      "anchor_event_id": "EVT_ROME_ARCH",
      "danger_index": 52.725,
      "blast_energy": 52.725,
      "continuum_blasted": true,
      "dialectical_image": "Past crisis 'EVT_ROME_ARCH' flashes up into present moment 'Q_01'"
    }
  ],
  "historical_materialism_verdict": {
    "total_blast_energy": 52.725,
    "total_redemption_index": 52.725,
    "verdict": "MESSIANIC_RUPTURE_OF_CONTINUUM"
  }
}
```

---

## 제약 사항

- $1 \le |\text{historical\_events}| \le 50$
- $1 \le |\text{constellation\_queries}| \le 20$
- $0 \le \text{epoch} \le 2100$
- $0.0 \le \text{ruins\_weight} \le 500.0$
- $0.0 \le \text{barbarism\_index} \le 1.0$
- $0.1 \le \text{storm\_of\_progress\_force} \le 10.0$
- $0.1 \le \text{weak\_messianic\_power} \le 5.0$
- 시간 복잡도: 사건 수 $N$과 질의 수 $Q$에 대해 $O(N \log N + Q \cdot N)$ 이내에 완료되어야 합니다.
- 공간 복잡도: $O(N + Q)$ 이내.
