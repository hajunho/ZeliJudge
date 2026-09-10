# 안토니오 그람시의 문화적 헤게모니: 시민사회 동의(Consent), 유기적 지식인 및 진지전 대 기동전 엔진 (Antonio Gramsci Cultural Hegemony & War of Position Engine)

## 문제 설명

이탈리아의 독창적인 마르크스주의 철학자이자 정치이론가인 안토니오 그람시(Antonio Gramsci)는 파시스트 무솔리니 정권에 투옥된 동안 작성한 『옥중수고(Quaderni del carcere, 1929~1935)』에서 근대 자본주의 국가 권력의 작동 방식을 해부하는 기념비적인 **헤게모니(Hegemony) 이론**을 제시했습니다.

그람시에 따르면 근대 국가(State)는 단순한 물리적 강제력(Coercion) 집행 기구가 아닙니다. 국가는 정치사회(강제력)와 시민사회(자발적 동의)의 결합체인 **통합 국가(Integral State = Political Society + Civil Society)**입니다.

지배 계급은 법원, 경찰, 군대라는 외적 억압 기구만으로 지배하는 것이 아니라, 언론, 학교, 종교, 문화 제도라는 시민사회 참호망을 통해 자신들의 세계관을 피지배 계급의 **"자연스러운 상식(Common Sense, Senso Comune)"**으로 내면화시킴으로써 **자발적 동의(Spontaneous Consent)**를 획득합니다.

```
+---------------------------------------------------------------------------------+
|               안토니오 그람시의 헤게모니 및 국가 구조 (Integral State)          |
+---------------------------------------------------------------------------------+
|  통합 국가 (State) = 정치사회 (Political Society) + 시민사회 (Civil Society)    |
+---------------------------------------------------------------------------------+
          |                                                    |
          v (외적 강제력: Coercion)                            v (자발적 동의: Consent)
+------------------------------------+               +----------------------------+
| 군대, 경찰, 법원, 교도소           |               | 언론, 학교, 노조, 사법문화 |
| - 지배(Domination / Direct Force)  |               | - 지도력(Hegemony)         |
| - 법률적 집행과 물리적 처벌        |               | - 상식(Common Sense) 형성  |
+------------------------------------+               +----------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                     전통적 지식인 vs 유기적 지식인                        |
   |  - 전통적 지식인: 기존 질서의 상식을 '중립적'으로 포장하여 보존           |
   |  - 유기적 지식인: 피지배 계급의 경제적·정치적 요구를 대변하는 진지 개척   |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                  2대 투쟁 전략: 기동전 vs 진지전                          |
   |  1. 기동전 (War of Maneuver): 국가 기구에 대한 직접 돌파                  |
   |     - 참호 포화도(Trench Saturation) < 0.60 시 실패 & 강제력 반동         |
   |  2. 진지전 (War of Position): 시민사회 제도 참호를 점진적으로 탈환        |
   |     - 참호 포화도 >= 0.60 달성 시 새로운 역사적 블록(Historical Bloc) 완성|
   +---------------------------------------------------------------------------+
```

### 1. 알고리즘 및 핵심 상태 전이 명세

#### 1.1 헤게모니 지수 (Hegemony Index, $H$)
헤게모니는 강제력($F$)보다 대중의 자발적 동의($C$)가 높고, 두 힘이 안정적으로 정렬될 때 극대화됩니다:
$$	ext{alignment} = 1.0 - |C - F|$$
$$H = 	ext{round}(0.60 	imes C + 0.40 	imes 	ext{alignment}, 4)$$

#### 1.2 지식인 배치 (`DEPLOY_INTELLECTUAL`)
- **`ORGANIC` (유기적 지식인)**:
  해당 영역의 침투도(`organic_infiltrated`)를 증가시키고, 지배 계급의 헤게모니적 통제(`hegemonic_control`) 및 동의($C$)를 약화시킵니다.
- **`TRADITIONAL` (전통적 지식인)**:
  기존 질서의 상식을 강화하여 헤게모니 통제와 지배 동의($C$)를 보강합니다.
- 전체 참호 포화도(`trench_saturation`)는 모든 시민사회 제도들의 `organic_infiltrated` 평균치로 갱신됩니다.

#### 1.3 전략 집행 (`EXECUTE_STRATEGY`)
1. **`WAR_OF_MANEUVER` (기동전)**:
   - `trench_saturation < 0.60`: 서구 시민사회의 견고한 참호망에 부딪혀 실패(`FAILED_TRENCH_REBOUND`). 국가는 경찰/군사 강제력(`coercion += 0.25`)을 증강하여 탄압합니다.
   - `trench_saturation >= 0.60`: 이미 시민사회의 헤게모니를 쟁취했으므로 신속한 권력 교체 및 돌파에 성공(`BREAKTHROUGH_HISTORICAL_BLOC`). 강제력과 기존 동의가 급감합니다.
2. **`WAR_OF_POSITION` (진지전)**:
   - 시민사회 모든 제도의 `organic_infiltrated`를 점진적으로 확대하고 기존 지배 동의를 깎아내려 참호 포화도를 구조적으로 높입니다 (`TRENCH_CONSOLIDATED`).

#### 1.4 역사적 국면 분류
- **`HEGEMONIC_STABILITY`** ($H \ge 0.70$): 강고한 지배 헤게모니가 대중의 상식으로 군림하는 상태.
- **`ORGANIC_CRISIS`** ($0.40 \le H < 0.70$): 지배 계급이 동의를 잃고 정당성의 위기(Crisis of Authority)에 직면한 상태.
- **`COUNTER_HEGEMONIC_TRANSCENDENCE`** ($H < 0.40$): 대항 헤게모니 세력이 시민사회를 장악하고 새로운 역사적 블록을 확립한 상태.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "initial_coercion": 0.6,
    "initial_consent": 0.7,
    "initial_trench_saturation": 0.2
  },
  "operations": [
    {"op": "EXECUTE_STRATEGY", "strategy": "WAR_OF_MANEUVER", "strength": 1.0},
    {"op": "DEPLOY_INTELLECTUAL", "type": "ORGANIC", "domain": "media", "power": 2.0},
    {"op": "EXECUTE_STRATEGY", "strategy": "WAR_OF_POSITION", "strength": 2.5}
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "operations_count": 3,
    "war_of_maneuver_attempts": 1,
    "war_of_position_actions": 1,
    "hegemonic_stability_count": 1,
    "organic_crisis_count": 2,
    "counter_hegemony_count": 0
  },
  "final_metrics": {
    "coercion": 0.85,
    "consent": 0.31,
    "trench_saturation": 0.675,
    "hegemony_index": 0.37,
    "state": "COUNTER_HEGEMONIC_TRANSCENDENCE"
  },
  "institutions": {...},
  "history": [...],
  "event_log": [...]
}
```
