# #125 - 니콜로 마키아벨리의 군주론: 비르투(Virtù), 포르투나(Fortuna), 사자와 여우의 통치술 및 권력 유지 엔진

## 📖 문제 배경과 역사적 맥락

> *"운명(Fortuna)은 우리의 행동 중 절반을 지배하지만, 나머지 절반 혹은 그에 준하는 부분은 우리 자신의 역량인 비르투(Virtù)에 맡겨져 있다. 포르투나는 제방과 둑이 없는 곳에서 사납게 날뛰는 강물과 같아서, 현명한 군주는 평화로울 때 제방을 쌓아 격류를 다스려야 한다."*  
> — **니콜로 마키아벨리 (Niccolò Machiavelli, 1469–1527), 『군주론』(Il Principe, 1532)**

16세기 이탈리아 르네상스 시기, 교황령과 외세(프랑스, 스페인, 신성로마제국)의 침탈로 산산조각 난 조국 피렌체를 지켜보던 외교관이자 정치사상가 **니콜로 마키아벨리(Niccolò Machiavelli)**는 서양 정치사상사의 판도를 영구히 바꾼 걸작 **『군주론(Il Principe)』**을 집필했습니다.

마키아벨리는 플라톤, 키케로, 중세 기독교 신학이 주창하던 "군주는 자비롭고 도덕적이어야 하며 신의 뜻에 따라야 한다"는 공허한 이상주의를 단호히 거부했습니다. 그는 **"현실에서 일어나는 일과 마땅히 일어나야 하는 일 사이에는 거대한 간극이 존재하며, 모든 상황에서 선하기만을 바라는 자는 악한 자들 틈에서 파멸할 수밖에 없다"**고 선언하며, 정치와 도덕을 분리하고 국가의 존속과 시민의 안위를 최우선으로 삼는 근대 현실주의 정치학(Raison d'État)을 정초했습니다.

```
       ┌────────────────────────────────────────────────────────┐
       │             마키아벨리 『군주론』의 4대 통치 원리           │
       └────────────────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ 1. 비르투와 포르투나│      │ 2. 사자와 여우의 비유│      │ 3. 두려움 vs 사랑   │
│ (Virtù & Fortuna)│      │  (Lion and Fox)  │      │ (Feared vs Loved)│
└────────┬─────────┘      └────────┬─────────┘      └────────┬─────────┘
         │                         │                         │
  운명의 강물(50%) 대       사자의 무력(늑대 퇴치)    사랑은 배신당하기 쉬우나
  군주의 결단·제방(50%)      여우의 간계(덫 간파)      처벌의 공포는 영원하다
  포르투나를 제압하는 용기   외양과 위장의 예술         "두려움의 대상이 되되,
                                                       증오(Hatred)는 피하라"
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   ▼
                  ┌──────────────────────────────────┐
                  │ 4. 군사적 자립: 자국민 군대(Militia)│
                  │  - 비열한 용병(Mercenary) 배격    │
                  │  - 위험한 외세 보조군(Auxiliary) 배제│
                  │  - 무장한 예언자만이 승리한다     │
                  └──────────────────────────────────┘
```

### 마키아벨리 통치학의 핵심 공리
1. **포르투나(Fortuna)와 비르투(Virtù)**:
   - 포르투나는 예측 불가능한 기회이자 재앙입니다. 비르투는 기회가 왔을 때 단호하게 낚아채고, 재앙이 닥치기 전에 사전 방벽(안정도, 군사력, 정보망)을 구축하여 위기를 극복하는 군주의 탁월한 역량입니다.
2. **사자의 힘과 여우의 간계**:
   - 군주는 법률이라는 인간의 방식뿐만 아니라 짐승의 방식을 모방해야 합니다. 힘만 쓰는 사자는 덫에 걸려 죽고, 꾀만 쓰는 여우는 늑대에게 물려 죽습니다.
3. **사랑받기보다 두려움의 대상이 되라 (Loved vs Feared)**:
   - 사랑은 필요할 때만 복종하는 이기적인 계약이지만, 처벌에 대한 두려움(Fear)은 항상 효력을 발휘합니다.
   - 단, 군주는 결코 **증오(Hatred)**를 사서는 안 됩니다. 시민의 재산(Patrimony)과 부녀자를 건드리지 않는 한, 군주는 두려움의 대상이 되면서도 인민의 지지를 유지할 수 있습니다.
4. **잔혹함의 올바른 사용 (Cruelty well used)**:
   - 체사레 보르자처럼, 권력을 장악할 때 필요한 잔혹한 조치는 단번에 끝내고(한 번에 마시고 매일 반복하지 말 것), 은혜는 조금씩 천천히 베풀어야 합니다.

본 과제에서는 마키아벨리의 권력 동학 상태 머신을 구현하여 군주국의 흥망과 최적 통치 태세를 시뮬레이션합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "virtu": 80.0,
    "lion_prowess": 85.0,
    "fox_cunning": 80.0
  },
  "initial_state": {
    "stability": 50.0,
    "affection": 40.0,
    "fear": 30.0,
    "hatred": 15.0,
    "treasury": 800,
    "military_type": "MERCENARY"
  },
  "events": [
    {
      "type": "REFORM_MILITARY",
      "params": {
        "target_type": "CITIZEN_MILITIA",
        "cost": 300
      }
    },
    {
      "type": "CRUELTY_EXECUTION",
      "params": {
        "severity": 30.0,
        "single_stroke": true,
        "confiscate_patrimony": false
      }
    },
    {
      "type": "EXERCISE_LION",
      "params": {
        "intensity": 40.0,
        "threat": 35.0
      }
    },
    {
      "type": "DISBURSE_FAVORS",
      "params": {
        "amount": 200,
        "distribution": "GRADUAL"
      }
    },
    {
      "type": "FORTUNA_TEMPEST",
      "params": {
        "magnitude": 45.0
      }
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `config`:
   - `virtu`: 군주의 고유 역량 및 결단력 ($[0, 100]$, 기본값 `70.0`).
   - `lion_prowess`: 사자의 물리적 무력 및 군사 지휘력 ($[0, 100]$, 기본값 `70.0`).
   - `fox_cunning`: 여우의 모략, 간계 및 외교력 ($[0, 100]$, 기본값 `70.0`).
2. `initial_state`:
   - `stability`: 국가 안정도 ($[0, 100]$, 기본값 `50.0`).
   - `affection`: 인민의 호의 및 사랑 ($[0, 100]$, 기본값 `50.0`).
   - `fear`: 인민 및 귀족의 경외·공포심 ($[0, 100]$, 기본값 `50.0`).
   - `hatred`: 인민의 원한 및 증오심 ($[0, 100]$, 기본값 `10.0`).
   - `treasury`: 국고 (정수, 기본값 `1000`).
   - `military_type`: 군대 유형 (`"MERCENARY"`, `"AUXILIARY"`, `"CITIZEN_MILITIA"`).
3. `events`: 다음 6가지 사건이 순서대로 발생합니다:
   - `FORTUNA_TEMPEST`:
     - 파라미터: `magnitude` ($M$).
     - 효과: 제방 저항력 $\text{Dam} = 0.40 \times \text{stability} + 0.40 \times \text{virtu} + 0.20 \times \text{fox}$. 순 피해량 $\text{Dmg} = \max(0.0, M - \text{Dam} \times 0.5)$.
     - 용병 배신 페널티: `military_type == "MERCENARY"`이고 $\text{Dmg} > 15.0$이면 $\text{Dmg} \times= 1.5$, $\text{treasury} = \max(0, \text{treasury} - 300)$, $\text{fear} = \max(0, \text{fear} - 20.0)$.
     - 보조군 잠식: `military_type == "AUXILIARY"`이고 $\text{Dmg} > 20.0$이면 $\text{stability} = \max(0, \text{stability} - 30.0)$.
     - $\text{stability} = \max(0, \text{stability} - \text{Dmg})$, $\text{affection} = \max(0, \text{affection} - \text{Dmg} \times 0.3)$.
   - `EXERCISE_LION`:
     - 파라미터: `intensity` ($I$), `threat` ($T$).
     - 효과: 군대 승수 $M_{\text{mil}} = 1.2$ (`CITIZEN_MILITIA`), $0.8$ (`MERCENARY`), $0.9$ (`AUXILIARY`). 유효 무력 $F_{\text{eff}} = (\text{lion} \times 0.6 + I \times 0.4) \times M_{\text{mil}}$.
     - 만약 $F_{\text{eff}} \ge T$: 위협 진압 성공 $\implies \text{stability} = \min(100, \text{stability} + 15.0)$, $\text{fear} = \min(100, \text{fear} + I \times 0.6)$.
     - 실패 시: $\text{stability} = \max(0, \text{stability} - 15.0)$, $\text{fear} = \max(0, \text{fear} - 10.0)$.
   - `EXERCISE_FOX`:
     - 파라미터: `cunning` ($C$), `trap_difficulty` ($D$).
     - 효과: 유효 간계 $K_{\text{eff}} = \text{fox} \times 0.6 + C \times 0.4$.
     - 만약 $K_{\text{eff}} \ge D$: 덫 간파 및 정적 무력화 $\implies \text{stability} = \min(100, \text{stability} + 10.0)$, $\text{fear} = \min(100, \text{fear} + 5.0)$, $\text{affection} = \min(100, \text{affection} + 5.0)$.
     - 실패 시: 위선 탄로 $\implies \text{hatred} = \min(100, \text{hatred} + 20.0)$, $\text{affection} = \max(0, \text{affection} - 15.0)$.
   - `CRUELTY_EXECUTION`:
     - 파라미터: `severity` ($S$), `single_stroke` (불리언), `confiscate_patrimony` (불리언).
     - 효과:
       - `single_stroke == true` (올바른 잔혹함): $\text{fear} = \min(100, \text{fear} + S \times 0.8)$, $\text{stability} = \min(100, \text{stability} + S \times 0.4)$. 재산 몰수(`confiscate_patrimony`) 시 $\text{hatred} = \min(100, \text{hatred} + S \times 0.8)$, 미몰수 시 $\text{hatred} = \min(100, \text{hatred} + S \times 0.2)$.
       - `single_stroke == false` (잘못된 잔혹함: 만성적 숙청): $\text{fear} = \min(100, \text{fear} + S \times 0.4)$, $\text{hatred} = \min(100, \text{hatred} + S \times 1.2)$, $\text{stability} = \max(0, \text{stability} - 20.0)$.
   - `DISBURSE_FAVORS`:
     - 파라미터: `amount` ($A$), `distribution` (`"GRADUAL"` vs `"SQUANDER_AT_ONCE"`).
     - 효과: 실제 지출 $E = \min(A, \text{treasury})$. $\text{treasury} -= E$.
       - `"GRADUAL"` (점진적 은혜): $\text{affection} = \min(100, \text{affection} + E / 10.0)$, $\text{hatred} = \max(0, \text{hatred} - 10.0)$, $\text{stability} = \min(100, \text{stability} + 10.0)$.
       - `"SQUANDER_AT_ONCE"` (일시적 낭비): $\text{affection} = \min(100, \text{affection} + 10.0)$, $\text{hatred} = \min(100, \text{hatred} + 15.0)$.
   - `REFORM_MILITARY`:
     - 파라미터: `target_type`, `cost`.
     - 효과: $\text{treasury} \ge \text{cost}$이면 $\text{treasury} -= \text{cost}$, $\text{military_type} = \text{target\_type}$, $\text{stability} = \min(100, \text{stability} + 20.0)$, $\text{virtu} = \min(100, \text{virtu} + 10.0)$.

### 반란 및 통치 태세(`posture`) 판정:
1. 매 사건 처리 직후:
   - 만약 $\text{hatred} \ge 70.0$이면: 반란 발생(`rebellion_occurred = true`), $\text{stability} = \max(0, \text{stability} - 40.0)$.
   - 만약 $\text{stability} \le 10.0$ 또는 $\text{hatred} \ge 90.0$이면: 군주 실각(`deposed = true`).
2. 통치 태세(`posture`):
   - `deposed == true` $\implies$ `"DEPOSED_RUINED"`
   - `hatred >= 70.0` $\implies$ `"TYRANNICAL_REBELLION"`
   - `fear >= 50.0 and hatred < 50.0` $\implies$ `"PRUDENT_FEARED_RULER"` (마키아벨리적 최적 상태: 두려움의 대상이 되되 증오받지 않음)
   - `affection >= 60.0 and fear < 30.0` $\implies$ `"NAIVE_VULNERABLE_LOVED"` (순진하고 취약한 사랑받는 군주)
   - 그 외 $\implies$ `"BALANCED_PRAGMATIC"`

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 군주국 상태를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력합니다:

```json
{
  "final_posture": "PRUDENT_FEARED_RULER",
  "final_stability": 100.0,
  "is_machiavellian_optimum": true,
  "rebellion_occurred": false,
  "deposed": false,
  "state": {
    "stability": 100.0,
    "affection": 60.0,
    "fear": 78.0,
    "hatred": 11.0,
    "treasury": 300,
    "military_type": "CITIZEN_MILITIA"
  },
  "history": [
    {
      "epoch": 1,
      "event": "REFORM_MILITARY",
      "stability": 70.0,
      "fear": 30.0,
      "hatred": 15.0,
      "affection": 40.0,
      "treasury": 500,
      "military_type": "CITIZEN_MILITIA",
      "posture": "BALANCED_PRAGMATIC"
    }
  ]
}
```

*참고*: 부동소수점 수치는 `round(val, 2)`를 적용합니다.

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 통치 태세 플래그가 완벽히 일치해야 합니다.
2. 마키아벨리안 최적 상태 조건(`fear >= 50.0 and hatred < 50.0 and not deposed`)을 정확히 판별해야 합니다.
