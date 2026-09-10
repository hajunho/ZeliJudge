# 막스 베버의 프로테스탄트 윤리와 자본주의 정신: 소명(Beruf), 현세적 금욕주의 및 합리화의 쇠우리(Iron Cage) 시뮬레이션 엔진

## 문제 설명

독일의 위대한 사회학자 **막스 베버(Max Weber)**는 고전적 명저 *《프로테스탄트 윤리와 자본주의 정신(Die protestantische Ethik und der Geist des Kapitalismus, 1905)》*을 통해 근대 서구 자본주의의 탄생이 단순한 물질적 탐욕이나 기술 발전의 산물이 아니라, **특정한 종교적 윤리(청교도/칼뱅주의적 정신)**의 역설적 귀결임을 증명했습니다.

베버가 규명한 역사적 동역학은 다음과 같습니다:

1. **이중 예정설(Double Predestination)과 실존적 고독**:
   - 장 칼뱅(Jean Calvin)의 신학에 따르면, 신이 누구를 구원하고 누구를 지옥으로 보낼지는 창세 전에 이미 결정되어 있으며 인간의 선행이나 교회의 면죄부로 바꿀 수 없습니다.
   - 이로 인해 신자들은 "내가 구원받은 자(선택받은 자)인가?"라는 극심한 내면적 구원 불안($SalvationAnxiety$)에 사로잡혔습니다.
2. **세속적 직업 소명설(Beruf)과 구원의 확신(Certitudo Salutis)**:
   - 중세 수도원적 금욕이 세속 바깥으로 탈출하는 것이었다면, 루터와 칼뱅 이후의 청교도들은 **세속의 일상적 직업 노동(Beruf)**을 신이 부여한 신성한 소명으로 받아들였습니다.
   - 세속 직업에서의 성실하고 끈질긴 성공과 부의 축적은 신의 은총을 입었다는 가장 확실한 심리적 증표($Certitudo \ Salutis$)가 되었습니다.
3. **현세적 금욕주의(Inner-worldly Asceticism)와 자본 축적**:
   - 청교도 윤리는 시간 낭비, 사치, 향락, 게으름을 최대의 죄악으로 규탄했습니다.
   - 돈을 버는 것은 신성한 의무였으나, 그 번 돈을 육체적 쾌락에 쓰는 것은 금지되었습니다.
   - 그 결과 **"소비의 억제(Asceticism) + 생산적 재투자(Reinvestment) = 자본의 폭발적 기하급수적 축적"**이라는 근대 자본주의 엔진이 가동되었습니다.
4. **합리화의 쇠우리(The Iron Cage / stahlhartes Gehäuse)**:
   - 그러나 시간이 흐르며 종교적 열정과 구원의 영혼은 증발(탈마법화, Entzauberung)하고, 차가운 경제적 계산과 도구적 합리성, 관료제적 기계 장치만이 남아 인간의 삶을 지배하게 됩니다.
   - 베버는 이를 탄식하며 다음과 같이 경고했습니다:
     > *"가벼운 망토처럼 성도의 어깨 위에 걸쳐져 언제든 벗어던질 수 있었던 외적 재화에 대한 배려가, 마침내 인간을 가두는 단단한 쇠우리(Iron Cage)가 되었다... 오늘날 우리는 영혼 없는 전문인, 가슴 없는 향락자(Fachmenschen ohne Geist, Genußmenschen ohne Herz)를 목도하고 있다."*

본 문제에서는 베버의 자본주의 정신 모델을 수리적으로 정식화하여, 주체들의 소명의식($Devotion$), 금욕주의($Asceticism$), 구원 불안($SalvationAnxiety$), 자본 재투자 동역학, 그리고 세속적 합리화 압력에 의해 출현하는 쇠우리 지수($IronCageIndex$)와 시대 체제($Epoch$)의 전이를 시뮬레이션하는 엔진을 구현합니다.

---

## 아키텍처 및 수학적 공식

