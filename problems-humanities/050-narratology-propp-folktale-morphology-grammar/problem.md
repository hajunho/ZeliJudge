# 블라디미르 프로프의 민담 형태론: 31개 서사 기능과 서사 문법 검증기 (Vladimir Propp Morphology of the Folktale & Narrative Grammar Parser)

## 문제 설명

러시아 형식주의(Russian Formalism) 및 구조주의 서사학(Structuralist Narratology)의 개척자인 **블라디미르 프로프(Vladimir Propp, 1895–1970)**는 1928년 저서 『민담 형태론(Morfologiya skazki)』에서 인물의 외모, 이름, 세부 묘사는 시대와 문화마다 무수히 변하지만, **서사에서 인물이 수행하는 행동과 기능(Functions of Dramatis Personae)의 집합과 연쇄 구조는 수학적이고 불변적인 법칙**을 따른다는 사실을 최초로 정립했습니다.

프로프는 마법 민담(Aarne-Thompson 유형)을 해부하여 **31개의 불변적 서사 기능(Narrative Functions)**과 **7개의 행동 영역(Spheres of Action)**을 규명하였으며, 민담의 구조가 단순한 사건의 나열이 아니라 엄격한 **서사 문법(Narrative Grammar)**에 의해 지배된다고 주장했습니다.

본 문제에서는 이야기의 사건 시퀀스를 입력받아 프로프의 31개 기능 기호 체계로 변환하고, 인과적 통사 제약(Causal Precedence Constraints)과 거시 국면의 시간적 단조성(Chronological Monotonicity)을 검증하며, 이야기 간 구조적 유사도를 분석하는 **프로프식 서사 형태론 파서**를 구현합니다.

---

## 프로프의 31개 서사 기능 및 기호 체계

1. **준비 단계 (Preparation)**:
   - $\beta$ (`beta`): 부재 (Absentation) - 연장자나 부모의 떠남
   - $\gamma$ (`gamma`): 금지 (Interdiction) - "~하지 말라"는 계율
   - $\delta$ (`delta`): 위반 (Violation) - 금지의 파기
   - $\epsilon$ (`epsilon`): 정찰 (Reconnaissance) - 악당의 탐색
   - $\zeta$ (`zeta`): 정보 전달 (Delivery) - 악당이 희생자에 대한 정보를 얻음
   - $\eta$ (`eta`): 속임수 (Trickery) - 악당의 기만과 변장
   - $\theta$ (`theta`): 공모 (Complicity) - 희생자가 속아 악당을 돕게 됨
2. **발단 및 결핍 (Complication)**:
   - $A$ (`A`): 악행/가해 (Villainy) - 악당이 위해를 가함
   - $a$ (`a`): 결핍 (Lack) - 마법 물건, 배우자 등의 부족 상태
   - $B$ (`B`): 중재/연결 (Mediation) - 파견자가 영웅에게 사명을 부여함
   - $C$ (`C`): 반작용 결의 (Beginning Counteraction) - 영웅의 결단
   - $\uparrow$ (`UP`): 출발 (Departure) - 영웅이 여정을 시작함
