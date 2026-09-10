# 미셸 푸코: 판옵티콘 및 규율 권력-지식 엔진 (Michel Foucault: Panopticon & Disciplinary Society Engine)

## 문제 설명

20세기 후반 프랑스의 철학자이자 사상가인 **미셸 푸코(Michel Foucault, 1926~1984)**는 저서 『감시와 처벌: 감옥의 탄생』(*Surveiller et punir: Naissance de la prison*, 1975)에서 근대 권력의 작동 메커니즘을 근본적으로 재정의했습니다. 푸코에 따르면 근대 권력은 군주가 행사하던 과거의 잔혹한 신체형(사형, 고문)과 달리, 보이지 않는 곳에서 끊임없이 개인의 신체를 규율하고 관찰하며 '정상(Normal)'과 '비정상(Abnormal)'을 구분짓는 **규율 권력(Disciplinary Power)**이자 **권력-지식(Power-Knowledge, Pouvoir-Savoir)**의 복합체입니다.

이러한 규율 권력의 가장 완벽한 건축적·기능적 모델로 제시된 것이 제러미 벤담(Jeremy Bentham)의 **판옵티콘(Panopticon, 일망감시장치)**입니다. 원형 건물의 둘레에는 죄수나 노동자, 환자, 학생의 독방이 배치되고, 중심부에는 높은 감시탑이 위치합니다. 핵심은 **가시성의 비대칭성(Asymmetry of Visibility)**입니다. 수감자는 감시탑의 감시자가 자신을 보고 있는지 결코 확인할 수 없습니다(Unverifiable). 따라서 수감자는 언제나 자신이 감시받고 있다고 가정하게 되며, 결국 감시자의 시선을 스스로의 내면에 체화하여 스스로를 감시하고 통제하는 **'순종적인 신체(Corps dociles)'** 및 **'내면화된 자기 규율(Internalized Self-Policing)'**의 주체로 개조됩니다.

본 문제는 푸코의 판옵티콘 및 규율 사회 이론을 정량적·시계열적 상태 전이 시뮬레이션 엔진으로 구현하는 것입니다.

```
                    [ 중앙 감시탑 (Central Inspection Tower) ]
                         | (가시성의 비대칭성: 보고 있으나 보이지 않음)
                         v
       +---------------------------------------------------+
       |                   판옵티콘 압력 (P)                |
       |  - 감시 중(INSPECTING): P = 1.0                   |
       |  - 불확실(UNVERIFIABLE): P = 0.8 (상시 감시 체화)   |
       +---------------------------------------------------+
                                 |
                                 v
   [ 개별 신체 (Subjects) 관찰 & 측정치 업데이트 (Metric Deltas) ]
                                 |
                                 v
   [ 규범화 판정 (Normalizing Judgment) vs 기관 허용치 (Norm Ranges) ]
          /                                           \
    (규범 이탈: DEVIANT)                        (규범 순응: CONFORMING)
          |                                           |
  규율 제재 (Penalty 적용)                    규율 보상 및 훈육 강화
  C_new = C - pen + P * 0.05                  C_new = C + P * 0.10
  신체 상태: DEVIANT_ABNORMAL                 임계치 도달 여부에 따라:
                                              - DOCILE_BODY
                                              - INTERNALIZED_SELF_POLICING
                                 |
                                 v
   [ 시험 및 기록화 (Examination & Cataloging into Power-Knowledge Archive) ]
```

---

## 알고리즘 및 수학적 명세

### 1. 기본 설정 및 초기 상태
- **순응도 임계치 ($	au$)**: `config.surveillance_intensity_threshold` (기본값: $0.60$)
- **규범 이탈 제재치 ($\lambda$)**: `config.normalization_penalty` (기본값: $0.15$)
- **기관 규범 허용 범위**: `institution_rules.norm_ranges`
  각 지표 $k$에 대해 $[Min_k, Max_k]$ 구간이 주어집니다.
- **주체 목록**: 초기 순응도 $C_{init} \in [0.0, 1.0]$ 및 지표 측정값 딕셔너리 $M = \{k: v\}$.

### 2. 라운드별 시계열 감시 전이 과정
각 감시 라운드($round$)에 대해 다음 단계를 순서대로 수행합니다:

#### Step 1: 판옵티콘 감시 압력 ($P$) 계산
- 감시탑 상태(`tower_state`):
  - `"INSPECTING"`: 감시자가 직접 주시 중임 $\implies P = 1.0$
  - `"UNVERIFIABLE"`: 감시탑 창문이 차단되어 확인 불가 $\implies P = 0.8$  
    *(푸코의 원칙: 감시가 불확실할 때에도 피감시자는 감시받고 있다고 확신하여 높은 압력을 체감함)*

