# 문제 #032: 대통령이 거부권을 행사한 법안을 국회가 뒤집을 수 있을까요?!: 입헌주의와 권력분립(Constitutional Law & Separation of Powers): 몽테스키외 삼권분립, 양원제 의회 통과·필리버스터 종결, 대통령 거부권 및 2/3 재의결, 위헌법률심사(Judicial Review) 상태 머신 엔진

## 1. 개요 (Story & Context)
1748년 프랑스의 계몽주의 사상가 샤를 드 몽테스키외(Charles de Montesquieu)는 저서 《법의 정신(*De l'esprit des lois*)》에서 영구적인 자유를 보장하기 위해 국가 권력을 입법(Legislative), 행정(Executive), 사법(Judicial)의 3부로 분리해야 한다는 **삼권분립(Trias Politica)** 원리를 주창했습니다.
이어 1787년 미국 헌법을 기초한 '건국의 아버지' 제임스 매디슨(James Madison)은 《연방주의자 논집 제51편(*Federalist No. 51*)》에서 인간 본성의 불완전함을 꿰뚫어 보며 다음과 같은 불멸의 통찰을 남겼습니다:

> *"만약 인간이 천사라면 국가 정부는 필요 없을 것이다. 만약 천사가 인간을 다스린다면 정부에 대한 내외부의 통제도 필요 없을 것이다... 따라서 야망은 야망에 맞서도록 만들어져야 한다(Ambition must be made to counteract ambition)."*

근대 입헌 민주주의 헌법 체계는 단순히 권력을 세 갈래로 나누는 데 그치지 않고, 각 부가 다른 부의 독주를 합법적으로 저지할 수 있는 정교한 **‘견제와 균형(Checks and Balances)의 동적 상태 머신’**을 설계했습니다:
1. **양원제 입법부(Bicameral Legislature)와 필리버스터(Filibuster)**:
   - 법안이 성립하려면 하원(House)과 상원(Senate) 양원의 단순 과반수 찬성을 모두 획득해야 합니다.
   - 특히 상원에서는 소수파가 합법적 의사진행방해(Filibuster)를 발동할 수 있으며, 이를 종결(Cloture)시키려면 재적 의원 3/5(60%) 이상의 특별 정족수를 확보해야 합니다.
2. **행정부의 법률안 거부권(Presidential Veto)**:
   - 의회를 통과한 법안은 국가원수(대통령)에게 송부됩니다. 대통령은 서명(`SIGN`)하여 공포하거나, 이의서를 첨부하여 의회로 환부 거부(`VETO`)할 수 있습니다.
   - 의회가 폐회되어 10일 이내에 법안을 반환할 수 없는 경우, 대통령이 서명하지 않고 방치함으로써 법안을 자동 폐기시키는 보류 거부(`POCKET_VETO`)도 존재합니다.
3. **입법부의 재의결(Legislative Veto Override)**:
   - 대통령이 거부권을 행사하더라도 의회는 굴복하지 않고 재의(Reconsideration)에 부칠 수 있습니다.
   - 이때 하원과 상원 양원에서 각각 출석/재적 **3분의 2($2/3$, 66.67%) 이상의 압도적 특별다수(Supermajority)** 찬성을 얻어내면, 대통령의 서명 없이도 법안은 최종 법률로 강제 발효됩니다 (`ENACTED_BY_VETO_OVERRIDE`)!
4. **사법부의 위헌법률심사(Judicial Review & Severability Doctrine)**:
   - 1803년 존 마셜(John Marshall) 대법관의 역사적인 '마버리 대 매디슨(Marbury v. Madison)' 판결 이후, 사법부는 의회가 통과시키고 대통령이 서명한 법률이라도 헌법의 최고 규범성에 위배될 경우 무효화할 수 있는 **사법심사권(Judicial Review)**을 가집니다.
   - 헌법재판소/연방대법원은 법률의 조항별로 위헌 여부를 투표(예: 9인 재판관 중 6인 이상 위헌 정족수)합니다.
   - 이때 **가분성 원칙(Severability Doctrine)**에 따라:
     - 위헌 조항이 비본질적(Non-essential) 부속 조항인 경우, 해당 조항만 잘라내어 무효화하고 나머지 조항은 유효하게 존속(`PARTIALLY_UPHELD_SEVERED`)시킵니다.
     - 그러나 위헌 조항이 법률의 핵심 목적을 담은 본질적(Essential) 조항이거나 법률의 모든 조항이 위헌 판정을 받은 경우, 법률 전체가 무효로 선언되어 효력을 상실(`STRUCK_DOWN_ENTIRELY`)합니다!

여러분은 헌법학 및 리걸테크(LegalTech) 입법 거버넌스 수석 엔지니어로서, 민주주의 3권 간의 견제와 균형 수명 주기를 시뮬레이션하는 **Constitutional Law & Separation of Powers Engine**을 완벽히 구축해야 합니다!

---

## 2. 상태 머신 및 연산 규칙

### 2.1 헌법 기관 및 정족수 설정 (`court_config`)
- `justice_count`: 사법부(헌법재판소/대법원) 총 재판관 수 (기본 9명).
- `unconstitutional_threshold`: 조항 위헌 결정을 위한 최소 찬성표 수 (기본 6표, $6/9$).

### 2.2 법안 상태 머신 전이
1. `INTRODUCE_BILL`:
   - 법안 식별자 `bill_id`, 명칭 `title`, 조항 목록 `articles` (`id`, `title`, `essential` 불리언)을 등록합니다.
   - 법안 초기 상태: `INTRODUCED`.
2. `LEGISLATIVE_VOTE`:
   - **하원 투표 (`house_vote`)**: `yeas > nays` 이면 하원 통과 (`house_pass = True`).
   - **상원 투표 (`senate_vote`)**:
     - `filibuster == True`인 경우: 토론 종결 표결을 진행하여 `cloture_yeas / (cloture_yeas + cloture_nays) >= 0.60` (3/5 이상)이어야 종결 성공. 종결 실패 시 법안은 상원에서 폐기 (`status: "KILLED_BY_FILIBUSTER"`).
     - 필리버스터가 없거나 종결 성공 시: 본회의 표결 `yeas > nays` 이면 상원 통과 (`senate_pass = True`).
   - 양원 통과(`house_pass and senate_pass`) 시: `status: "PASSED_LEGISLATURE"`.
   - 불통과 시: `status: "REJECTED_BY_LEGISLATURE"`.
3. `EXECUTIVE_ACTION`:
   - `action: "SIGN"`: 대통령이 서명하여 법률로 발효. `status: "ENACTED_BY_SIGNATURE"`. 효력 있는 법률 목록(`enacted_laws`)에 등록.
   - `action: "VETO"`: 대통령이 거부권 행사하여 의회로 환부. `status: "VETOED"`.
   - `action: "POCKET_VETO"`: 폐회 기간 중 방치하여 자동 폐기. `status: "POCKET_VETOED"`.
4. `VETO_OVERRIDE_VOTE`:
   - 거부권 행사 법안에 대해 양원 재의결 진행:
     - 하원: `house_yeas / house_total >= 2/3` ($66.6667\%$)
     - 상원: `senate_yeas / senate_total >= 2/3` ($66.6667\%$)
   - 양원 모두 $2/3$ 이상 충족 시: 거부권 무력화 및 법률 발효 (`status: "ENACTED_BY_VETO_OVERRIDE"`). `enacted_laws`에 등록.
   - 한 곳이라도 미달 시: 거부권 확정 및 법안 영구 폐기 (`status: "VETO_SUSTAINED"`).
5. `JUDICIAL_REVIEW`:
   - 공포된 법률(`law_id`)에 대해 위헌 심사 청구:
   - 각 조항별 재판관들의 위헌 찬성표(`unconstitutional_votes`)를 검사:
     - `unconstitutional_votes >= unconstitutional_threshold` 이면 해당 조항은 `UNCONSTITUTIONAL`.
   - **가분성(Severability) 판정**:
     - 위헌 조항이 0개: 전면 합헌 유지 (`verdict: "UPHELD_CONSTITUTIONAL"`).
     - 위헌 조항 중 `essential == True`인 본질적 조항이 포함되어 있거나, 모든 조항이 위헌인 경우: 법률 전면 무효화 (`verdict: "STRUCK_DOWN_ENTIRELY"`).
     - 위헌 조항이 모두 `essential == False`인 경우: 위헌 조항만 절단 삭제하고 나머지 조항은 합헌 유지 (`verdict: "PARTIALLY_UPHELD_SEVERED"`).

---

## 3. 입력 형식 (Input Specification)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "court_config": {
    "justice_count": 9,
    "unconstitutional_threshold": 6
  },
  "operations": [
    {
      "step": 1,
      "op": "INTRODUCE_BILL",
      "bill_id": "BILL-001",
      "title": "Clean Energy Standards Act",
      "articles": [
        {"id": 1, "title": "Renewable Target", "essential": true},
        {"id": 2, "title": "Grid Modernization Grant", "essential": false}
      ]
    },
    {
      "step": 2,
      "op": "LEGISLATIVE_VOTE",
      "bill_id": "BILL-001",
      "house_vote": {"yeas": 230, "nays": 200},
      "senate_vote": {"filibuster": false, "yeas": 53, "nays": 47}
    },
    {
      "step": 3,
      "op": "EXECUTIVE_ACTION",
      "bill_id": "BILL-001",
      "action": "SIGN"
    },
    {
      "step": 4,
      "op": "JUDICIAL_REVIEW",
      "law_id": "BILL-001",
      "article_votes": {
        "1": {"unconstitutional_votes": 1},
        "2": {"unconstitutional_votes": 2}
      }
    }
  ]
}
```

---

## 4. 출력 형식 (Output Specification)
표준 출력(stdout)으로 각 연산의 진행 로그, 통계 지표, 유효한 현행 법률 목록을 포함하는 JSON 객체를 한 줄로 출력합니다:
```json
{
  "operations_log": [
    {"step": 1, "op": "INTRODUCE_BILL", "bill_id": "BILL-001", "status": "INTRODUCED"},
    {"step": 2, "op": "LEGISLATIVE_VOTE", "bill_id": "BILL-001", "house_pass": true, "senate_pass": true, "status": "PASSED_LEGISLATURE"},
    {"step": 3, "op": "EXECUTIVE_ACTION", "bill_id": "BILL-001", "action": "SIGN", "status": "ENACTED_BY_SIGNATURE"},
    {"step": 4, "op": "JUDICIAL_REVIEW", "law_id": "BILL-001", "verdict": "UPHELD_CONSTITUTIONAL", "unconstitutional_article_ids": [], "active_article_ids": [1, 2], "status": "UPHELD_CONSTITUTIONAL"}
  ],
  "statistics": {
    "bills_introduced": 1,
    "bills_enacted_signature": 1,
    "bills_enacted_override": 0,
    "vetoes_exercised": 0,
    "vetoes_sustained": 0,
    "filibusters_successful": 0,
    "judicial_reviews_conducted": 1,
    "laws_struck_down_entirely": 0,
    "laws_partially_severed": 0,
    "laws_upheld": 1
  },
  "active_laws": {
    "BILL-001": {
      "title": "Clean Energy Standards Act",
      "active_articles": [1, 2]
    }
  }
}
```
