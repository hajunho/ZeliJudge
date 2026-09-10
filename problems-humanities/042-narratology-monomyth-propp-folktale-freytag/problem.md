# 문제 #042: 천의 얼굴을 가진 영웅과 민담의 문법: 서사학(Narratology) & 디지털 인문학: 블라디미르 프로프(Vladimir Propp)의 31대 민담 형태론(Morphology of the Folktale), 조지프 캠벨(Joseph Campbell)의 12단계 영웅의 여정(Hero's Journey Monomyth) 및 프라이타크 피라미드(Freytag's Pyramid) 서사 긴장도 시뮬레이터 (Narratology & Monomyth Questline Engine)

## 실무 및 학술 배경: 게임 시나리오 엔진과 AI 스토리텔링 검증 시스템
글로벌 AAA 게임 개발사(Blizzard, Riot, Sony)의 퀘스트 디자인 팀과 할리우드 영화 제작사, 그리고 디지털 인문학(Digital Humanities) 연구소는 수천 편의 퀘스트 스토리와 시나리오 플롯이 독자 및 플레이어에게 몰입감과 카타르시스를 전달하는지 검증하기 위한 **서사 구조 및 긴장도 분석 엔진(Narratology Engine)**을 구축하고 있습니다.

인류의 신화와 문학은 시공간을 초월하여 놀라울 정도로 정교한 보편적 문법을 공유합니다:
1. **블라디미르 프로프 (Vladimir Propp, 1928)**:
   - 『민담 형태론(*Morphology of the Folktale*)』에서 러시아 민담 100여 편을 분석하여, 모든 이야기의 가변적 세부 묘사 뒤에 숨겨진 **31개의 불변적 서사 기능(Functions)**과 **7대 인물 원형(Dramatis Personae)**을 발견했습니다.
   - 인물 원형: 영웅(Hero), 악당(Villain), 증여자(Donor: 마법의 수단을 주는 자), 조력자(Helper), 공주/보상(Princess or Prize), 파견자(Dispatcher), 가짜 영웅(False Hero).
2. **조지프 캠벨 (Joseph Campbell, 1949)**:
   - 『천의 얼굴을 가진 영웅(*The Hero with a Thousand Faces*)』에서 고대 길가메시 서사시부터 그리스 신화, 불교 설화, 스타워즈에 이르는 모든 신화가 **단일신화(Monomyth: 3막 12단계 영웅의 여정)**로 귀결됨을 규명했습니다:
     - 제1막 출발 (Departure): 일상 세계 $\to$ 모험의 소명 $\to$ 소명 거부 $\to$ 멘토와의 만남 $\to$ 첫 관문 통과
     - 제2막 입문 (Initiation): 시험/동맹/적 $\to$ 가장 깊은 동굴 접근 $\to$ 결정적 시련(Ordeal/죽음과 부활) $\to$ 보상(영약)
     - 제3막 귀환 (Return): 귀환의 길 $\to$ 부활 $\to$ 영약을 가지고 귀환
