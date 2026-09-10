# Problem #044: 고고학 유물 공반 편년법(Seriation)과 브레이너드-로빈슨(Brainerd-Robinson) 상대 연대 측정 엔진

## 1. 개요 및 인문학적 배경 (Overview & Humanistic Background)

방사성 탄소 연대 측정법($^{14}\text{C}$)이 발명되기 전인 19세기 말, 영국의 고고학자 **윌리엄 플린더스 피트리(Sir William Flinders Petrie, 1853~1942)**는 이집트 나카다(Naqada)의 선왕조 시대 고분 900여 기를 발굴하면서 기념비적인 학문적 과제에 직면했습니다. 문자 기록이나 동전처럼 절대 연대를 알려주는 유물이 전혀 없는 상태에서, 수많은 무덤들이 어느 순서로 축조되었는지를 밝혀내야 했던 것입니다.

피트리는 유적에 출토된 토기 양식들의 공반(共伴, Co-occurrence) 관계를 체계화하여 인류 최초의 **상대 편년법(Relative Chronology: Seriation)**을 창안했습니다. 유물의 유행은 갑자기 나타났다 사라지는 것이 아니라, "등장 -> 완만한 증가 -> 절정(Peak) -> 점진적 쇠퇴 -> 소멸"이라는 단봉형(Unimodal) 곡선, 즉 **전함 곡선(Battleship curve)**을 그립니다. 따라서 시간적으로 가까운 시기의 무덤들은 유물 양식의 구성 비율이 매우 유사하며, 시간적 거리가 멀어질수록 유사도는 단조 감소합니다.

```
       시간 흐름에 따른 유물 양식별 상대 빈도 변화 (Battleship Curves)
  시간 (상대 연대)
    ▲
최근│   [양식 A]        [양식 B]             [양식 C]
    │      .          .::::::::.         .::::::::::::.
    │     ...        .::::::::::.       .::::::::::::::.
    │    .....      .::::::::::::.       .::::::::::::.
    │   .......       .::::::::.           .::::::::.
    │  .........         ....                 ....
    │ ...........         ..                   ..
오래됨+------------------------------------------------------------►
                                                            유물 유형
```

1951년 고고학자 조지 브레이너드(George Brainerd)와 수학자 W. S. 로빈슨(W. S. Robinson)은 이를 계량화하여 **브레이너드-로빈슨 유사도 계수(Brainerd-Robinson Similarity Coefficient)**와 **로빈슨 행렬(Robinson Matrix)** 이론을 정립했습니다.

두 유적지 $A$와 $B$에서 각 유물 유형 $k$의 백분율 빈도를 $p_{A, k}$, $p_{B, k}$라 할 때, 브레이너드-로빈슨 계수 $BR(A, B)$는 다음과 같이 정의됩니다:
$$BR(A, B) = 200 - \sum_{k=1}^{M} |p_{A, k} - p_{B, k}|$$
- 두 유적의 유물 구성비가 100% 일치하면 $BR = 200$ (최대 유사도).
- 두 유적 간 공유하는 유물이 전혀 없으면 $BR = 0$ (완전 불일치).

유적들의 상대 연대 순서 $\pi = (\pi_1, \pi_2, \dots, \pi_N)$가 올바르게 정렬되면, 인접한 유적 간의 유사도 합 $\sum_{t=1}^{N-1} BR(\pi_t, \pi_{t+1})$이 최대화되며, 정렬된 유사도 행렬은 대각선에서 멀어질수록 값이 단조 감소하는 **로빈슨 행렬(Robinson form)**을 만족하게 됩니다.

