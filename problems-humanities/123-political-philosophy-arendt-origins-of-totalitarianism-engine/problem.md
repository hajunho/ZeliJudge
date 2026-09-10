# #123 - 한나 아렌트의 전체주의의 기원: 반유대주의, 제국주의, 잉여 인간화 및 수용소 인격 파괴 엔진

## 📖 문제 배경과 역사적 맥락

> *"전체주의가 지배를 완성하기 위해 수용소에서 벌인 실험의 본질은, 인간을 단지 죽이는 것이 아니라 인간 내면의 자발성(Spontaneity)과 복수성(Plurality)을 완전히 소멸시켜 '움직이는 시체'이자 잉여물(Superfluous)로 변환하는 데 있었다."*  
> — **한나 아렌트 (Hannah Arendt, 1906–1975), 『전체주의의 기원』(The Origins of Totalitarianism, 1951)**

20세기 중반 나치즘과 스탈린주의라는 인류 역사상 유례없는 파국을 목격한 유대계 독일 철학자 **한나 아렌트(Hannah Arendt)**는 1951년 불후의 명작 **『전체주의의 기원(The Origins of Totalitarianism)』**을 발표했습니다. 아렌트는 전체주의가 전통적인 군주 독재, 군사 참칭 정권, 또는 통상적인 권위주의 독재(Authoritarian Dictatorship)와는 근본적으로 다른 **완전히 새로운 형태의 통치 형태(sui generis)**임을 논증했습니다.

전통적 독재가 반대파를 억압하면서도 시민들의 사적 영역을 부분적으로 남겨두는 반면, 전체주의는 국가와 사회, 공적 영역과 사적 영역의 구분을 완전히 분쇄하고, 대중을 끝없이 원자화(Atomization)·고독(Loneliness) 상태로 몰아넣으며 인간의 정신과 영혼까지 100% 지배하고자 합니다.

아렌트는 전체주의가 하늘에서 갑자기 떨어진 것이 아니라 서구 근대사 속 세 가지 독성 조류의 응집체임을 3부작에 걸쳐 해부했습니다:

```
                  ┌────────────────────────────────────────────────────────┐
                  │             한나 아렌트 『전체주의의 기원』 3단계 역학           │
                  └────────────────────────────────────────────────────────┘
                                            │
         ┌──────────────────────────────────┼──────────────────────────────────┐
         ▼                                  ▼                                  ▼
┌──────────────────┐               ┌──────────────────┐               ┌──────────────────┐
│ 제1부: 반유대주의  │               │  제2부: 제국주의  │               │ 제3부: 전체주의  │
│  (Anti-Semitism) │               │  (Imperialism)   │               │ (Totalitarianism)│
└────────┬─────────┘               └────────┬─────────┘               └────────┬─────────┘
         │                                  │                                  │
  국가 후원 유대인의                 "팽창이 전부다" (Rhodes)            계급 붕괴와 원자화된 대중
  기능 상실 및 동화 실패             잉여 자본과 잉여 인간의 수출        폭민과 엘리트의 냉소적 연대
  종교적 차별 -> 생물학적 인종 이데올로기  관료주의적 인종주의의 탄생          현실을 대체하는 무오류의 허구 논리
  국민국가 해체 속 희생양 전락       무국적 난민과 "권리를 가질 권리" 박탈   수용소: 3단계 인격 파괴 실험
         │                                  │                                  │
         └──────────────────────────────────┼──────────────────────────────────┘
                                            ▼
                  ┌────────────────────────────────────────────────────────┐
                  │  전체주의 지배 지표 (Totalitarian Domination Index: TDI) │
                  │     • 사적 영역의 완전 소멸, 영구 테러와 공포            │
                  │     • 법적 인격 -> 도덕적 인격 -> 자발성/개성 완전 파괴 │
                  │     • "인간은 잉여물이다(Humans are superfluous)" 완성  │
                  └────────────────────────────────────────────────────────┘
```