3. **구스타프 프라이타크 (Gustav Freytag, 1863)**:
   - 5막 비극 이론인 **프라이타크 피라미드(Freytag's Pyramid)**를 통해 서사 긴장도(Dramatic Tension)가 발단 $\to$ 상승(Rising Action) $\to$ 절정(Climax) $\to$ 하강(Falling Action) $\to$ 대단원(Denouement)의 대칭적 산형 곡선을 이룰 때 최고의 감정적 공명을 일으킴을 입증했습니다.

서사학 연구원이자 게임 시나리오 시스템 엔지니어로서, 인물 원형과 사건 연쇄를 분석하여 단일신화 순응도, 인물 간 공반 네트워크, 서사 결함(역행, 가짜 영웅 미폭로 등)을 판정하고 프라이타크 긴장도 곡선을 산출하는 엔진을 구현하십시오.

---

## 서사학 및 단일신화 알고리즘 사양

### 1. 조지프 캠벨의 12단계 단일신화 (Campbell's Monomyth Stages)
1. `ORDINARY_WORLD` (일상 세계)
2. `CALL_TO_ADVENTURE` (모험에의 소명)
3. `REFUSAL_OF_THE_CALL` (소명의 거부)
4. `MEETING_WITH_THE_MENTOR` (멘토와의 만남)
5. `CROSSING_THE_FIRST_THRESHOLD` (첫 번째 관문 통과)
6. `TESTS_ALLIES_ENEMIES` (시험, 동맹, 적)
7. `APPROACH_TO_INMOST_CAVE` (가장 깊은 동굴로의 접근)
8. `ORDEAL` (결정적 시련 / 죽음과 부활)
9. `REWARD` (보상 획득)
10. `THE_ROAD_BACK` (귀환의 길)
11. `RESURRECTION` (부활 / 최후의 시험)
12. `RETURN_WITH_THE_ELIXIR` (영약을 가지고 귀환)

* **3막 구조 (3-Act Structure)**:
  - 제1막 출발 (Departure): Stages 1 ~ 5
  - 제2막 입문 (Initiation): Stages 6 ~ 9
  - 제3막 귀환 (Return): Stages 10 ~ 12

---

### 2. 서사 문법 및 구조 결함 검증 (`structural_issues`)
1. **필수 인물 원형 결함**:
   - `HERO` 원형이 없으면: `"MISSING_HERO_ARCHETYPE"`
   - `VILLAIN` 원형이 없으면: `"MISSING_VILLAIN_ARCHETYPE"`
2. **사건-인물 정합성 결함**:
   - `propp_function == "DISPATCH"`인데 참여 인물 중 `DISPATCHER`가 없으면: `"DISPATCH_WITHOUT_DISPATCHER"`
   - `propp_function == "DONOR_TEST"`인데 참여 인물 중 `DONOR`가 없으면: `"DONOR_TEST_WITHOUT_DONOR"`
   - `propp_function`이 `"STRUGGLE"` 또는 `"ORDEAL"`인데 참여 인물 중 `VILLAIN`이 없으면: `"CLIMACTIC_STRUGGLE_WITHOUT_VILLAIN"`
3. **가짜 영웅 미폭로 결함**:
   - `FALSE_HERO` 원형이 존재하는데, `"EXPOSURE"` 또는 `"PUNISHMENT"` 기능 사건에 해당 인물이 등장하지 않고 서사가 끝나면: `"UNEXPOSED_FALSE_HERO"`
4. **불법적 서사 역행 (Illegal Stage Regression)**:
   - 사건 단계 인덱스 $i_{t} < i_{t-1} - 2$인 급격한 역행이 발생하면: `"ILLEGAL_STAGE_REGRESSION"`

---

### 3. 프라이타크 피라미드 긴장도 메트릭 (`freytag_pyramid`)
- `peak_tension`: 사건들의 긴장도 중 최댓값
- `peak_event_step`: 최고 긴장도가 발생한 사건의 단계 번호(`step`)
- `peak_stage`: 최고 긴장도 시점의 캠벨 단계
- `rising_action_slope`: 시작 사건부터 절정 사건까지의 평균 상승 기울기:
  $$\text{slope}_{\text{rise}} = \frac{\text{peak\_tension} - \text{initial\_tension}}{\text{peak\_index}} \quad (\text{peak\_index} > 0)$$
- `falling_action_slope`: 절정 사건부터 최종 사건까지의 평균 하강 기울기:
  $$\text{slope}_{\text{fall}} = \frac{\text{final\_tension} - \text{peak\_tension}}{\text{remaining\_steps}} \quad (\text{remaining\_steps} > 0)$$
- `climax_in_proper_phase`: 절정 사건이 입문 후반 또는 부활 단계(Stages 7, 8, 9, 11)에 위치하면 `True`, 그렇지 않으면 `False`.

---

### 4. 서사 완성도 등급 판정 (`narrative_rating`)
- `"MASTERPIECE_MONOMYTH"`: 결함(`structural_issues`)이 0건이고, 3막(출발, 입문, 귀환)을 모두 충족하며, 12단계 중 75% 이상(9단계 이상)을 포괄하고, 절정이 올바른 위치(`climax_in_proper_phase == True`)에 있는 경우.
- `"COHERENT_STANDARD"`: 결함이 0건이고 최소 2개 이상의 막을 충족하는 정상적인 단편/외전 서사.
- `"BROKEN_NARRATIVE"`: 불법적 서사 역행(`ILLEGAL_STAGE_REGRESSION`) 결함이 포함된 경우.
- `"IRREGULAR_AVANT_GARDE"`: 결함은 있으나 역행은 없거나 규칙을 벗어난 실험적 서사.

---

## 입력 형식 (`sys.stdin`)

JSON 객체로 주어지며 `mode`에 따라 동작합니다:
1. `mode == "ANALYZE_STORY"`: 단일 이야기 분석.
2. `mode == "BATCH_CORPUS_ANALYTICS"`: 다수 이야기 코퍼스 일괄 분석.

## 출력 형식 (`sys.stdout`)
단일 행의 압축된 JSON 문자열을 출력합니다.