3. **증여자 시퀀스 (Donor Cycle)**:
   - $D$ (`D`): 증여자의 첫 시험 (First Function of Donor)
   - $E$ (`E`): 영웅의 반응 (Hero's Reaction)
   - $F$ (`F`): 마법 수단의 획득 (Provision/Receipt of Magical Agent)
4. **투쟁 및 결핍 해소 (Struggle & Crisis)**:
   - $G$ (`G`): 공간 이동/인도 (Transference/Guidance)
   - $H$ (`H`): 악당과의 직접 투쟁 (Struggle)
   - $J$ (`J`): 표식/낙인 (Branding)
   - $I$ (`I`): 악당 격퇴/승리 (Victory)
   - $K$ (`K`): 결핍 해소/구출 (Liquidation of Lack)
5. **귀환 및 추격 (Return)**:
   - $\downarrow$ (`DOWN`): 귀환 (Return)
   - $Pr$ (`Pr`): 악당의 추격 (Pursuit)
   - $Rs$ (`Rs`): 구출 (Rescue)
6. **가짜 영웅과 시련 (Unrecognized Arrival & False Hero)**:
   - $o$ (`o`): 미인식 도착 (Unrecognized Arrival)
   - $L$ (`L`): 가짜 영웅의 부당한 주장 (Unfounded Claims)
   - $M$ (`M`): 어려운 과제 (Difficult Task)
   - $N$ (`N`): 과제 해결 (Task Resolved)
7. **결말 및 승능 (Resolution)**:
   - $Q$ (`Q`): 영웅의 인지 (Recognition)
   - $Ex$ (`Ex`): 가짜 영웅의 정체 폭로 (Exposure)
   - $T$ (`T`): 변신/새 모습 (Transfiguration)
   - $U$ (`U`): 악당의 처벌 (Punishment)
   - $W$ (`W`): 결혼 및 즉위 (Wedding/Coronation)

---

## 서사 문법 검증 규칙 (Narrative Grammar Rules)

1. **발단 필수성 (`Rule A`)**: 이야기에는 가해($A$) 또는 결핍($a$) 중 최소 하나가 반드시 존재해야 합니다 (`MISSING_COMPLICATION`).
2. **증여자 인과성 (`Rule B`)**: 마법 수단의 획득($F$)은 반드시 그 이전에 증여자의 시험($D$)과 영웅의 반응($E$)이 선행해야 합니다 (`ILLEGAL_GIFT_WITHOUT_DONOR_CYCLE`).
3. **투쟁 선행성 (`Rule C`)**: 승리($I$)는 반드시 그 이전에 직접적인 투쟁($H$)이 선행해야 합니다 (`VICTORY_WITHOUT_STRUGGLE`).
4. **결핍 해소 인과성 (`Rule D`)**: 결핍 해소($K$)는 반드시 발단인 $A$ 또는 $a$ 이후에 발생해야 합니다 (`LIQUIDATION_WITHOUT_COMPLICATION`).
5. **거시 국면 시간 순서 (`Rule E`)**: 발단($A/a$) $\to$ 증여자($D/E/F$) $\to$ 투쟁/승리($H/I$) $\to$ 결핍 해소($K$) $\to$ 결말($W$)의 대단계는 거꾸로 역전될 수 없습니다 (`CHRONOLOGICAL_INVERSION_IN_{macro}`).

---

## 동작 모드

1. `parse_story`: 단일 이야기 사건 시퀀스를 파싱하여 정형 공식 문자열(`canonical_formula`), 핵심 6대 요소 충족 여부, 완성도 점수(0~100), 문법 유효성 및 오류 목록 출력.
2. `compare_stories`: 두 이야기 간 기능 자카드 유사도(Jaccard Similarity) 및 레벤슈타인 서사 편집 거리(Levenshtein Distance)를 계산하여 구조적 친화도(`structural_affinity`) 판정.
3. `corpus_grammar_audit`: 복수의 이야기 코퍼스에 대한 전수 문법 검사 및 평균 완성도 통계 산출.

---

## 입출력 예시

### 입력 (`parse_story`)
```json
{
  "mode": "parse_story",
  "story": {
    "title": "The Golden Apple and the Firebird",
    "events": [
      {"function": "a", "description": "황금 사과 결핍"},
      {"function": "B", "description": "이반 왕자 파견"},
      {"function": "C", "description": "출발 결의"},
      {"function": "UP", "description": "출발"},
      {"function": "D", "description": "바바 야가 시험"},
      {"function": "E", "description": "시험 완수"},
      {"function": "F", "description": "마법 검 획득"},
      {"function": "H", "description": "마왕과 투쟁"},
      {"function": "I", "description": "승리"},
      {"function": "K", "description": "사과 회수"},
      {"function": "DOWN", "description": "귀환"},
      {"function": "W", "description": "결혼"}
    ]
  }
}
```

### 출력
```json
{
  "mode": "parse_story",
  "result": {
    "title": "The Golden Apple and the Firebird",
    "canonical_formula": "a B C UP D E F H I K DOWN W",
    "functions_count": 12,
    "elements_present": {
      "complication": true,
      "departure": true,
      "donor_sequence": true,
      "struggle_victory": true,
      "liquidation": true,
      "resolution": true
    },
    "completeness_score": 100,
    "is_grammatically_valid": true,
    "syntax_errors": []
  }
}
```