이 문제에서는 여러 고분/층위에서 출토된 유물 수량 데이터를 입력받아 브레이너드-로빈슨 유사도를 계산하고, 비트마스크 동적 계획법(Bitmask DP)을 통해 최적의 상대 연대 순서를 복원하며, 로빈슨 위반(Robinson Violations) 및 유물 양식별 전함 곡선 단봉성(Unimodality)을 판정하는 인문학 컴퓨팅 엔진을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "anchor_site": "Tomb_B101"
  },
  "assemblages": [
    {
      "site_id": "Tomb_B103",
      "artifacts": {
        "Black_Topped": 30,
        "Decorated": 20,
        "Rough_Ware": 25,
        "Wavy_Handled": 25
      }
    },
    {
      "site_id": "Tomb_B101",
      "artifacts": {
        "Black_Topped": 80,
        "Decorated": 0,
        "Rough_Ware": 15,
        "Wavy_Handled": 5
      }
    }
  ]
}
```

- `config`:
  - `anchor_site` (string 또는 null): 시간의 기점(가장 오래된 층위 또는 기준 무덤)으로 지정된 사이트 ID. `null`인 경우 양방향 대칭 경로 중 사전식(Lexicographical)으로 시작 사이트 ID가 앞서는 방향을 표준 방향으로 채택합니다.
- `assemblages`: 유적/층위/고분 목록 ($2 \le N \le 12$).
  - `site_id`: 고유 식별자 문자열.
  - `artifacts`: 유물 유형별 출토 수량 딕셔너리 (음이 아닌 정수).

### 처리 규칙 (Processing Rules)

1. **유물 백분율 빈도 계산**:
   - 각 유적 $i$에 대해 유물 $k$의 백분율 $p_{i, k} = \frac{\text{artifacts}[k]}{\sum_j \text{artifacts}[j]} \times 100.0$을 소수점 둘째 자리까지 반올림(`round(val, 2)`)하여 계산합니다. (총 수량이 0인 경우 0.0)

2. **브레이너드-로빈슨 유사도 행렬 계산**:
   - 모든 유적 쌍 $(i, j)$에 대해 $BR(i, j) = \text{round}(200.0 - \sum_k |p_{i, k} - p_{j, k}|, 2)$를 계산합니다. (자기 자신 $BR(i, i) = 200.0$)

3. **연속 유사도 최대화 경로 탐색 (Optimal Seriation Permutation)**:
   - 비트마스크 동적 계획법(Bitmask DP)을 사용하여 모든 유적을 정확히 한 번씩 방문하며 인접 유적 간 유사도 합 $\sum_{t=1}^{N-1} BR(\pi_t, \pi_{t+1})$을 최대화하는 순열 $\pi$를 찾습니다.
   - `anchor_site`가 지정된 경우 해당 사이트가 반드시 순열의 시작점($\pi_1$)이어야 합니다.
   - `anchor_site`가 `null`인 경우, 최대 점수를 달성하는 경로 $\pi$와 그 역순 $\pi^{-1}$ 중 첫 번째 사이트 ID가 사전순으로 앞서는 경로를 선택합니다.
   - 동점 경로 발생 시 탐색 순서(작은 인덱스 우선)로 결정론적 결과를 유지합니다.

4. **로빈슨 위반(Robinson Violations) 검사**:
   - 정렬된 순열 $\pi$에 따른 $N \times N$ 유사도 행렬에서, 각 행 $i$에 대해:
     - 오른쪽 원소들: $i < j < k$에 대해 $BR(\pi_i, \pi_j) < BR(\pi_i, \pi_k)$이면 위반 1회.
     - 왼쪽 원소들: $k < j < i$에 대해 $BR(\pi_i, \pi_j) < BR(\pi_i, \pi_k)$이면 위반 1회.
   - 전체 행에 걸친 총 위반 횟수를 합산합니다.

5. **유물별 전함 곡선 단봉성(Battleship Unimodality) 판정**:
   - 정렬된 순서에 따른 유물 빈도 수열 $[p_{\pi_1, k}, p_{\pi_2, k}, \dots, p_{\pi_N, k}]$가 약한 증가 후 약한 감소 형태(피크를 찍고 내려온 뒤 다시 $0.001$을 초과하여 상승하지 않는 형태)를 만족하는지 검사합니다.
   - 단봉성을 만족하는 유물 유형의 비율 `unimodal_compliance_pct`를 백분율 소수점 둘째 자리로 산출합니다.

6. **상태 판정 (`status`)**:
   - 위반 횟수 0: `"PERFECT_ROBINSON_SERIATION"`
   - 위반 횟수 > 4 이거나 `unimodal_compliance_pct < 60.0`: `"STRATIGRAPHIC_ANOMALY_OR_DISTURBED"`
   - 그 외: `"CHRONOLOGICALLY_ROBUST"`

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "seriated_order": ["Tomb_B101", "Tomb_B102", "Tomb_B103", "Tomb_B104", "Tomb_B105"],
  "consecutive_similarity_sum": 580.45,
  "robinson_violations_count": 0,
  "unimodal_compliance_pct": 100.0,
  "status": "PERFECT_ROBINSON_SERIATION",
  "battleship_curves": {
    "Black_Topped": {
      "frequencies": [80.0, 55.0, 30.0, 15.0, 5.0],
      "peak_site": "Tomb_B101",
      "is_unimodal": true
    }
  },
  "seriated_similarity_matrix": [
    [200.0, 150.0, 100.0, 70.0, 50.0],
    [150.0, 200.0, 150.0, 120.0, 100.0]
  ]
}
```

---

## 3. 제약 사항 (Constraints)
- 유적/고분 개수 $N$: $2 \le N \le 12$
- 유물 유형 개수 $M$: $1 \le M \le 30$
- 유물 출토 수량: $0 \le \text{count} \le 10,000$
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`).