#### Step 2: 주체별 측정치 업데이트 및 규범화 검증
각 주체 $s$에 대해 (입력 순서 보존):
1. **지표 업데이트**: 관찰된 델타($\Delta v$)를 반영합니다.
   $$M'_k = 	ext{round}(M_k + \Delta v_k, 4)$$
2. **규범 이탈 판정 (Normalizing Judgment)**:
   - 기관 허용 구간 $[Min_k, Max_k]$에 대해, $M'_k < Min_k - 10^{-7}$ 또는 $M'_k > Max_k + 10^{-7}$인 지표 키를 수집합니다.
   - 수집된 이탈 지표 리스트 `deviations`는 알파벳 오름차순으로 정렬합니다.
   - `is_deviant = (len(deviations) > 0)`

#### Step 3: 순응도 전이 및 신체 상태 판정
기존 순응도 $C_{old}$로부터 새로운 순응도 $C_{new}$를 계산합니다:
- **규범 이탈 시 (`is_deviant == True`)**:
  $$C_{new} = \max(0.0, \min(1.0, C_{old} - \lambda + (P 	imes 0.05)))$$
  신체 상태: `"DEVIANT_ABNORMAL"`
- **규범 순응 시 (`is_deviant == False`)**:
  $$C_{new} = \max(0.0, \min(1.0, C_{old} + (P 	imes 0.10)))$$
  - $C_{new} \ge 	au - 10^{-7}$인 경우: `"INTERNALIZED_SELF_POLICING"` (내면화된 자기감시 주체)
  - 그렇지 않은 경우: `"DOCILE_BODY"` (순종적인 신체)
- 주체의 순응도를 소수점 넷째 자리로 반올림 갱신합니다: $C \leftarrow 	ext{round}(C_{new}, 4)$.

#### Step 4: 시험(Examination)과 권력-지식 기록보관소화
- 라운드에서 시험이 실시되었는지 여부(`examination_conducted`):
  - `True`: 개별 주체의 임상 데이터가 권력-지식 아카이브에 편입됨 $\implies$ `dossier_status = "CATALOGED_IN_ARCHIVE"`
  - `False`: 기록되지 않음 $\implies$ `dossier_status = "UNRECORDED"`

### 3. 최종 통계 요약 (Summary)
모든 라운드 종료 후:
- `institution_type`: 기관 유형 문자열
- `total_subjects`: 총 주체 수
- `internalized_self_policing_count`: 최종 순응도가 $	au$ 이상인 주체 수
- `disciplinary_deviants_count`: 최종 순응도가 $	au$ 미만인 주체 수
- `panoptic_internalization_rate`: $	ext{round}(rac{	ext{internalized\_count}}{	ext{total\_subjects}}, 4)$ (주체 수 0인 경우 0.0)

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "surveillance_intensity_threshold": 0.65,
    "normalization_penalty": 0.15
  },
  "institution_rules": {
    "institution_type": "bentham_panopticon_prison",
    "norm_ranges": {
      "silence_decibels": [0.0, 35.0],
      "cell_orderliness": [8.0, 10.0]
    }
  },
  "subjects": [
    {
      "subject_id": "INMATE-101",
      "name": "Jean Valjean",
      "initial_compliance": 0.50,
      "metrics": {
        "silence_decibels": 20.0,
        "cell_orderliness": 9.0
      }
    }
  ],
  "surveillance_rounds": [
    {
      "round": 1,
      "tower_state": "INSPECTING",
      "examination_conducted": true,
      "observed_behaviors": {
        "INMATE-101": {
          "metric_deltas": {
            "silence_decibels": 5.0
          }
        }
      }
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "institution_type": "bentham_panopticon_prison",
    "total_subjects": 1,
    "internalized_self_policing_count": 0,
    "disciplinary_deviants_count": 1,
    "panoptic_internalization_rate": 0.0
  },
  "surveillance_history": [
    {
      "round": 1,
      "tower_state": "INSPECTING",
      "examination_conducted": true,
      "subject_states": [
        {
          "subject_id": "INMATE-101",
          "name": "Jean Valjean",
          "compliance": 0.6,
          "deviations": [],
          "body_state": "DOCILE_BODY",
          "dossier_status": "CATALOGED_IN_ARCHIVE"
        }
      ]
    }
  ]
}
```

---

## 제약 조건

- $1 \le 	ext{total\_subjects} \le 100$
- $1 \le 	ext{surveillance\_rounds} \le 50$
- 모든 부동 소수점 수치는 소수점 넷째 자리까지 반올림(`round(v, 4)`)하여 기록합니다.
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
