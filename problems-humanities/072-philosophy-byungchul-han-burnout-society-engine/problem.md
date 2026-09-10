# 한병철의 피로사회: 성과주체, 긍정성의 과잉 및 자발적 자기착취 엔진 (Byung-Chul Han The Burnout Society & Auto-Exploitation Engine)

## 문제 설명

재독 철학자 **한병철(Byung-Chul Han)**은 2010년 저서 **『피로사회(Müdigkeitsgesellschaft)』**를 통해 21세기 후기 현대 사회의 질병과 인간 소외의 근본 원인을 해부하여 전 세계적인 지적 반향을 일으켰습니다.

푸코가 분석했던 과거의 **규율사회(Disciplinary Society)**는 병원, 감옥, 공장, 군대처럼 "너는 ~해서는 안 된다(금지와 통제)"라는 부정성(Negativity)의 사회였습니다. 그러나 오늘날의 사회는 피트니스 클럽, 오피스 빌딩, 스타트업 연구소처럼 **"Yes, We Can!(너는 무엇이든 할 수 있다)"**는 구호가 지배하는 **성과사회(Achievement Society)**로 변모하였습니다.

성과사회에서 인간은 더 이상 복종하는 '순종적 주체'가 아니라, 자기 자신을 스스로 경영하고 최적화하는 **성과주체(Leistungssubjekt)**가 됩니다:

```
        [ The Transition: Disciplinary Society to Burnout Society ]
   +----------------------------------------------------------------+
   | Disciplinary Society (규율사회): "Thou Shalt Not" (외부 강제/부정성) |
   +----------------------------------------------------------------+
                                  |  Historical Paradigm Shift
                                  v
   +----------------------------------------------------------------+
   | Achievement Society (성과사회): "Yes, We Can!" (내면 강박/긍정성 과잉)|
   | Auto-Exploitation (자발적 자기착취): Exploiter == Exploited     |
   +----------------------------------------------------------------+
                                  |
                                  v
   +----------------------------------------------------------------+
   | Hyperactivity (과잉행동) & Multitasking (분산된 주의력의 퇴행)  |
   | Neuronal Violence (신경성 폭력): Depression, ADHD, Burnout      |
   +----------------------------------------------------------------+
                 |                                  ^
                 v                                  |
   [ DEPRESSIVE BURNOUT ]          [ VITA CONTEMPLATIVA (사색적 삶) ]
   Collapse from war against self  Deep Boredom (깊은 심심함), Rest
   Free but exhausted into death   Healing stillness & Inactivity
```

성과사회의 가장 역설적인 비극은 **자발적 자기착취(Auto-Exploitation)**입니다. 외적 지배자(Master)가 존재하지 않으므로, 인간은 자신이 '자유롭다'는 착각 속에서 스스로를 죽음에 이를 때까지 무자비하게 착취합니다. 외부의 적이 없기 때문에 저항이나 혁명도 불가능하며, 실패의 모든 책임을 자기 자신에게 돌린 끝에 필연적으로 **우울증(Depression)**과 **번아웃(Burnout)**에 직면하게 됩니다.

본 문제에서는 성과 압박, 자발적 자기착취율, 멀티태스킹 과잉활동, 그리고 이에 저항하는 사색적 삶(Vita Contemplativa)과 깊은 심심함(Deep Boredom)의 상호작용을 통해 **번아웃 지수($B$)** 및 실존적 심리 체제 전이를 정량 시뮬레이션하는 엔진을 구현합니다.

---

## 핵심 메커니즘 및 수리 모델

### 1. 실존 공간의 4대 상태 변수
모든 상태 변수는 $[0.0, 1.0]$ 범위의 실수로 표현됩니다:
- `achievement_pressure` ($A$): "더 잘할 수 있다"는 내면화된 성과 강박.
- `auto_exploitation` ($E$): 스스로를 채찍질하는 자발적 자기착취율.
- `hyperactivity` ($H$): 멀티태스킹, 숏폼 피드, 끊임없는 알림에 의한 주의력 분산도.
- `vita_contemplativa` ($V$): 깊은 심심함, 사색적 멈춤, 비활동성(Inactivity)의 시간.

### 2. 번아웃 지수 (Burnout Index, $B$)
신경성 피로와 자기 소진의 수준을 정량화합니다. 분모의 사색적 삶($V$)은 신경성 폭력을 완충하는 실존적 방패로 작용합니다:

$$B = 	ext{round}\left(\min\left(1.0, \max\left(0.0, rac{A 	imes 0.35 + E 	imes 0.40 + H 	imes 0.25}{1.0 + 0.8 	imes V}ight)ight), 4ight)$$

