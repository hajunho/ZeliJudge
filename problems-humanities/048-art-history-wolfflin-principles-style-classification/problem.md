# 하인리히 뵐플린의 미술사 기초 개념: 5대 대립 범주 기반 르네상스 대 바로크 양식 판별 엔진 (Heinrich Wölfflin Principles of Art History Style Classifier)

## 문제 설명

스위스의 미술사학자 **하인리히 뵐플린(Heinrich Wölfflin, 1864–1945)**은 1915년 출간된 저서 『미술사의 기초 개념(Kunstgeschichtliche Grundbegriffe)』에서 예술 작품을 단순히 주제나 전기가 아닌 순수한 시각적·형식적 구조(Visual Form)로 파악하는 **양식사(Formgeschichte)**의 기틀을 정립했습니다.
그는 16세기 전성기 르네상스(High Renaissance)에서 17세기 바로크(Baroque)로의 이행을 인간 지각 방식(Modes of Seeing)의 근본적 전환으로 파악하며, 이를 설명하는 **5가지 형식적 대립 범주(Five Pairs of Oppositions)**를 제안했습니다.

본 문제에서는 예술 작품의 형식적 시각 메트릭(선, 면, 구도, 부분-전체 관계, 명암 조명)을 입력받아, 뵐플린의 5대 대립 쌍별 지수를 산출하고, 르네상스(-1.0)부터 바로크(+1.0)에 이르는 종합 뵐플린 지수(Composite Wölfflin Index)를 통해 미술사적 양식을 자동으로 정량 분류하고 두 작품 간의 통시적 양식 전이를 비교 분석하는 **미술사 양식 판별 엔진(Art Historical Style Classifier)**을 구현합니다.

---

## 5대 대립 범주 및 수식 체계

각 범주 점수는 **-1.0 (극단적 르네상스)**에서 **+1.0 (극단적 바로크)** 사이의 연속 실수 값으로 정규화(Clamp)됩니다.

### 1. 선적 vs 회화적 (Linear vs Painterly: `linear_vs_painterly`)
- **르네상스(선적)**: 사물의 경계와 윤곽선(Contour)이 명확하고 단단하게 분리됨.
- **바로크(회화적)**: 붓터치 블렌딩과 명암 융합을 통해 사물의 외곽선이 배경과 뒤섞이고 경계가 모호해짐.
$$s_1 = 	ext{clamp}(	ext{brushstroke\_blending} - 	ext{contour\_definition}, -1.0, 1.0)$$

### 2. 평면 vs 깊이 (Plane vs Recession: `plane_vs_recession`)
- **르네상스(평면)**: 인물과 건축물이 캔버스 평면과 평행한 층위(Layer)로 정연하게 전개됨.
- **바로크(깊이)**: 대각선 단축법(Foreshortening)과 사선 축(Diagonal Axis)을 따라 화면 안쪽 깊숙이 빨려 들어가는 역동적 공간감 형성.
$$s_2 = 	ext{clamp}(	ext{diagonal\_recession} - 	ext{parallel\_planes}, -1.0, 1.0)$$

### 3. 폐쇄된 형태 vs 개방된 형태 (Closed vs Open Form: `closed_vs_open_form`)
- **르네상스(폐쇄)**: 프레임(틀) 내부에 수직·수평 기하학적 안정 구도를 갖추며 화면 내부에서 완결됨.
- **바로크(개방)**: 사선과 동적 시선 유도를 통해 프레임 바깥으로 공간이 확장되고 캔버스 밖의 보이지 않는 공간과 연결됨.
$$s_3 = 	ext{clamp}(	ext{off\_canvas\_focus} - 	ext{frame\_containment}, -1.0, 1.0)$$

### 4. 다원성 vs 통일성 (Multiplicity vs Unity: `multiplicity_vs_unity`)
- **르네상스(다원성)**: 화면 속 각 인물이나 모티브가 독립된 완결성과 형태적 개별성을 보존하며 조화롭게 병렬됨.
- **바로크(통일성)**: 단일한 주도적 모티브나 강렬한 광선에 모든 개별 요소들이 종속되어 하나의 거대한 유기적 덩어리로 통합됨.
$$s_4 = 	ext{clamp}(	ext{subordination\_to\_focus} - 	ext{part\_autonomy}, -1.0, 1.0)$$

