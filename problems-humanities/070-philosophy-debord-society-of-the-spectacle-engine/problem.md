# 기 드보르의 스펙터클의 사회: 외양의 지배, 3대 스펙터클(집중·분산·통합) 및 상황주의 전용(Détournement) 엔진 (Guy Debord The Society of the Spectacle & Détournement Engine)

## 문제 설명

1967년 상황주의 인터내셔널(Situationist International)의 창시자 기 드보르(Guy Debord)는 후기 자본주의 소비사회와 미디어 문화를 통렬하게 비판한 걸작 『스펙터클의 사회(La Société du spectacle)』를 발표했습니다.

드보르는 현대 사회에서 인간의 삶이 겪은 가장 근본적인 소외를 **"직접 살아가는 삶의 모든 것이 하나의 단순한 이미지와 외양(Appearing/Spectacle)으로 전락한 사태"**로 정의했습니다:
> *"경제의 첫 번째 단계는 인간의 성취를 **'존재(Being)'**에서 **'소유(Having)'**로 퇴행시켰다. 그리고 지금 스펙터클이 지배하는 현대 단계는 '소유'에서 오직 **'외양(Appearing)'**으로의 전면적인 전도를 강요한다."*

스펙터클은 단순한 시각 이미지의 모음이 아니라, **"이미지들에 의해 매개된 사람들 사이의 사회적 관계(A social relation between people that is mediated by images)"**입니다.

```
+---------------------------------------------------------------------------------+
|                  기 드보르의 스펙터클 존재론적 3단계 전이 모델                  |
+---------------------------------------------------------------------------------+
|  1. 존재 (Being)      ---> 직접적인 삶의 실천, 자율적 연대, 생생한 체험         |
|         | (고전 자본주의 산업화)                                                |
|         v                                                                       |
|  2. 소유 (Having)     ---> 상품의 축적, 화폐적 소유가 인간의 가치를 규정        |
|         | (후기 미디어 자본주의 스펙터클화)                                     |
|         v                                                                       |
|  3. 외양 (Appearing)  ---> '보여지는 것(인스타그램, 광고, 브랜드, 가상)'이 실재를 대체|
+---------------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                       3대 스펙터클 양식 (Modes of Spectacle)              |
   |  - CONCENTRATED: 전체주의·독재의 단일 우상·군사 퍼레이드 (모드 계수 1.10) |
   |  - DIFFUSE: 현대 서구 소비사회의 상품 물신성과 무한 광고 (모드 계수 1.00)   |
   |  - INTEGRATED: 국가 감시와 글로벌 소비주의가 결합된 현대 사회 (계수 1.25)   |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                     상황주의 저항 전술 (Situationist Tactics)             |
   |  1. 전용 (Détournement): 지배 광고/슬로건을 탈취하여 체제 비판으로 전복   |
   |     - 외양(Appearing)을 직접적 비판의식(Being)으로 역환원                 |
   |  2. 표류 (Dérive): 상품 소비와 알고리즘 동선을 거부하는 심리지리학적 방랑|
   |     - 일상 공간의 직접적 체험(Being) 확장 및 소외 해방                    |
   +---------------------------------------------------------------------------+
```

### 1. 알고리즘 및 상태 전이 명세

#### 1.1 스펙터클 지수 (Spectacle Index, $S$)
$$S = 	ext{round}\left(\min\left(1.0, rac{	ext{appearing}}{	ext{being} + 	ext{having} + 	ext{appearing}} 	imes (1.0 + 0.4 	imes 	ext{media\_amplification}) 	imes 	ext{mode\_factor}ight), 4ight)$$
- 모드 계수: `CONCENTRATED` = 1.10, `DIFFUSE` = 1.00, `INTEGRATED` = 1.25

#### 1.2 스펙터클 방출 (`BROADCAST_SPECTACLE`)
- `intensity`에 비례하여 $	ext{Being} 	o 	ext{Having}$ 전이:
  $$\Delta 	ext{having} = \min(	ext{being}, 	ext{intensity} 	imes 0.10)$$
- `commodity_fetish`에 비례하여 $	ext{Having} 	o 	ext{Appearing}$ 전이:
  $$\Delta 	ext{appearing} = \min(	ext{having}, 	ext{intensity} 	imes 0.15 + 	ext{commodity\_fetish} 	imes 0.10)$$

#### 1.3 상황주의 전용 (`APPLY_DETOURNEMENT`)
체제 광고나 미디어 이미지를 전복하여 외양을 해체하고 주체성을 탈환합니다:
$$	ext{reclaimed} = \min(	ext{appearing}, 	ext{subversive\_power} 	imes 0.20)$$
$$	ext{appearing} \leftarrow 	ext{appearing} - 	ext{reclaimed}, \quad 	ext{being} \leftarrow 	ext{being} + 	ext{reclaimed}$$

#### 1.4 심리지리학적 표류 (`PERFORM_DERIVE`)
목적 없는 배회와 우연한 만남을 통해 상품 경로에서 탈출합니다:
$$	ext{gain\_being} = \min(0.30, 	ext{duration\_hours} 	imes 0.03 + 	ext{spontaneous\_events} 	imes 0.04)$$
$$	ext{being} \leftarrow 	ext{being} + 	ext{gain\_being}, \quad 	ext{having} \leftarrow 	ext{having} - \min(	ext{having}, 	ext{gain\_being} 	imes 0.5)$$

#### 1.5 사회적 상태 분류
- **`TOTAL_SPECTACULAR_ALIENATION`** ($S \ge 0.75$): 삶의 모든 영역이 미디어 이미지와 가상 외양에 완벽히 식민지화된 상태.
- **`DIFFUSE_COMMODITY_FETISHISM`** ($0.45 \le S < 0.75$): 상품 광고와 브랜드 유행이 소비자의 의식을 포섭한 상태.
- **`SITUATIONIST_EMANCIPATION`** ($S < 0.45$): 직접적 삶의 실천과 비판적 의식이 회복된 해방 상태.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "initial_mode": "DIFFUSE",
    "initial_being": 0.5,
    "initial_having": 0.35,
    "initial_appearing": 0.15,
    "media_amplification": 0.5
  },
  "operations": [
    {"op": "BROADCAST_SPECTACLE", "type": "DIFFUSE", "intensity": 1.5, "commodity_fetish": 0.8},
    {"op": "APPLY_DETOURNEMENT", "target_image": "luxury_car_billboard", "subversive_power": 1.2},
    {"op": "PERFORM_DERIVE", "duration_hours": 3.0, "spontaneous_events": 2}
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "operations_count": 3,
    "detournement_count": 1,
    "derive_count": 1,
    "alienation_count": 0,
    "max_spectacle_index": 0.564
  },
  "final_ontology": {
    "being": 0.551,
    "having": 0.1975,
    "appearing": 0.23,
    "spectacle_index": 0.2825,
    "state": "SITUATIONIST_EMANCIPATION",
    "mode": "DIFFUSE"
  },
  "history": [...],
  "event_log": [...]
}
```