### 3. 3대 실존적 심리 체제 (Regime Classification)
- $B \ge 0.75$: **`DEPRESSIVE_BURNOUT`** (우울증적 소진: 자기 자신과의 전쟁에서 탈진하여 영혼과 신체가 마비된 상태)
- $0.45 \le B < 0.75$: **`HYPERACTIVE_ACHIEVEMENT`** (과잉행동적 성과주의: 긍정성의 과잉 속에서 피로를 안고 질주하는 상태)
- $B < 0.45$: **`SERENE_CONTEMPLATION`** (사색적 평정: 깊은 심심함과 멈춤 속에서 고유한 창조적 안식을 누리는 상태)

### 4. 연산별 상태 전이 규칙

1. **성과 프로젝트 수행 (`ENGAGE_ACHIEVEMENT_PROJECT`)**:
   - 입력: `project_name`, `intensity` ($i$), `self_optimization_drive` ($d$)
   - 성과 강박, 자기착취 및 과잉행동 증폭:
     $$A = 	ext{round}(\min(1.0, A + i 	imes 0.12), 4)$$
     $$E = 	ext{round}(\min(1.0, E + i 	imes 0.15 + d 	imes 0.10), 4)$$
     $$H = 	ext{round}(\min(1.0, H + i 	imes 0.08), 4)$$
     $$V = 	ext{round}(\max(0.0, V - i 	imes 0.10), 4)$$

2. **과잉 멀티태스킹 유발 (`TRIGGER_HYPER_MULTITASKING`)**:
   - 입력: `task_count` ($k$), `notification_density` ($n$)
   - 산만한 주의력 분산과 뇌 피로도 폭증:
     $$H = 	ext{round}(\min(1.0, H + \min(0.35, k 	imes 0.04 + n 	imes 0.15)), 4)$$
     $$E = 	ext{round}(\min(1.0, E + n 	imes 0.08), 4)$$
     $$V = 	ext{round}(\max(0.0, V - 0.08), 4)$$

3. **깊은 심심함 훈련 (`PRACTICE_DEEP_BOREDOM`)**:
   - 입력: `duration_hours` ($h$), `digital_detox` (bool, 참일 시 가중치 1.4 적용)
   - 아무것도 하지 않는 비활동성(Das Nicht-Tun)을 통해 영혼의 이완 회복:
     $$V = 	ext{round}(\min(1.0, V + \min(0.5, h 	imes 0.08 	imes 	ext{detox\_factor})), 4)$$
     $$H = 	ext{round}(\max(0.0, H - h 	imes 0.10 	imes 	ext{detox\_factor}), 4)$$
     $$A = 	ext{round}(\max(0.0, A - h 	imes 0.05), 4)$$

4. **사색적 삶 회복 (`EMBRACE_VITA_CONTEMPLATIVA`)**:
   - 입력: `meditation_depth` ($m$)
   - 활동적 삶(Vita Activa)의 맹목적 광기를 멈추고 관조적 사유를 회복:
     $$V = 	ext{round}(\min(1.0, V + m 	imes 0.25), 4)$$
     $$E = 	ext{round}(\max(0.0, E - m 	imes 0.20), 4)$$
     $$A = 	ext{round}(\max(0.0, A - m 	imes 0.15), 4)$$

5. **상태 조회 (`GET_STATE`)**:
   - 현재 4대 변수, 번아웃 지수($B$) 및 실존 체제를 반환합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "initial_achievement_pressure": 0.45,
    "initial_auto_exploitation": 0.35,
    "initial_hyperactivity": 0.35,
    "initial_vita_contemplativa": 0.4
  },
  "operations": [
    {"op": "GET_STATE"},
    {"op": "ENGAGE_ACHIEVEMENT_PROJECT", "project_name": "Quarterly OKR 200% Hyper-Growth", "intensity": 0.8, "self_optimization_drive": 0.75},
    {"op": "TRIGGER_HYPER_MULTITASKING", "task_count": 8, "notification_density": 0.85},
    {"op": "PRACTICE_DEEP_BOREDOM", "duration_hours": 3.0, "digital_detox": true},
    {"op": "EMBRACE_VITA_CONTEMPLATIVA", "meditation_depth": 0.9},
    {"op": "GET_STATE"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과와 최종 누적 통계를 담은 JSON을 출력합니다:

```json
{
  "results": [
    {
      "op": "GET_STATE",
      "achievement_pressure": 0.45,
      "auto_exploitation": 0.35,
      "hyperactivity": 0.35,
      "vita_contemplativa": 0.4,
      "burnout_index": 0.2917,
      "regime": "SERENE_CONTEMPLATION"
    }
  ],
  "final_summary": {
    "achievement_pressure": 0.273,
    "auto_exploitation": 0.507,
    "hyperactivity": 0.262,
    "vita_contemplativa": 0.803,
    "burnout_index": 0.2215,
    "regime": "SERENE_CONTEMPLATION",
    "stats": {
      "projects_engaged": 1,
      "multitasking_events": 1,
      "boredom_practices": 1,
      "contemplation_sessions": 1,
      "max_burnout_index": 0.6278,
      "burnout_epochs": 0
    },
    "event_count": 6
  }
}
```