```
                     [ 칼뱅주의 이중 예정설 ]
                     "누가 구원받을지 알 수 없다"
                                │
                                ▼
                   [ 극심한 내면적 구원 불안 ]
                    (Salvation Anxiety S > 0)
                                │
               구원의 징표(Certitudo Salutis) 탐색
                                ▼
        ┌───────────────────────────────────────────────┐
        │        세속적 직업 소명 (Beruf) 노동          │
        │        현세적 금욕주의 (Asceticism A)         │
        └───────────────────────┬───────────────────────┘
                                │
             소비 유출 억제 & 잉여 가치의 100% 생산적 재투자
                                ▼
               ┌─────────────────────────────────┐
               │     폭발적 근대 자본 축적 (K)    │
               │   신학적 열정의 점진적 탈마법화   │
               └────────────────┬────────────────┘
                                │
             종교적 영혼 증발 (Secular Rationalization)
             차가운 도구적 계산과 관료제의 일상화
                                ▼
               ┌─────────────────────────────────┐
               │    합리화의 쇠우리 (Iron Cage)   │
               │     기계화된 석화의 시대 도래     │
               │  "영혼 없는 전문인, 가슴 없는 향락자" │
               └─────────────────────────────────┘
```

### 1. 노동 생산, 소비 및 재투자 공식

각 경제 주체 $i$의 1회 노동 사이클(`work_cycle`):
1. **생산 및 총이윤 ($Profit_i$)**:
   $$Profit_i = Devotion_i 	imes 50.0 	imes (1.0 + Asceticism_i 	imes 0.8) 	imes market\_factor$$
2. **향락 소비 유출 ($Consumption_i$)**:
   금욕주의가 결여될수록($1.0 - Asceticism_i$) 세속적 향락으로 소비가 유출됩니다:
   $$Consumption_i = Profit_i 	imes (1.0 - Asceticism_i) 	imes 0.7$$
3. **순 자본 재투자 ($\Delta K_i$)**:
   $$Reinvestment_i = Profit_i - Consumption_i$$
   $$Capital_i \leftarrow Capital_i + Reinvestment_i$$
   $$TotalReinvested_i \leftarrow TotalReinvested_i + Reinvestment_i$$
   $$TotalConsumed_i \leftarrow TotalConsumed_i + Consumption_i$$
4. **구원 불안 완화**:
   성공적인 소명 수행과 자본 재투자는 신의 은총 징표로서 구원 불안을 감소시킵니다:
   $$SalvationAnxiety_i \leftarrow \max(0.0, SalvationAnxiety_i - Reinvestment_i 	imes 0.001)$$

### 2. 쇠우리 지수 ($IronCageIndex$) 및 시대 체제 ($Epoch$)

사회 평균 자본($\overline{K}$)과 종교적 소명 영혼($\overline{Spirit}$)으로부터 쇠우리 지수를 산출합니다:
$$\overline{K} = rac{1}{N}\sum_{i=1}^N Capital_i, \quad \overline{Spirit} = rac{1}{N}\sum_{i=1}^N (Asceticism_i 	imes SalvationAnxiety_i)$$
$$K_{factor} = egin{cases} rac{\overline{K}}{\overline{K} + 400.0}, & \overline{K} > 0 \ 0.0, & \overline{K} \le 0 \end{cases}$$
$$	ext{IronCageIndex} = 	ext{round}\Big(	ext{clamp}ig(	ext{rationalization\_pressure} 	imes 0.5 + K_{factor} 	imes 0.5 - \overline{Spirit} 	imes 0.25, 0.0, 1.0ig), 4\Big)$$

