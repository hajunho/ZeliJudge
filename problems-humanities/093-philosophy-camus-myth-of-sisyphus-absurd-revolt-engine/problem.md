# 알베르 카뮈의 시시포스 신화: 부조리(L'Absurde), 철학적 자살 및 실존적 반항(La Révolte) 엔진

## 문제 설명

1942년 프랑스의 소설가이자 철학자 **알베르 카뮈(Albert Camus)**는 저서 『시시포스 신화(Le Mythe de Sisyphe)』를 통해 20세기 실존주의와 철학계에 가장 강렬한 화두를 던졌습니다:

> *"진정으로 중대한 철학적 문제는 오직 하나뿐이다. 그것은 바로 자살이다. 인생이 살 가치가 있느냐 없느냐를 판단하는 것, 이것이 철학의 근본 질문에 답하는 것이다."*

카뮈에 따르면, **부조리(L'Absurde)**는 인간 본연의 명료함과 통합에 대한 갈망(`desire_for_meaning`)과 비합리적이고 침묵하는 세계(`world_silence`)가 정면으로 부딪칠 때 발생합니다. 인간은 삶에 본래적 의미가 없음을 깨달았을 때 세 가지 선택의 기로에 섭니다:
1. **육체적 자살(Physical Suicide)**: 부조리의 무게에 굴복하여 삶을 중단하는 것 (카뮈는 이를 비겁한 도피이자 패배로 거부함).
2. **철학적 자살(Philosophical Suicide / Leap of Faith)**: 키르케고르나 종교적 실존주의자들처럼 부조리를 견디지 못하고 초월적 신앙이나 내세, 혹은 인위적인 형이상학적 도그마로 도약(Leap)하여 지성을 희생시키는 것 (카뮈는 이를 지성의 자살로 규정하고 거부함).
3. **부조리한 반항(Absurd Revolt)**: 신이나 내세의 희망을 일체 거부한 채, 세계의 침묵과 죽음이라는 숙명을 차갑고 명료한 지성(`lucidity`)으로 응시하며 끊임없이 반항(Revolt), 자유(Freedom), 열정(Passion)을 불태우는 삶.

```
                     +------------------------------------+
                     |      인간의 의미/명료함 갈망 (D)     |
                     +------------------------------------+
                                       |
                                       v  (충돌: Confrontation)
                     +------------------------------------+
                     |      세계의 침묵과 불합리성 (S)     |
                     +------------------------------------+
                                       |
                                       v
         +------------------------------------------------------------+
         |                 부조리(L'Absurde) 의식의 각성               |
         |                 Absurd Index A = Λ * sqrt(D * S) * (1 - 0.5H) |
         +------------------------------------------------------------+
                                       |
                +----------------------+----------------------+
                |                      |                      |
                v                      v                      v
        [철학적 자살]           [육체적 자살]          [부조리한 반항 (시시포스)]
       H >= 0.5 (도약)        V < 0.2 & A > 0.55       희망 없는 명료한 직시
     지성의 포기/환상 추구      생명력 고갈/절망 굴복     반항(Revolt) · 자유 · 열정
                                                        "시시포스는 행복하다"
```

본 문제에서는 카뮈의 부조리 철학과 시시포스의 바위 굴리기 신화를 정밀하게 수리적으로 모델링한 **시시포스 부조리 판정 및 실존적 반항 시뮬레이션 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. 주체 파라미터
- `desire_for_meaning` ($D \in [0.0, 1.0]$): 삶의 의미, 목적, 설명에 대한 인간적 갈망.
- `world_silence` ($S \in [0.0, 1.0]$): 세계의 냉혹한 무관심, 불합리성, 침묵.
- `lucidity` ($\Lambda \in [0.0, 1.0]$): 자기기만 없는 차가운 지성적 명료함.
- `hope_escapism` ($H \in [0.0, 1.0]$): 초월적 도약, 사후세계 또는 형이상학적 환상에 대한 도피 성향.
- `vitality` ($V \in [0.0, 1.0]$): 신체적/정신적 생명력 (기본값: 0.5).
- `experiences_count` ($E \ge 1$): 누적된 생의 감각적 경험 수 (기본값: 1).

### 2. 부조리 지수 계산
- 원시 부조리도:
  $$A_{\text{raw}} = \Lambda \times \sqrt{D \times S} \times (1.0 - 0.5 \times H)$$
- 최종 부조리 지수:
  $$A = \text{round}(\min(1.0, \max(0.0, A_{\text{raw}})), 4)$$

### 3. 실존적 태도 분류 (`stance`)
1. **철학적 자살 (`PHILOSOPHICAL_SUICIDE`)**:
   - 조건: $H \ge 0.50$
   - 결과:
     - `revolt`: $0.0$
     - `freedom`: $\text{round}((1.0 - H) \times (1.0 - D \times 0.5), 4)$
     - `passion`: $\text{round}(0.1 \times V, 4)$
     - `verdict`: `"도약(Leap of Faith)에 의한 지성의 희생 및 형이상학적 현실 도피"`
     - `sisyphus_happy`: `false`
2. **육체적 자살 (`PHYSICAL_SUICIDE`)**:
   - 조건: $V < 0.20$ 이고 $A > 0.55$
   - 결과:
     - `revolt`: $0.0$, `freedom`: $0.0$, `passion`: $0.0$
     - `verdict`: `"부조리의 무게를 견디지 못하고 의식을 소멸시키는 육체적 자살 (패배 및 굴복)"`
     - `sisyphus_happy`: `false`
3. **부조리한 반항 (`ABSURD_REVOLT`)**:
   - 조건: 위의 두 도피/패배 조건을 벗어난 모든 주체.
   - 3대 귀결 지표 계산:
     - **반항(Revolt)**:
       $$\text{revolt} = \text{round}(\min(1.0, \Lambda \times (1.0 - H) \times (1.0 + 0.5 \times A)), 4)$$
     - **자유(Freedom)**:
       $$\text{freedom} = \text{round}(\min(1.0, (1.0 - H) \times (0.5 \times \Lambda + 0.5 \times (1.0 - D \times 0.5))), 4)$$
     - **열정(Passion)**:
       $$\text{exp\_factor} = \min(2.0, 1.0 + \ln(1 + E) \times 0.2)$$
       $$\text{passion} = \text{round}(\min(1.0, A \times \Lambda \times \text{exp\_factor}), 4)$$
     - `verdict`: `"부조리를 직시하며 희망 없이 삶의 조건을 긍정하는 항거(La Revolte)"`
     - `sisyphus_happy`: $\text{revolt} \ge 0.40$ 이고 $\Lambda \ge 0.50$ 일 때 `true`, 아니면 `false`. ("우리는 시시포스가 행복하다고 상상해야 한다")

### 4. 바위 굴리기 주기 시뮬레이션 (`SIMULATE_BOULDER_CYCLE`)
- 시시포스는 질량 $m$ (`boulder_mass`), 중력가속도 $g$ (`gravity`), 산 높이 $h$ (`peak_height`)에 대해 산꼭대기까지 바위를 밀어 올립니다.
- 1회 밀어올림 시 소모 일률:
  $$W = m \times g \times h \quad (\text{Joules})$$
- 정상에 도달하면 바위는 불가피하게 평원으로 굴러 떨어집니다.
- **하강(Descent) 동안 깨어나는 의식**:
  - 도전 지수 $\text{defiance} = \text{round}(\Lambda \times (1.0 - H), 4)$
  - 승리 지수 $\text{triumph} = \text{round}(\min(1.0, \text{defiance} \times (1.0 + 0.1 \times \ln(i + 1))), 4)$ (여기서 $i$는 누적 사이클 번호)
  - $\text{triumph} \ge 0.5$이면 명료한 순간 카운트(`lucid_moments_count`)를 1 증가시킵니다.
  - 운명의 주인화 여부: $\text{triumph} \ge 0.6$이면 `fate_mastered: true`, 아니면 `false`.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "boulder_mass": 100.0,
    "gravity": 9.8,
    "peak_height": 50.0
  },
  "operations": [
    {
      "op": "EVALUATE_SUBJECT",
      "params": {
        "desire_for_meaning": 0.85,
        "world_silence": 0.90,
        "lucidity": 0.95,
        "hope_escapism": 0.05,
        "vitality": 0.85,
        "experiences_count": 20
      }
    },
    {
      "op": "SIMULATE_BOULDER_CYCLE",
      "params": {
        "cycles": 3,
        "lucidity": 0.95,
        "desire_for_meaning": 0.90,
        "hope_escapism": 0.05
      }
    },
    { "op": "GET_ENGINE_STATS" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과를 담은 JSON 배열을 공백 없이(compact) 한 줄로 출력합니다.

---

## 제약 사항

- $0.0 \le D, S, \Lambda, H, V \le 1.0$
- $1 \le E \le 10^6$
- $1 \le \text{cycles} \le 10^5$
- 시간 복잡도: 각 평가 연산 $O(1)$, 사이클 연산 $O(\text{cycles})$, 전체 $O(N)$ 이내.
