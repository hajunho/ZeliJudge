# 슬라보예 지젝 이데올로기의 숭고한 대상: 냉소적 이성, 라캉적 3계 및 이데올로기적 환상 엔진 (Slavoj Žižek Sublime Object of Ideology Engine)

## 문제 설명

슬로베니아의 세계적 철학자이자 문화 비평가인 **슬라보예 지젝(Slavoj Žižek, 1949~)**은 1989년 출간된 서구 철학계의 기념비적 데뷔작 **『이데올로기의 숭고한 대상』(The Sublime Object of Ideology)**을 통해, 자크 라캉(Jacques Lacan)의 정신분석학과 헤겔 변증법을 융합하여 후기 자본주의 이데올로기의 작동 방식을 혁명적으로 재정의했습니다.

고전적 마르크스주의에서 이데올로기는 "그들은 자신들이 무엇을 하는지 알지 못하지만, 그럼에도 그것을 행하고 있다(Sie wissen das nicht, aber sie tun es)"는 **허위의식(False Consciousness)**으로 규정되었습니다. 지젝은 페터 슬로터다이크(Peter Sloterdijk)의 『냉소적 이성 비판』을 계승하여, 오늘날 지배적인 이데올로기 양식은 무지가 아니라 오히려 완전한 앎에 기초한 **냉소적 이성(Cynical Reason)**이라고 선언합니다:

> *"그들은 자신들이 무엇을 하는지 아주 잘 알고 있지만, 그럼에도 불구하고 여전히 그것을 행하고 있다!" (They know very well what they are doing, but still, they are doing it!)*

현대인은 자본주의의 착취, 환경 파괴, 상품 물신주의의 기만을 비판적으로 명확히 인지하고 조롱하면서도(냉소적 거리두기), 행동과 실천에 있어서는 체제의 명령에 100% 순응합니다. 이데올로기는 인간의 '머릿속 신념'에 있는 것이 아니라, 인간이 매일 반복하는 **'물질적 실천과 사회적 행동'** 속에 체현되어 있습니다.

```
[ 이데올로기적 주체 의식의 4대 모드 ]

1. 고전적 허위의식 (Classical False Consciousness): K = False, A = True
   "알지 못하기에 행한다." (전통적 교조주의 체제 순응)
2. 지젝의 냉소적 이성 (Cynical Reason): K = True, A = True
   "잘 알고 있으면서도 행한다." (후기 자본주의 지배적 헤게모니)
3. 해방적 저항 (Emancipatory Resistance): K = True, A = False
   "진실을 직시하고 체제 실천을 거부한다." (환상의 횡단)
4. 맹목적 일탈 (Blind Drift): K = False, A = False
   "비판적 앎도 없이 무질서하게 표류한다." (탈사회화된 아노미)
```

지젝은 라캉의 3계(RSI)를 통해 이데올로기가 어떻게 사회의 구조적 모순을 봉합하는지 규명합니다:
1. **상상계 (The Imaginary)**: 나르시시즘적 자아 이상, 미디어 이미지, 시각적 매혹.
2. **상징계 (The Symbolic)**: '대타자(The Big Other)', 법, 언어, 사회적 규범과 질서.
3. **실재계 (The Real)**: 상징화에 저항하는 외상적(Traumatic) 구멍이자 과잉의 영역.

사회는 결코 모순 없는 전체로 완결될 수 없으며, 언제나 구조적인 **근원적 결여(Constitutive Lack)**를 안고 있습니다. 이때 **이데올로기적 환상(Ideological Fantasy)**은 이 외상적 실재의 균열을 가려주는 '스크린' 역할을 합니다.

```
               [ 라캉-지젝 환상 공식과 향유의 도둑질 투사 구조 ]

         상징계 질서 (The Symbolic, S) <---> 상상계적 자아 (The Imaginary, I)
                          \                 /
                           \               /
                            v             v
                    [ 이데올로기적 환상 스크린 ($ <> a) ]
                    (사회의 근원적 결여와 모순을 봉합)
                                  |
                                  | (균열 발생 시)
                                  v
                    [ 외상적 실재계의 분출 (The Real, R) ]
                                  |
               +------------------+------------------+
               |                                     |
               v                                     v
    [ 향유의 도둑질 투사 (Theft of Enjoyment) ]     [ 환상의 횡단 (Traversing the Fantasy) ]
    - 체제의 내적 모순을 외부 타자에게 뒤집어씌움   - 대타자의 무능과 실재의 트라우마를 직시
    - "저 외부인들이 우리의 향유를 훔쳐갔다!"       - 체제 순응을 거부하고 새로운 주체로 거듭남
    - 극우 포퓰리즘, 혐오 정치의 기저 메커니즘      - 지젝이 제시하는 급진적 해방의 윤리
```

본 문제는 사회 주체들의 인지·행동 상태(앎 여부, 순응 실천 여부) 및 라캉적 3계 지표(상상계, 상징계, 실재계 트라우마, 희생양 편향도)를 입력받아, 주체별 이데올로기 모드, 냉소 지수, 환상 스크린 건전도, 향유의 도둑질 지수, 환상의 횡단 여부 및 사회 전체의 헤게모니 양식을 진단하는 슬라보예 지젝 이데올로기 판정 엔진을 구현하는 것입니다.

---

## 알고리즘 및 상태 전이 명세

### 1. 주체별 이데올로기 모드 및 냉소 지수
입력된 주체 $s$의 비판적 앎(`knows_truth`)과 실천 순응(`acts_compliantly`)에 따라 판정:
1. `knows_truth == False` 이고 `acts_compliantly == True`:
   - `ideology_mode = "CLASSICAL_FALSE_CONSCIOUSNESS"`
   - `cynicism_index = 0.0`
