# 문제 037: 토머스 쿤의 패러다임 전환과 과학혁명의 구조 시뮬레이터 (Thomas Kuhn's Paradigm Shift & Scientific Revolutions Engine)

## 문제 설명

전통적인 과학철학과 논리실증주의는 과학의 역사를 "관측과 실험을 통해 참된 진리가 차곡차곡 누적되어 온 점진적 발전의 과정"으로 묘사해 왔습니다. 그러나 물리학자이자 과학철학자인 토머스 쿤(Thomas S. Kuhn, 1922~1996)은 1962년 출간된 불후의 명저 『과학혁명의 구조』(*The Structure of Scientific Revolutions*)에서 이러한 누적적 진보관을 정면으로 분쇄했습니다.

쿤에 따르면, 과학은 결코 선형적으로 축적되지 않으며, 특정 과학자 사회가 공유하는 세계관이자 문제 해결의 틀인 **패러다임(Paradigm)**이 단절적으로 교체되는 **'과학 혁명(Scientific Revolution)'**을 통해 도약합니다.

### 쿤의 과학 발전 4단계 상태 머신 (Epistemological State Machine)
1. **전(前) 패러다임 단계 (Pre-Paradigm Period)**:
   - 합의된 연구 규범이 없어 여러 학파가 기초 정의를 두고 끊임없이 논쟁하는 혼란 상태입니다.
2. **정상과학 (Normal Science)**:
   - 지배적 패러다임이 확립된 후, 과학자들은 패러다임이 제공하는 이론적 틀 안에서 정밀한 측정을 수행하고 미해결 문제를 해결하는 **'퍼즐 풀이(Puzzle-Solving)'**에 몰두합니다.
   - 관측 결과가 기존 이론의 예측과 일치하면 정상과학 퍼즐 풀이에 성공합니다. 예측과 맞지 않는 결과가 나와도 패러다임 자체를 의심하지 않고, 실험 기구의 결함이나 보조 가설의 오류로 취급합니다.
3. **변칙사례의 누적과 위기 (Anomaly Accumulation & Crisis)**:
   - 정상과학의 틀로 설명할 수 없는 **변칙사례(Anomaly)**가 지속적으로 발견되고 누적됩니다.
   - 누적된 변칙사례의 심각도(Severity) 총합이 패러다임의 허용 한계인 **위기 임계치(`anomaly_threshold`)**를 초과하면 과학자 공동체에 신뢰의 위기가 도래하며 시스템은 **위기(`CRISIS`)** 상태로 전환됩니다.
4. **비정상 과학과 혁명 (Extraordinary Science & Revolution)**:
   - 위기 상태에서 과학자들은 기존 패러다임을 의심하고 새로운 대안 패러다임들을 적극적으로 제안하기 시작합니다(`REVOLUTION` 상태).
   - 제안된 경쟁 패러다임이 누적된 변칙사례 심각도의 $75\%$ 이상을 성공적으로 해결(`resolves_anomalies`)하면, 과학자 집단의 전향(Gestalt Switch)이 일어나 **패러다임 전환(Paradigm Shift)**이 완수되고 시스템은 새로운 패러다임 기반의 **정상과학(`NORMAL_SCIENCE`)**으로 복귀합니다.
5. **공약불가능성 (Incommensurability)**:
   - 신·구 패러다임은 동일한 어휘(예: '질량', '시간', '행성', '연소')를 사용하더라도 그 개념적 의미(기의)가 근본적으로 변이(Semantic Shift)되므로, 중립적인 단일 언어로 두 패러다임의 우열을 객관적으로 직접 비교할 수 없습니다.

