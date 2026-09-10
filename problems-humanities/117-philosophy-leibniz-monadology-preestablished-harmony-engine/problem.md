# 고트프리트 빌헬름 라이프니츠: 단자론(Monadologie), 예정조화설(Harmonia Praestabilita) 및 미소지각 시뮬레이션 엔진

## 문제 설명

17~18세기 독일의 보편천재 철학자이자 수학자 **고트프리트 빌헬름 라이프니츠(Gottfried Wilhelm Leibniz, 1646~1716)**는 데카르트의 기계론적 물리학(물질의 연장)과 스피노자의 실체일원론을 비판하며, 1714년 저작 『단자론(Monadologie)』을 통해 독창적인 다원론적 형이상학을 정립했습니다.

라이프니츠에 따르면 우주의 궁극적인 실체는 물리적 원자가 아니라 영적이고 비물질적인 단순 실체인 **단자(Monad, 모나드)**들입니다:
> *"단자들에는 어떠한 것도 드나들 수 있는 창문이 없다(Les monades n'ont point de fenêtres)."*

```
 [외부 상호작용 없는 '창문 없는' 단자들]
   [ 단자 A (Spirit) ]            [ 단자 B (Soul) ]            [ 단자 C (Bare Monad) ]
   (내적 시계: Rate 1.0)          (내적 시계: Rate 1.0)          (내적 시계: Rate 1.0)
   (관점: 0도 관측)               (관점: 90도 관측)             (관점: 180도 관측)
            \                             |                             /
             +-----------------------------+---------------------------+
                                           |
                                [ 신의 예정조화 (Pre-established Harmony) ]
                                (우주 창조 시 완벽한 동기화)
                                           |
                                  [ 우주적 사건 발생 ]
```

### 핵심 아키텍처 및 철학적 원리
1. **창문 없는 단자 (Windowless Monads)와 예정조화설 (Harmonia Praestabilita)**:
   - 단자들은 물리적으로 서로에게 영향을 미치거나 메시지를 직접 교환할 수 없습니다.
   - 신(God)이 우주를 창조할 때 모든 단자의 내적 시계(내적 전개 법칙)를 완벽하게 조화시켜 놓았기 때문에, 각 단자는 자신의 고유한 관점(Perspective Angle $\theta$)에서 전 우주의 사건을 자율적으로 거울처럼 반영(Mirroring)합니다.
2. **미소지각(Petites Perceptions)과 통각(Apperception)**:
   - 단자의 표상은 미세한 무의식적 음향의 합인 **미소지각(Petites Perceptions)**에서 출발합니다 (예: 거대한 바다 파도의 포효는 수많은 개별 물방울들의 들리지 않는 미세 소리의 총합).
   - 미소지각의 총합이 임계치($\ge 0.25$)를 넘으면 **의식적 지각(Conscious Perception)**이 되고, 최상위 단자인 정신(Spirit) 단자는 자의식과 반성적 이성을 갖춘 **통각(Apperception)**에 도달합니다($\ge 0.35$).
3. **식별불가능자의 동일성 원리 (Identity of Indiscernibles)**:
   - 라이프니츠 형이상학의 근본 공리: 우주에는 관점, 본성, 내적 지각 상태가 완전히 동일한 두 단자가 결코 존재할 수 없습니다.
4. **최선의 세계 (The Best of All Possible Worlds / Théodicée)**:
   - 신이 창조한 현실 세계는 가능한 모든 세계 중 **"최대의 다양성(Maximum Variety)"**과 **"최소/최고 질서의 법칙(Order/Simplicity of Principles)"**이 완벽한 균형을 이루는 최적화된 세계입니다.

