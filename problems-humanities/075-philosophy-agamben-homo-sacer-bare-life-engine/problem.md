# 조르조 아감벤의 호모 사케르(Homo Sacer)와 발가벗겨진 생명(Bare Life) 시뮬레이션 엔진

## 문제 설명

현대 정치철학자 **조르조 아감벤(Giorgio Agamben)**은 대표작 *《호모 사케르: 주권 권력과 발가벗겨진 생명(Homo Sacer: Il potere sovrano e la nuda vita, 1995)》*과 *《예외상태(Stato di eccezione, 2003)》*를 통해 현대 생명정치(Biopolitics)의 근원적 구조를 폭로했습니다.

고대 그리스인들은 생명을 두 가지로 엄격히 구분했습니다:
1. **조에(Zoē, ζωή)**: 모든 생명체(동물, 인간, 신)가 공유하는 단순한 생물학적 생존 그 자체.
2. **비오스(Bios, βίος)**: 폴리스(Polis)라는 공동체 안에서 법적·정치적 권리를 향유하는 시민으로서의 삶 (Bios Politikos).

아감벤은 서구 정치의 탄생이 법의 내부에 '조에'를 단순히 포섭한 것이 아니라, **주권적 밴(Sovereign Ban, 주권의 배제적 포섭)**을 통해 생물학적 생명을 법질서 바깥으로 추방하면서 동시에 그 추방을 통해 법의 주권을 확립하는 역설적 구조에 기초한다고 분석했습니다.

그 극한의 경계선에 서 있는 고대 로마법의 인물이 바로 **호모 사케르(Homo Sacer, 성스러운 인간 / 저주받은 인간)**입니다:
> *"살해해도 살인죄로 처벌받지 않으나, 신성한 제단에 제물로 바칠 수도 없는 자."*

호모 사케르는 모든 시민적 법 권리($Bios$)를 박탈당하여 오직 생물학적 생존($Zoar{e}$)만 남겨진 **'발가벗겨진 생명(Bare Life / Nuda Vita)'**입니다. 주권자가 비상사태나 안보 위기를 이유로 헌정 질서를 정지시키는 **예외상태(State of Exception)**가 일상화될 때, 이러한 예외는 법의 공백이 아니라 법이 스스로를 철회하면서 주권의 무제한적 폭력을 발가벗겨진 생명 위에 투사하는 **수용소(The Camp)**라는 공간을 탄생시킵니다. 아감벤은 수용소가 과거의 역사적 일탈이 아니라, **"현대성의 노모스(The Nomos of the Modern)"**이며 오늘날 난민 캠프, 공항 환승 구역, 구금 시설, 알고리즘적 계정 정지(Digital Bare Life)로 끝없이 변주된다고 경고합니다.

이에 맞서 아감벤은 주권적 법-생명 장치를 무력화하고 권력의 종속으로부터 삶을 해방시키는 **'무위성(Inoperativity / Inoperosità)'**과 법과 삶이 분리되지 않는 **'삶-형태(Form-of-Life / Forma-di-vita)'**를 제시합니다.

본 문제에서는 아감벤의 정치철학 이론을 모델링하여, 사회 주체들의 $Zoar{e}$와 $Bios$, 주권적 밴($SovereignBan$) 및 예외상태($StateOfException$)의 동역학을 계산하고, 호모 사케르 상태 판별과 수용소 지수($CampIndex$), 그리고 무위적 해방($InoperativeCommons$)의 과정을 시뮬레이션하는 엔진을 구현합니다.

---

## 철학적 아키텍처 및 수학적 공식

```
                     [ 주권자 Sovereign Power ]
                                │
              결정 (Decides on Exception: Carl Schmitt)
                                ▼
               ┌─────────────────────────────────┐
               │    예외상태 (State of Exception)   │
               │   법의 정지 & 주권적 밴 (Ban) 선언   │
               └────────────────┬────────────────┘
                                │
       배제적 포섭 (Exclusive Inclusion: 추방함으로써 지배함)
                                ▼
           ┌─────────────────────────────────────────┐
           │        호모 사케르 (Homo Sacer)          │
           │       발가벗겨진 생명 (Bare Life)         │
           │  - Zoē: 단순 생물학적 생존 (남겨짐)       │
           │  - Bios: 법적·정치적 시민권 (박탈됨)      │
           │  - Killable: 살해 가능 (처벌 없음)       │
           │  - Non-Sacrificable: 신성 제물 불가    │
           └────────────────────┬────────────────────┘
                                │
                    공간화 (Spatialization)
                                ▼
               ┌─────────────────────────────────┐
               │         수용소 (The Camp)        │
               │      현대성의 노모스 (Nomos)       │
               └────────────────┬────────────────┘
                                │
                      메시아적 탈-작동 (Deactivation)
                                ▼
               ┌─────────────────────────────────┐
               │      무위성 (Inoperativity)       │
               │    삶-형태 (Form-of-Life) 실현    │
               │   주권적 밴의 해체와 자유의 회복   │
               └─────────────────────────────────┘
```