쇠우리 지수에 따른 시대 체제($Epoch$) 전이:
- $	ext{IronCageIndex} \ge 0.75$: `"IRON_CAGE_MECHANICAL_PETRIFICATION"` (기계화된 석화: 영혼 없는 전문인들의 쇠우리)
- $0.40 \le 	ext{IronCageIndex} < 0.75$: `"RATIONALIZED_MODERN_CAPITALISM"` (합리화된 근대 자본주의)
- $	ext{IronCageIndex} < 0.40$: `"EARLY_PROTESTANT_ETHIC_ASCETICISM"` (초기 청교도 금욕주의)

### 3. 명령어 명세 (Commands)

1. `WORK_AND_ACCUMULATE` (`cycles`, `market_factor`):
   - 모든 주체가 지정된 횟수(`cycles`)만큼 소명 노동과 자본 재투자를 반복합니다.
2. `SECULAR_RATIONALIZATION` (`intensity`):
   - 세계의 탈마법화(Entzauberung): 종교적 구원 불안을 증발시키고 합리화 압력을 강화합니다:
     $$	ext{rationalization\_pressure} \leftarrow \min(1.0, 	ext{rationalization\_pressure} + intensity)$$
     $$orall i, \; SalvationAnxiety_i \leftarrow \max(0.0, SalvationAnxiety_i - intensity 	imes 0.8)$$
     $$orall i, \; Asceticism_i \leftarrow \max(0.2, Asceticism_i - intensity 	imes 0.3)$$
3. `ASCETIC_REFORM` (`subject_id`, `asceticism_boost`):
   - 특정 주체의 청교도적 금욕과 절제를 강화합니다:
     $$Asceticism_i \leftarrow \min(1.0, Asceticism_i + asceticism\_boost)$$
4. `LUXURY_CONSUMPTION` (`subject_id`, `waste_amount`):
   - 특정 주체가 금욕을 포기하고 자본을 세속적 사치로 낭비합니다:
     $$w = \min(Capital_i, waste\_amount)$$
     $$Capital_i \leftarrow Capital_i - w, \quad TotalConsumed_i \leftarrow TotalConsumed_i + w$$
     $$Asceticism_i \leftarrow \max(0.0, Asceticism_i - 0.20)$$
5. `STEP`:
   - 스텝 카운터를 1 증가시키고 상태를 갱신합니다.
6. `QUERY_WEBER_STATE`:
   - 현재 시점의 스냅샷(`step`, `rationalization_pressure`, `iron_cage_index`, `epoch`, `agents`)을 `query_logs`에 저장합니다. (주체 딕셔너리는 `subject_id` 오름차순 정렬)

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "rationalization_pressure": 0.20,
    "agents": [
      {
        "subject_id": "calvinist_weaver",
        "name": "Puritan Weaver",
        "calling": "weaver",
        "capital": 50.0,
        "asceticism": 0.90,
        "calling_devotion": 0.90,
        "salvation_anxiety": 0.85
      }
    ]
  },
  "commands": [
    {"type": "WORK_AND_ACCUMULATE", "cycles": 5, "market_factor": 1.2},
    {"type": "QUERY_WEBER_STATE"},
    {"type": "STEP"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 한 줄로 출력합니다:
```json
{"total_steps":1,"rationalization_pressure":0.2,"iron_cage_index":0.1989,"epoch":"EARLY_PROTESTANT_ETHIC_ASCETICISM","agents":{"calvinist_weaver":{"subject_id":"calvinist_weaver","name":"Puritan Weaver","calling":"weaver","capital":481.89,"asceticism":0.9,"calling_devotion":0.9,"salvation_anxiety":0.4181,"total_reinvested":431.89,"total_consumed":32.51}},"query_logs":[{"step":0,"rationalization_pressure":0.2,"iron_cage_index":0.1989,"epoch":"EARLY_PROTESTANT_ETHIC_ASCETICISM","agents":{"calvinist_weaver":{"subject_id":"calvinist_weaver","name":"Puritan Weaver","calling":"weaver","capital":481.89,"asceticism":0.9,"calling_devotion":0.9,"salvation_anxiety":0.4181,"total_reinvested":431.89,"total_consumed":32.51}}}]}
```