본 문제에서는 단자들의 관점별 우주 사건 반영, 미소지각의 통각 집적, 식별불가능자의 동일성 검증, 클록 분산에 따른 질서도 측정 및 최선의 세계 최적화 판정 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "monads": [
    {
      "id": "spirit_newton",
      "monad_type": "SPIRIT",
      "perspective_angle": 0.0,
      "internal_clock_rate": 1.0,
      "petites_perceptions": [0.15, 0.12, 0.18]
    },
    {
      "id": "spirit_leibniz",
      "monad_type": "SPIRIT",
      "perspective_angle": 180.0,
      "internal_clock_rate": 1.0,
      "petites_perceptions": [0.2, 0.25]
    }
  ],
  "cosmic_events": [
    {
      "event_id": "genesis_light",
      "intensity": 8.0,
      "spatial_source_angle": 0.0,
      "timestamp": 1
    }
  ],
  "simulation_ticks": 2
}
```

### 파라미터 규격
- `monads` (배열): 시뮬레이션할 단자 객체 목록.
  - `id` (문자열): 단자 식별자.
  - `monad_type` (문자열): `"BARE_MONAD"`(단순 무의식 단자), `"SOUL"`(기억을 갖춘 영혼 단자), `"SPIRIT"`(이성과 통각을 갖춘 정신 단자).
  - `perspective_angle` (실수, $0.0 \le \theta < 360.0$): 우주를 바라보는 고유 관점 각도.
  - `internal_clock_rate` (실수): 내적 시간 진행 속도.
  - `petites_perceptions` (배열 of 실수): 잠재된 미소지각 값들.
- `cosmic_events` (배열): 우주에서 일어나는 전역 사건 목록 (`event_id`, `intensity`, `spatial_source_angle`, `timestamp`).
- `simulation_ticks` (정수): 시뮬레이션 진행 틱 수 ($t = 1, 2, \dots$).

---

## 계산 명세

1. **미소지각 집적 및 지각/통각 판정**:
   - `petites_sum` = $\text{round}(\sum p_i, 4)$.
   - `conscious_perception` = `petites_sum >= 0.25`.
   - `apperception_achieved` = (`monad_type == "SPIRIT"` and `petites_sum >= 0.35`).

2. **식별불가능자의 동일성 (Identity of Indiscernibles) 검증**:
   - 임의의 서로 다른 두 단자 $(A, B)$에 대해, 관점 각도 차이 $< 10^{-4}$, 동일한 `monad_type`, 미소지각 합 차이 $< 10^{-4}$이면 `indiscernibles_violation = true` 및 위반 쌍 목록에 추가.

3. **예정조화에 따른 관점별 우주 사건 반영 (Mirroring)**:
   - 매 틱 $t$마다:
     - `internal_time` = $\text{round}(\text{internal\_time} + \text{clock\_rate}, 2)$.
     - 틱 $t$에 해당하는 우주 사건이 있으면:
       - 관점 계수: $\text{perspective\_factor} = \cos(\text{radians}(\theta_{\text{monad}} - \theta_{\text{event}}))$.
       - 단자 타입 배율: `"SPIRIT"` (1.2), `"SOUL"` (1.0), `"BARE_MONAD"` (0.8).
       - 표현 명석도: $\text{expressed\_clarity} = \text{round}(\text{intensity} \times |\text{perspective\_factor}| \times \text{type\_mult}, 4)$.

4. **변신론(Théodicée) 최선의 세계 최적화 지표**:
   - 다양성 점수 `variety_score`:
     - $\text{round}(\min(10.0, (\text{unique\_types} \times 2.0) + ((\max(\theta) - \min(\theta)) / 36.0)), 4)$.
   - 질서 점수 `order_score`:
     - 클록 분산 $\sigma^2 = \frac{1}{N} \sum (c_i - \bar{c})^2$.
     - $\text{round}(\max(1.0, 10.0 - \sigma^2 \times 10.0), 4)$.
   - 최적성 지표 `best_world_optimality`: $\text{round}((\text{variety\_score} \times \text{order\_score}) / 10.0, 4)$.
   - 세계 상태 판정 (`world_status`):
     - `indiscernibles_violation == true` $\rightarrow$ `"VIOLATION_INDISCERNIBLE_DUPLICATE"`
     - `best_world_optimality >= 7.0` $\rightarrow$ `"OPTIMUM_HARMONIA_PRAESTABILITA"`
     - `order_score < 5.0` $\rightarrow$ `"DESYNCHRONIZED_MONADIC_CHAOS"`
     - 그 외 $\rightarrow$ `"SUBOPTIMAL_POSSIBLE_WORLD"`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "monad_count": 2,
  "indiscernibles_principle": {
    "violation": false,
    "violating_pairs": []
  },
  "theodicy_metrics": {
    "variety_score": 7.75,
    "order_score": 10.0,
    "best_world_optimality": 7.75,
    "world_status": "OPTIMUM_HARMONIA_PRAESTABILITA"
  },
  "monads_state": [
    {
      "id": "spirit_newton",
      "type": "SPIRIT",
      "perspective_angle": 0.0,
      "clock_rate": 1.0,
      "petites_sum": 0.45,
      "conscious_perception": true,
      "apperception_achieved": true,
      "internal_time": 2.0,
      "mirrored_events_log": [
        {
          "tick": 1,
          "event_id": "genesis_light",
          "perspective_factor": 1.0,
          "expressed_clarity": 9.6
        }
      ]
    }
  ]
}
```

---

## 제약 조건

- $1 \le \text{len(monads)} \le 100$
- $0 \le \text{len(cosmic\_events)} \le 50$
- $1 \le \text{simulation\_ticks} \le 20$
- 모든 부동소수점 값은 명시된 반올림 규칙(`round(x, 4)`)을 준수합니다.
- 실행 시간 제한: 2.0초 이내
- 메모리 사용 제한: 256MB 이내