### 1. 호모 사케르 지수 ($HomoSacerIndex$) 및 판별

각 주체 $i$는 생물학적 생존 수준 $Zoar{e}_i \in [0, 1]$와 시민적·법적 권리 $Bios_i \in [0, 1]$, 그리고 개별적 주권 밴 노출도 $BanExposure_i \in [0, 1]$를 갖습니다:
1. **유효 주권 밴 ($EffectiveBan_i$)**:
   $$	ext{EffectiveBan}_i = \min(1.0, \max(BanExposure_i, 	ext{sovereign\_ban}))$$
2. **호모 사케르 지수 ($HS_i$)**:
   $$HS_i = Zoar{e}_i 	imes (1.0 - Bios_i) 	imes 	ext{EffectiveBan}_i$$
   (계산 결과는 소수점 4자리로 반올림)
3. **호모 사케르 여부 및 법적 신분 판별**:
   - $HS_i \ge 0.60$ 일 때, 해당 주체는 **호모 사케르**로 전락합니다 (`is_homo_sacer = True`).
   - 호모 사케르인 경우:
     - `is_killable = True` (살해 가능: 법의 보호를 받지 못하므로 누구든 처벌 없이 처단 가능)
     - `is_sacrificable = False` (제물 불가: 법과 신성 양쪽 모두에서 배제됨)
   - 호모 사케르가 아닌 경우:
     - `is_killable = False`
     - `is_sacrificable = (Bios_i >= 0.50)` (시민적 권리가 0.50 이상인 정통 시민만 신성한 종교/국가적 의식의 주체/제물이 될 수 있음)

### 2. 수용소 지수 ($CampIndex$) 및 노모스 상태 ($NomosState$)

전체 주체의 호모 사케르 지수 평균과 현재 국가의 예외상태 수위로부터 수용소 공간의 제도화 정도를 산출합니다:
$$\overline{HS} = rac{1}{N}\sum_{i=1}^N HS_i$$
$$	ext{CampIndex} = 	ext{round}\Big(	ext{clamp}ig(	ext{state\_of\_exception} 	imes 0.5 + \overline{HS} 	imes 0.5, 0.0, 1.0ig), 4\Big)$$

수용소 지수에 따른 통치 체제($NomosState$)는 다음과 같이 전이됩니다:
- $	ext{CampIndex} \ge 0.65$: `"THE_CAMP_PERMANENT_EXCEPTION"` (수용소화된 영구적 예외상태)
- $0.35 \le 	ext{CampIndex} < 0.65$: `"HYBRID_BIO_SECURITY_ZONE"` (생체 보안 및 감시 통제 지대)
- $	ext{CampIndex} < 0.35$: `"CONSTITUTIONAL_RULE_OF_LAW"` (입헌주의적 법치주의)

### 3. 통치 및 해방 명령 (Commands)

1. `DECLARE_EXCEPTION` (`intensity`):
   - 주권자가 헌정 질서 중단을 선포하여 예외상태를 심화시킵니다:
     $$	ext{state\_of\_exception} \leftarrow \min(1.0, 	ext{state\_of\_exception} + 	ext{intensity})$$
     $$	ext{sovereign\_ban} \leftarrow \min(1.0, 	ext{sovereign\_ban} + 	ext{intensity} 	imes 0.8)$$
   - 모든 주체의 시민권($Bios$)이 침식됩니다:
     $$orall i, \; Bios_i \leftarrow \max(0.0, Bios_i - 	ext{intensity} 	imes 0.3)$$