### 아렌트가 규명한 수용소의 3단계 인간성 파괴 실험
아렌트에 따르면 강제 수용소(Concentration & Extermination Camps)는 단순한 학살장이 아니라, **"모든 것이 가능한 세계"**를 입증하려는 전체주의 이데올로기의 궁극적 실험실이었습니다:
1. **법적 인격(Juridical Person)의 파괴**: 국적과 시민권을 박탈당한 무국적자(Stateless)로 만들어 어떤 법률과 사법 체계의 보호도 받지 못하는 법 외곽의 '회색 지대'로 격리.
2. **도덕적 인격(Moral Person)의 파괴**: 피해자에게 동료를 감시하고 학살 작업(존더코만도 등)에 가담하도록 강요하여, 양심과 도덕적 결단을 무의미하게 만들고 모두를 공범이자 죄인으로 타락시킴.
3. **개성과 자발성(Individuality & Spontaneity)의 파괴**: 끊임없는 육체적·정신적 고문과 극도의 영양실조, 규격화된 번호 낙인을 통해 인간을 예측 가능한 자극-반응 기계(Pavlovian reflex)로 퇴화시킴.

본 과제에서는 한나 아렌트의 정치철학 모델을 엄밀한 상태 전이 및 인구 동학 시뮬레이션 엔진으로 구현합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "totalitarian_threshold": 75.0,
    "initial_fiction": 15.0,
    "initial_alliance": 10.0
  },
  "groups": [
    {
      "id": "bourgeoisie",
      "name": "부르주아 시민계층",
      "population": 50000,
      "cohesion": 70.0,
      "isolation": 30.0,
      "juridical_rights": 100.0,
      "moral_integrity": 90.0,
      "spontaneity": 90.0
    },
    {
      "id": "minority_refugees",
      "name": "소수민족 및 무국적 난민",
      "population": 10000,
      "cohesion": 50.0,
      "isolation": 50.0,
      "juridical_rights": 50.0,
      "moral_integrity": 80.0,
      "spontaneity": 85.0
    }
  ],
  "events": [
    {
      "type": "ECONOMIC_CRISIS",
      "params": {
        "severity": 30.0
      }
    },
    {
      "type": "MOB_ELITE_PACT",
      "params": {
        "radicalism": 35.0
      }
    },
    {
      "type": "STATELESS_DENATIONALIZATION",
      "params": {
        "target_group": "minority_refugees"
      }
    },
    {
      "type": "IDEOLOGICAL_PROPAGANDA",
      "params": {
        "intensity": 30.0,
        "logical_consistency": 1.4
      }
    },
    {
      "type": "CAMP_DEPORTATION",
      "params": {
        "target_group": "minority_refugees",
        "count": 10000
      }
    },
    {
      "type": "TOTAL_TERROR_CYCLE",
      "params": {
        "severity": 50.0
      }
    }
  ]
}
```

### 파라미터 세부 규칙 및 기본값:
1. `config`:
   - `totalitarian_threshold` (기본값 `75.0`): $TDI$가 이 값 이상일 때 전체주의 지배 체제로 전이.
   - `initial_fiction` (기본값 `10.0`): 이데올로기적 허구 지수 $\Phi \in [0, 100]$.
   - `initial_alliance` (기본값 `10.0`): 폭민-엘리트 연대 지수 $\Omega \in [0, 100]$.
2. `groups`:
   - `id`: 고유 식별자 문자열.
   - `name`: 집단 명칭.
   - `population`: 집단 인구수 (양의 정수).
   - `cohesion`: 집단 내 연대감 및 시민적 유대 ($[0, 100]$, 기본값 `80.0`).
   - `isolation`: 고립도 및 원자화 지수 ($[0, 100]$, 기본값 `20.0`).
   - `juridical_rights`: 법적 권리 및 인격 보장 지수 ($[0, 100]$, 기본값 `100.0`).
   - `moral_integrity`: 도덕적 성실성 및 주체성 지수 ($[0, 100]$, 기본값 `100.0`).
   - `spontaneity`: 자발성 및 고유한 창조성 지수 ($[0, 100]$, 기본값 `100.0`).
   - 초기 집단 상태(`status`)는 모두 `"ACTIVE_CITIZEN"`이며 수용소 수감자수(`camp_count`)는 0입니다.
3. `events`: 다음 7가지 사건이 순서대로 발생합니다:
   - `ECONOMIC_CRISIS`:
     - 파라미터: `severity` ($S$).
     - 효과: `ACTIVE_CITIZEN` 집단의 `cohesion`은 $\max(0, \text{cohesion} - S \times 1.5)$, `isolation`은 $\min(100, \text{isolation} + S \times 1.2)$. 폭민-엘리트 연대 $\Omega$는 $\min(100, \Omega + S \times 0.8)$.
   - `IMPERIALIST_EXPANSION`:
     - 파라미터: `surplus_export` ($E$), `target_group` (선택).
     - 효과: 허구 지수 $\Phi$가 $\min(100, \Phi + E \times 0.7)$. 지정된 `target_group`이 존재하면, 해당 집단의 `juridical_rights`를 $\max(0, \text{rights} - E \times 1.8)$로 감소. 만약 감소 후 `juridical_rights` < 30.0이고 `status`가 `"ACTIVE_CITIZEN"`이면 상태를 `"SUPERFLUOUS_ALIEN"`으로 변경.
   - `MOB_ELITE_PACT`:
     - 파라미터: `radicalism` ($R$).
     - 효과: $\Omega = \min(100, \Omega + R)$, $\Phi = \min(100, \Phi + R \times 1.2)$. 모든 집단의 `moral_integrity`를 $\max(0, \text{moral} - R \times 0.5)$로 감소.
   - `STATELESS_DENATIONALIZATION`:
     - 파라미터: `target_group` ($G$).
     - 효과: 대상 집단의 `juridical_rights`를 즉시 `0.0`으로 박탈. 상태(`status`)를 `"SUPERFLUOUS_ALIEN"`으로 전환. `isolation`을 $\min(100, \text{isolation} + 30.0)$으로 증가.
   - `IDEOLOGICAL_PROPAGANDA`:
     - 파라미터: `intensity` ($I$), `logical_consistency` ($C$, 기본값 1.5).
     - 효과: $\Phi = \min(100, \Phi + I \times C)$. `"CORPSE_FABRICATED"`가 아닌 모든 집단에 대해:
       - `spontaneity` = $\max(0, \text{spontaneity} - I \times 0.8)$
       - `cohesion` = $\max(0, \text{cohesion} - I \times 0.6)$
       - `isolation` = $\min(100, \text{isolation} + I \times 0.7)$
   - `CAMP_DEPORTATION`:
     - 파라미터: `target_group` ($G$), `count` ($N$).
     - 효과: 대상 집단에서 $\min(N, \text{population} - \text{camp\_count})$만큼 수용소로 이송(`camp_count` 누적, 누적 총 이송 인구 `total_deported` 갱신). 이송된 인원이 1명 이상이면 해당 집단의 `status`는 `"CAMP_INTERNEE"`가 됨. 해당 집단의 `juridical_rights`는 `0.0`이 됨.
   - `TOTAL_TERROR_CYCLE`:
     - 파라미터: `severity` ($V$).
     - 효과:
       - `camp_count > 0`인 집단:
         - `moral_integrity` = $\max(0, \text{moral} - V \times 1.5)$
         - `spontaneity` = $\max(0, \text{spontaneity} - V \times 1.8)$
         - 3대 인격 파괴 조건 충족 검사: 만약 `juridical_rights == 0.0` 이고 `moral_integrity <= 10.0` 이고 `spontaneity <= 5.0` 이면, 집단의 `status`는 `"CORPSE_FABRICATED"`(움직이는 시체/생체 인형화)로 전이되며, 해당 집단의 `camp_count` 전원이 `total_fabricated` 누적 카운트에 합산됩니다 (중복 가산 방지: 이미 `"CORPSE_FABRICATED"`인 집단은 재가산하지 않음).
       - `camp_count == 0`인 집단:
         - `spontaneity` = $\max(0, \text{spontaneity} - V \times 0.4)$
         - `cohesion` = $\max(0, \text{cohesion} - V \times 0.5)$
         - `isolation` = $\min(100, \text{isolation} + V \times 0.6)$

### 지표 계산 공식 (각 사건 처리 직후):
1. **인구 가중 평균 고립도 및 자발성**:
   $$
   \bar{I} = \frac{\sum_{i} \text{isolation}_i \times \text{population}_i}{\sum_{i} \text{population}_i}, \quad
   \bar{S} = \frac{\sum_{i} \text{spontaneity}_i \times \text{population}_i}{\sum_{i} \text{population}_i}
   $$
2. **전체주의 지배 지표 ($TDI$)**:
   $$
   TDI = 0.30 \times \Phi + 0.25 \times \Omega + 0.25 \times \bar{I} + 0.20 \times (100.0 - \bar{S})
   $$
   (단, $TDI$는 $0.0 \sim 100.0$ 범위로 클램핑 후 소수점 둘째 자리로 반올림: `round(val, 2)`).
3. **체제 상태 (`regime_state`) 전이**:
   - $TDI \ge \text{totalitarian\_threshold} \implies$ `"TOTALITARIAN_RULE"`
   - $50.0 \le TDI < \text{totalitarian\_threshold} \implies$ `"DUAL_STATE"` (이중국가: 규범국가와 특권국가의 병존)
   - $30.0 \le TDI < 50.0 \implies$ `"MASS_MOBILIZATION"` (대중 동원기)
   - $TDI < 30.0 \implies$ `"PRE_TOTALITARIAN"` (전체주의 이전)

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 감사 결과를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력합니다:

```json
{
  "final_regime_state": "TOTALITARIAN_RULE",
  "final_tdi": 85.2,
  "is_totalitarian": true,
  "superfluous_population_ratio": 6.25,
  "total_deported": 10000,
  "total_fabricated": 10000,
  "group_status": {
    "bourgeoisie": {
      "name": "부르주아 시민계층",
      "status": "ACTIVE_CITIZEN",
      "cohesion": 0.0,
      "isolation": 100.0,
      "juridical_rights": 100.0,
      "moral_integrity": 72.5,
      "spontaneity": 46.0,
      "camp_internees": 0
    },
    "minority_refugees": {
      "name": "소수민족 및 무국적 난민",
      "status": "CORPSE_FABRICATED",
      "cohesion": 0.0,
      "isolation": 100.0,
      "juridical_rights": 0.0,
      "moral_integrity": 0.0,
      "spontaneity": 0.0,
      "camp_internees": 10000
    },
    "atomized_mass": {
      "name": "원자화된 실업 대중",
      "status": "ACTIVE_CITIZEN",
      "cohesion": 0.0,
      "isolation": 100.0,
      "juridical_rights": 100.0,
      "moral_integrity": 52.5,
      "spontaneity": 31.0,
      "camp_internees": 0
    }
  },
  "history": [
    {
      "epoch": 1,
      "event": "ECONOMIC_CRISIS",
      "tdi": 39.06,
      "regime_state": "MASS_MOBILIZATION",
      "ideological_fiction": 15.0,
      "mob_elite_alliance": 34.0
    }
  ]
}
```

*참고*: `superfluous_population_ratio`는 전체 인구 중 `status`가 `"SUPERFLUOUS_ALIEN"`, `"CAMP_INTERNEE"`, `"CORPSE_FABRICATED"`에 해당하는 인구의 백분율($\%$)이며 소수점 둘째 자리로 반올림(`round(..., 2)`)합니다.

---

## 🎯 채점 기준 및 제약 조건

1. 모든 부동소수점 수치는 Python 표준 `round(x, 2)`를 적용합니다.
2. 모든 이벤트는 순차적으로 상태를 변이시키며, 지표 및 이력 로그는 사건 순서대로 생성되어야 합니다.
3. 정확성(Correctness) 100%: 8개의 공개 및 히든 엣지케이스 테스트를 모두 통과해야 합니다.