당신은 토머스 쿤의 패러다임 수립, 퍼즐 풀이, 변칙사례 누적, 위기 도래, 과학 혁명 평가 및 공약불가능성 지수를 측정하는 인식론 엔진을 구현해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "initial_paradigm": {
    "id": "P_PTOLEMY",
    "name": "Geocentric Ptolemaic Astronomy",
    "anomaly_threshold": 10.0,
    "vocabulary": {
      "planet": "wandering orb orbiting Earth",
      "center": "the Earth"
    }
  },
  "operations": [
    {
      "step": 1,
      "op": "OBSERVE_PHENOMENON",
      "phenomenon_id": "PHEN-01",
      "description": "Mars retrograde motion",
      "expected_prediction": "CIRCULAR",
      "observed_outcome": "RETROGRADE",
      "severity": 4.0
    },
    {
      "step": 2,
      "op": "PROPOSE_PARADIGM",
      "paradigm": {
        "id": "P_COPERNICUS",
        "name": "Heliocentric Copernican Astronomy",
        "anomaly_threshold": 15.0,
        "vocabulary": {
          "planet": "celestial body orbiting Sun",
          "center": "the Sun"
        },
        "resolves_anomalies": ["PHEN-01"]
      }
    },
    {
      "step": 3,
      "op": "EVALUATE_REVOLUTION",
      "candidate_id": "P_COPERNICUS"
    },
    {
      "step": 4,
      "op": "ANALYZE_INCOMMENSURABILITY",
      "target_paradigm_id": "P_COPERNICUS"
    },
    {
      "step": 5,
      "op": "GET_SNAPSHOT"
    }
  ]
}
```

### 연산 종류
1. `OBSERVE_PHENOMENON`: 현상을 관측합니다. 예측과 결과가 일치하면 `PUZZLE_SOLVED`, 불일치 시 `ANOMALY_RECORDED`로 기록하고 심각도를 누적합니다. 누적 심각도가 `anomaly_threshold` 이상이 되면 상태가 `CRISIS`로 전환됩니다.
2. `PROPOSE_PARADIGM`: 위기 상태에서 새로운 경쟁 패러다임을 등록합니다. 상태가 `CRISIS`였다면 `REVOLUTION`으로 변경됩니다.
3. `EVALUATE_REVOLUTION`: 후보 패러다임이 누적된 변칙사례 심각도의 $75\%$ 이상을 해결하는지 평가합니다. 만족 시 `PARADIGM_SHIFT_COMPLETED`가 발생하며 활성 패러다임이 교체되고 상태는 `NORMAL_SCIENCE`로 리셋됩니다.
4. `ANALYZE_INCOMMENSURABILITY`: 현재 활성 패러다임과 대상 패러다임 간의 공통 어휘 중 의미가 변이된 비율인 공약불가능성 지수(`incommensurability_index = shifted / shared`)와 어휘별 의미 차이를 산출합니다.
5. `GET_SNAPSHOT`: 현재 활성 패러다임, 인식론적 상태, 누적 변칙사례 수 및 통계 메트릭을 반환합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다. 모든 부동소수점 수치는 소수점 둘째 자리까지 반올림(`round(x, 2)`)합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "OBSERVE_PHENOMENON",
      "phenomenon_id": "PHEN-01",
      "status": "ANOMALY_RECORDED",
      "severity": 4.0,
      "total_severity": 4.0,
      "threshold": 10.0,
      "current_state": "NORMAL_SCIENCE"
    }
  ],
  "final_state": {
    "active_paradigm": "P_COPERNICUS",
    "active_paradigm_name": "Heliocentric Copernican Astronomy",
    "epistemological_state": "NORMAL_SCIENCE",
    "accumulated_anomaly_count": 0,
    "total_anomaly_severity": 0.0,
    "anomaly_threshold": 15.0,
    "metrics": {
      "puzzles_solved": 0,
      "anomalies_encountered": 1,
      "paradigm_shifts": 1,
      "crises_triggered": 1
    }
  }
}
```

---

## 제약 조건

- 패러다임 어휘 수: $1 \le |\text{vocabulary}| \le 20$
- 연산 수: $1 \le M \le 30$
- 현상 심각도: $0.1 \le \text{severity} \le 50.0$
- 혁명 성공 임계 비율: 누적 변칙사례 심각도의 $75\%$ 이상 해결 필요