2. `IMPOSE_BAN` (`subject_id`, `ban_level`):
   - 특정 주체를 지정하여 주권적 밴을 가하고 사회 밖으로 추방합니다:
     $$BanExposure_i \leftarrow \min(1.0, BanExposure_i + 	ext{ban\_level})$$
     $$Bios_i \leftarrow \max(0.0, Bios_i - 	ext{ban\_level} 	imes 0.7)$$
3. `STRIP_RIGHTS` (`subject_id`, `bios_reduction`):
   - 특정 주체의 법적·시민적 권리($Bios$)를 직접 삭감합니다:
     $$Bios_i \leftarrow \max(0.0, Bios_i - 	ext{bios\_reduction})$$
4. `INOPERATIVE_COMMONS` (`emancipation_effort`):
   - 삶을 법의 종속으로부터 해방시키는 아감벤의 무위성(Inoperativity) 및 삶-형태(Form-of-Life) 실천:
     $$	ext{form\_of\_life\_index} \leftarrow \min(1.0, 	ext{form\_of\_life\_index} + 	ext{effort})$$
     $$	ext{sovereign\_ban} \leftarrow \max(0.0, 	ext{sovereign\_ban} - 	ext{effort} 	imes 0.7)$$
     $$	ext{state\_of\_exception} \leftarrow \max(0.0, 	ext{state\_of\_exception} - 	ext{effort} 	imes 0.6)$$
   - 모든 주체의 밴 노출이 해제되고 삶의 존엄($Bios$)이 회복됩니다:
     $$orall i, \; BanExposure_i \leftarrow \max(0.0, BanExposure_i - 	ext{effort})$$
     $$orall i, \; Bios_i \leftarrow \min(1.0, Bios_i + 	ext{effort} 	imes 0.5)$$
5. `STEP`:
   - 시뮬레이션의 스텝 카운터를 1 증가시키고 상태를 재평가합니다.
6. `QUERY_HOMO_SACER`:
   - 현재 시점의 `step`, `camp_index`, `nomos_state`, `homo_sacer_count`, 그리고 주체들의 상태 딕셔너리(`subjects`)를 `query_logs`에 스냅샷으로 기록합니다. (주체 딕셔너리의 키는 `subject_id` 오름차순 정렬)

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "state_of_exception": 0.20,
    "sovereign_ban": 0.30,
    "subjects": [
      {
        "subject_id": "citizen_local",
        "name": "Naturalized Native",
        "category": "citizen",
        "zoe": 1.0,
        "bios": 0.90
      },
      {
        "subject_id": "refugee_unregistered",
        "name": "Stateless Border Crosser",
        "category": "refugee",
        "zoe": 1.0,
        "bios": 0.20
      }
    ]
  },
  "commands": [
    {"type": "IMPOSE_BAN", "subject_id": "refugee_unregistered", "ban_level": 0.80},
    {"type": "QUERY_HOMO_SACER"},
    {"type": "STEP"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 한 줄로 출력합니다:
```json
{"total_steps":1,"state_of_exception":0.2,"sovereign_ban":0.3,"camp_index":0.37,"nomos_state":"HYBRID_BIO_SECURITY_ZONE","form_of_life_index":0.0,"homo_sacer_count":1,"subjects":{"citizen_local":{"subject_id":"citizen_local","name":"Naturalized Native","category":"citizen","zoe":1.0,"bios":0.9,"homo_sacer_index":0.03,"is_homo_sacer":false,"is_killable":false,"is_sacrificable":true},"refugee_unregistered":{"subject_id":"refugee_unregistered","name":"Stateless Border Crosser","category":"refugee","zoe":1.0,"bios":0.0,"homo_sacer_index":0.8,"is_homo_sacer":true,"is_killable":true,"is_sacrificable":false}},"query_logs":[{"step":0,"camp_index":0.37,"nomos_state":"HYBRID_BIO_SECURITY_ZONE","homo_sacer_count":1,"subjects":{"citizen_local":{"subject_id":"citizen_local","name":"Naturalized Native","category":"citizen","zoe":1.0,"bios":0.9,"homo_sacer_index":0.03,"is_homo_sacer":false,"is_killable":false,"is_sacrificable":true},"refugee_unregistered":{"subject_id":"refugee_unregistered","name":"Stateless Border Crosser","category":"refugee","zoe":1.0,"bios":0.0,"homo_sacer_index":0.8,"is_homo_sacer":true,"is_killable":true,"is_sacrificable":false}}}]}
```