### 5. 절대적 명료성 vs 상대적 명료성 (Absolute vs Relative Clarity: `absolute_vs_relative_clarity`)
- **르네상스(절대적 명료성)**: 모든 사물이 균일한 빛 아래 완벽하게 조명되어 세부 형태와 해부학적 구조가 명명백백하게 드러남.
- **바로크(상대적 명료성)**: 극단적 명암대비(키아로스쿠로/테네브리즘)로 인해 사물의 일부가 어둠 속에 은폐되며 관람자의 상상력에 의해 완성됨.
$$s_5 = 	ext{clamp}(	ext{chiaroscuro\_obscuration} - 	ext{uniform\_illumination}, -1.0, 1.0)$$

---

## 종합 지수 및 양식 분류 (Classification Rules)

### 종합 뵐플린 지수 (Composite Wölfflin Index)
$$C = rac{1}{5} \sum_{i=1}^{5} s_i \quad (	ext{소수점 셋째 자리 반올림})$$

### 양식 분류 구간
- $C \le -0.40$: `HIGH_RENAISSANCE` (전성기 르네상스 - 라파엘로, 다빈치, 미켈란젤로)
- $-0.40 < C \le -0.10$: `MANNERISM` (매너리즘 / 과도기 르네상스 - 파르미지아니노, 브론치노)
- $-0.10 < C \le 0.10$: `BALANCED_HYBRID` (절충적 고전주의)
- $0.10 < C \le 0.40$: `EARLY_BAROQUE` (초기/온건 바로크 - 안니발레 카라치)
- $C > 0.40$: `HIGH_BAROQUE` (전성기 바로크 - 카라바조, 루벤스, 베르니니, 렘브란트)

### 범주별 극성 (Polarities)
- $s_i < -0.15$: `RENAISSANCE_DOMINANT`
- $s_i > 0.15$: `BAROQUE_DOMINANT`
- 기타: `NEUTRAL`

---

## 동작 모드

1. `single`: 단일 작품의 5대 범주 점수, 종합 지수, 양식 분류, 극성 판별.
2. `compare`: 두 작품 A, B 간의 범주별 차이($\Delta_i = s_{B,i} - s_{A,i}$), 유클리드 거리($\sqrt{\sum \Delta_i^2}$), 최대 발산 범주(`max_divergence_category`), 양식 전이 유형(`shift_type`):
   - $C_B - C_A > 0.30$: `RENAISSANCE_TO_BAROQUE_TRANSITION`
   - $C_B - C_A < -0.30$: `CLASSICAL_LINEAR_REVIVAL` (신고전주의 등 선적 고전 복귀)
   - 기타: `INTRA_ERA_VARIATION`
3. `batch`: 다수의 작품 코퍼스에 대한 전수 평가 및 평균 지수, 양식별 분포 통계 집계.

---

## 입출력 예시

### 입력 (`single` 모드)
```json
{
  "mode": "single",
  "artwork": {
    "title": "School of Athens",
    "artist": "Raphael",
    "year": 1511,
    "metrics": {
      "contour_definition": 0.95,
      "brushstroke_blending": 0.10,
      "parallel_planes": 0.90,
      "diagonal_recession": 0.15,
      "frame_containment": 0.92,
      "off_canvas_focus": 0.08,
      "part_autonomy": 0.88,
      "subordination_to_focus": 0.20,
      "uniform_illumination": 0.95,
      "chiaroscuro_obscuration": 0.05
    }
  }
}
```

### 출력
```json
{
  "mode": "single",
  "result": {
    "title": "School of Athens",
    "artist": "Raphael",
    "year": 1511,
    "category_scores": {
      "linear_vs_painterly": -0.85,
      "plane_vs_recession": -0.75,
      "closed_vs_open_form": -0.84,
      "multiplicity_vs_unity": -0.68,
      "absolute_vs_relative_clarity": -0.9
    },
    "composite_wolfflin_index": -0.804,
    "classification": "HIGH_RENAISSANCE",
    "style_label": "전성기 르네상스 (High Renaissance)",
    "polarities": {
      "linear_vs_painterly": "RENAISSANCE_DOMINANT",
      "plane_vs_recession": "RENAISSANCE_DOMINANT",
      "closed_vs_open_form": "RENAISSANCE_DOMINANT",
      "multiplicity_vs_unity": "RENAISSANCE_DOMINANT",
      "absolute_vs_relative_clarity": "RENAISSANCE_DOMINANT"
    }
  }
}
```
