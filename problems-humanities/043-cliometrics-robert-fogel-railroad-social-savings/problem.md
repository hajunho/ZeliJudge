# 문제 #043: 철도가 없었다면 미국은 번영하지 못했을까?: 계량역사학(Cliometrics) & 경제사: 노벨상 수상자 로버트 포겔(Robert Fogel)의 대항사실적 역사 분석(Counterfactual History), 운송 네트워크 사회적 절약(Social Savings) 모델 및 1890 미국 철도 필수성 공리(Axiom of Indispensability) 반증 시뮬레이터 (Cliometrics: Robert Fogel's Counterfactual Social Savings & Railroad Indispensability Engine)

## 실무 및 학술 배경: 역사적 가상 세계(Counterfactual World)의 수리 계량화와 노벨경제학상
19세기 미국의 급격한 경제 성장과 대륙 횡단 산업혁명을 설명할 때, 전통 경제사학자들은 **"철도는 미국 산업화의 절대적인 원동력이었으며, 철도가 없었다면 미국의 경제 발전은 불가능했다"**는 이른바 **'철도 필수성의 공리(The Axiom of Indispensability)'**를 의심할 여지 없는 상식으로 받아들였습니다.

그러나 1964년, 경제학자 **로버트 포겔(Robert William Fogel)**은 기념비적인 명저 『철도와 미국의 경제성장: 계량경제학적 역사 연구(*Railroads and American Economic Growth: Essays in Econometric History*)』를 통해 역사학계에 대폭탄을 던졌습니다.

포겔은 컴퓨터와 계량경제학 기법을 역사학에 최초로 도입한 **'계량역사학(Cliometrics)'**을 창시하며, 과학적 질문을 던졌습니다:
* *"만약 19세기에 철도가 아예 발명되지 않았거나 건설되지 않았다면(Counterfactual World), 미국 경제는 정말로 붕괴했을까?"*
* *"철도가 없었다면 사람들은 가만히 손을 놓고 있었을까? 아니면 운하(Canal), 강(River), 오대호(Great Lakes) 수운망과 포장도로 마차(Wagon)를 확충하여 화물을 운송했을까?"*

포겔은 1890년 미국 전역의 주요 농산물(밀, 옥수수, 돼지고기) 운송 경로를 복합 운송 그래프로 모델링하고, **사회적 절약(Social Savings)**을 측정했습니다:
$$\text{사회적 절약 (Social Savings, } S) = \sum_{i, j} Q_{ij} \times \left( C^{\text{대항사실}}_{ij} - C^{\text{실제}}_{ij} \right)$$
* $C^{\text{실제}}_{ij}$: 철도가 존재하는 실제 세계의 톤당 최소 운송 비용 (다익스트라 최단 경로).
* $C^{\text{대항사실}}_{ij}$: 철도가 배제되고 수운(운하·호수·강)과 마차로만 구성된 대항사실적 세계의 톤당 최소 운송 비용.
  - 여기에는 운하의 **겨울철 결빙(Freezing)으로 인한 장기 보관 재고 금융 비용($\text{carrying cost} = \text{unit\_price} \times r \times \frac{\text{frozen\_days}}{365}$)**과 **항만 환적 비용(Transshipment)**이 정밀하게 산입됩니다.

포겔의 경이로운 계산 결과:
* 철도가 창출한 총 사회적 절약액은 1890년 미국 국민총생산(GNP, 약 120억 달러)의 **단 2.7%~4.7%에 불과**했습니다!
* 즉, 철도는 유용한 혁신이었지만 '대체 불가능한 필수품'은 아니었으며, 미국은 수운망 확충만으로도 거의 동일한 수준의 경제 성장을 달성할 수 있었음이 입증되었습니다.
* 이 파격적인 대항사실적 분석 방법론으로 포겔은 1993년 노벨 경제학상을 수상했습니다.

경제사 연구원이자 계량역사학 데이터 과학자로서, 19세기 미국 운송 네트워크의 실제 세계와 대항사실적 세계를 다익스트라 알고리즘으로 시뮬레이션하고 포겔의 사회적 절약 지표 및 필수성 공리 반증 여부를 판정하십시오.

---

## 계량역사학 사회적 절약 알고리즘 사양

### 1. 복합 운송 네트워크 그래프 ($G = (V, E)$)
- 노드 ($V$): 주요 농업 거점 및 소비/항만 도시 (Chicago, Buffalo, New York, St. Louis 등).
- 간선 ($E$): 두 도시 간의 운송 경로. 각 간선은 복수의 운송 모드(`modes`)를 가질 수 있습니다:
  - `"rail"`: 철도 운송 (거리 `distance_miles`, 톤마일당 운임 `rate_per_ton_mile`).
  - `"water"`: 수운 (운하/호수/강: 거리, 운임, 연간 결빙 일수 `frozen_days_per_year`, 톤당 환적 비용 `transshipment_cost_per_ton`).
  - `"wagon"`: 마차 도로 운송 (거리, 운임: 톤마일당 비용이 철도나 수운 대비 15~20배 높음).

---

### 2. 세계별 톤당 최단 경로 운송비 계산 (Dijkstra)
1. **실제 세계 (Actual World with Rail)**:
   - 모든 운송 모드(`rail`, `water`, `wagon`)를 자유롭게 환적/이용 가능.
   - 간선 통행 비용:
     - `rail` 또는 `wagon`: $\text{distance} \times \text{rate}$
     - `water`: $\text{distance} \times \text{rate} + \text{transshipment} + \left(\text{unit\_value} \times r \times \frac{\text{frozen\_days}}{365}\right)$
2. **대항사실적 세계 (Counterfactual World without Rail)**:
   - **`rail` 모드가 100% 완전 배제**됨!
   - 오직 수운(`water`)과 마차(`wagon`)만으로 네트워크를 주파해야 함.

---

### 3. 총 화물 운임 청구서 및 사회적 절약 산출
- 실제 세계 총 운임: $B_{\text{actual}} = \sum_{k} \text{tons}_k \times c^{\text{actual}}_k$
- 대항사실 세계 총 운임: $B_{\text{counterfactual}} = \sum_{k} \text{tons}_k \times c^{\text{counterfactual}}_k$
- **총 사회적 절약액 (Total Social Savings)**:
  $$S = B_{\text{counterfactual}} - B_{\text{actual}}$$
- **GNP 대비 사회적 절약 비율**:
  $$\text{gnp\_share\_pct} = \frac{S}{\text{GNP}} \times 100\% \quad (\text{소수점 둘째 자리 반올림})$$
- **역사적 필수성 공리 판정 (`verdict`)**:
  - `gnp_share_pct < 5.0%`: `"DISPROVED_AXIOM_OF_INDISPENSABILITY"` (포겔의 역사적 결론: 철도는 필수불가결하지 않았음).
  - `gnp_share_pct >= 5.0%`: `"INDISPENSABLE_INFRASTRUCTURE"`.

---

## 입력 형식 (`sys.stdin`)

JSON 객체로 주어지며 `mode`에 따라 동작합니다:
1. `mode == "CALCULATE_SOCIAL_SAVINGS"`: 지정된 운송망과 화물 수요에 대한 사회적 절약액 계산.
2. `mode == "SENSITIVITY_ANALYSIS"`: 마차 운임 변동에 따른 민감도 분석.

## 출력 형식 (`sys.stdout`)
단일 행의 압축된 JSON 문자열을 출력합니다.