2. `knows_truth == True` 이고 `acts_compliantly == True`:
   - `ideology_mode = "CYNICAL_REASON"`
   - `cynicism_index = round(0.5 + 0.5 * (1.0 - symbolic_order), 4)`
3. `knows_truth == True` 이고 `acts_compliantly == False`:
   - `ideology_mode = "EMANCIPATORY_RESISTANCE"`
   - `cynicism_index = 0.0`
4. `knows_truth == False` 이고 `acts_compliantly == False`:
   - `ideology_mode = "BLIND_DRIFT"`
   - `cynicism_index = 0.0`

### 2. 상징계의 근원적 결여 (Constitutive Lack)
대타자(상징계 질서)의 불완전성:
$$	ext{constitutive\_lack} = \max(0.0, 	ext{round}(1.0 - 	ext{symbolic\_order}, 4))$$

### 3. 환상 스크린 건전도 (Fantasy Integrity)
상징계와 상상계의 지지가 실재계의 트라우마에 의해 삭감되는 수준:
$$	ext{raw\_integrity} = (0.6 \cdot 	ext{symbolic\_order} + 0.4 \cdot 	ext{imaginary\_ego}) 	imes (1.0 - 0.8 \cdot 	ext{real\_trauma})$$
$$	ext{fantasy\_integrity} = \max(0.0, \min(1.0, 	ext{round}(	ext{raw\_integrity}, 4)))$$
- 상태 분류:
  - $\ge 0.70$: `"HEGEMONIC_FANTASY_STABLE"` (환상 스크린이 안정적으로 사회를 지탱)
  - $0.35 \le 	ext{integrity} < 0.70$: `"FANTASY_FISSURED"` (환상에 균열이 가기 시작함)
  - $< 0.35$: `"ERUPTION_OF_THE_REAL"` (실재계의 외상적 분출 및 환상 붕괴)

### 4. 향유의 도둑질 투사도 (Theft of Enjoyment)
사회의 내적 모순을 외부 타자(희생양)의 탓으로 돌리는 심리적 기제:
$$	ext{theft} = (0.6 \cdot 	ext{constitutive\_lack} + 0.4 \cdot 	ext{real\_trauma}) 	imes 	ext{scapegoat\_bias}$$
$$	ext{theft\_of\_enjoyment} = \max(0.0, \min(1.0, 	ext{round}(	ext{theft}, 4)))$$

### 5. 환상의 횡단 (Traversing the Fantasy)
지젝적 주체화의 핵심 윤리:
- `knows_truth == True` 이고 `acts_compliantly == False` 이며 `fantasy_integrity < 0.35`인 경우:
  `traversed_fantasy = True`
- 그 외: `False`

### 6. 사회 전체 헤게모니 진단 (Hegemonic Diagnosis)
- `cynical_ratio >= 0.50`: `"CYNICAL_POST_IDEOLOGICAL_HEGEMONY"`
- `mean_theft >= 0.50`: `"POPULIST_OTHERING_SCAPEGOAT_POLARIZATION"`
- `classical_ratio >= 0.50`: `"ORTHODOX_DOCTRINAL_HEGEMONY"`
- `emancipatory_ratio >= 0.40`: `"COUNTER_HEGEMONIC_FERMENT"`
- 그 외: `"FRAGMENTED_IDEOLOGICAL_FIELD"`

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 전달됩니다:

```json
{
  "config": {},
  "subjects": [
    {
      "id": "s1",
      "name": "전통적 관료",
      "knows_truth": false,
      "acts_compliantly": true,
      "imaginary_ego": 0.85,
      "symbolic_order": 0.90,
      "real_trauma": 0.10,
      "scapegoat_bias": 0.05
    },
    {
      "id": "s2",
      "name": "냉소적 로펌 변호사",
      "knows_truth": true,
      "acts_compliantly": true,
      "imaginary_ego": 0.60,
      "symbolic_order": 0.35,
      "real_trauma": 0.25,
      "scapegoat_bias": 0.15
    },
    {
      "id": "s3",
      "name": "외국인 혐오 극우 청년",
      "knows_truth": false,
      "acts_compliantly": true,
      "imaginary_ego": 0.90,
      "symbolic_order": 0.20,
      "real_trauma": 0.75,
      "scapegoat_bias": 0.95
    },
    {
      "id": "s4",
      "name": "환상을 횡단한 비판적 실천가",
      "knows_truth": true,
      "acts_compliantly": false,
      "imaginary_ego": 0.20,
      "symbolic_order": 0.10,
      "real_trauma": 0.85,
      "scapegoat_bias": 0.0
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다:

```json
{
  "subject_evaluations": [
    {
      "id": "s1",
      "name": "전통적 관료",
      "ideology_mode": "CLASSICAL_FALSE_CONSCIOUSNESS",
      "mode_desc": "맑스적 허위의식: '그들은 알지 못하기에 행한다'",
      "cynicism_index": 0.0,
      "constitutive_lack": 0.1,
      "fantasy_integrity": 0.8096,
      "fantasy_status": "HEGEMONIC_FANTASY_STABLE",
      "theft_of_enjoyment": 0.005,
      "traversed_fantasy": false
    },
    ...
  ],
  "collective_ideology": {
    "total_subjects": 4,
    "mode_distribution": {
      "classical_false_consciousness": 2,
      "cynical_reason": 1,
      "emancipatory_resistance": 1,
      "blind_drift": 0
    },
    "mean_cynicism": 0.2063,
    "mean_fantasy_integrity": 0.3855,
    "mean_theft_of_enjoyment": 0.222,
    "traversed_fantasy_count": 1,
    "hegemonic_diagnosis": "ORTHODOX_DOCTRINAL_HEGEMONY"
  }
}
```
