# 이론 정리: 오스틴과 설의 화행 이론 및 적정 조건과 제도적 사실

## 1. 일상언어학파와 화행 이론의 탄생

20세기 중반 옥스퍼드 일상언어학파(Oxford Ordinary Language Philosophy)의 중심인 **J. L. 오스틴(John L. Austin)**은 논리실증주의(Logical Positivism)가 언어의 기능을 참/거짓을 검증할 수 있는 명제적 진술로만 한정 지었던 **기술적 오류(Descriptive Fallacy)**를 비판했습니다.

그는 일상 언어에서 수많은 문장들이 사실을 묘사하는 것이 아니라, 발화 그 자체가 사회적·제도적 행위를 실행하는 **수행적 발화(Performative Utterances)**임을 규명했습니다:
- *"이 배를 퀸 엘리자베스호로 명명합니다."* (Naming/Christening)
- *"내일 10시까지 보고서를 제출하겠다고 약속합니다."* (Promising)
- *"피고인에게 징역 3년을 선고합니다."* (Sentencing)

이러한 문장들은 참이나 거짓으로 판별되는 것이 아니라, 성공적으로 행위가 완수되었는지(**Felicitous**) 아니면 결함으로 실패했는지(**Infelicitous**)로 평가됩니다.

---

## 2. 삼분법적 화행 체계 (Austin's Trichotomy)

오스틴은 단일한 발화 행위를 세 가지 차원으로 분해했습니다:

1. **발화 행위(Locutionary Act)**: 특정한 음성, 문법 규칙, 사전적 의미를 갖는 문장을 물리적으로 소리 내어 말하는 행위.
2. **발화 수반 행위(Illocutionary Act)**: 발화를 수행함에 있어(In saying something) 화자가 청자에게 부여하는 소통적 힘(Illocutionary Force). 진정한 의미의 행위(약속, 요청, 경고 등)가 성립하는 핵심 차원입니다.
3. **발화 효과(Perlocutionary Act)**: 발화를 통해(By saying something) 청자의 감정, 생각, 행동에 야기되는 실제적 결과(설득, 협박에 의한 공포, 위로 등).

---

## 3. 존 설(John Searle)의 5대 발화 수반 행위 분류

존 설은 발화 수반 행위의 목적(Illocutionary Point)과 적합 방향(Direction of Fit)을 기준으로 5대 범주를 확립했습니다:

| 화행 범주 | 적합 방향 (Direction of Fit) | 심리적 상태 (Sincerity) | 대표 예시 |
|:---|:---:|:---:|:---|
| **단언 (Assertives)** | 단어 $\to$ 세계 (Word-to-World) | 믿음 (Belief) | 주장, 진술, 보고, 추측 |
| **지시 (Directives)** | 세계 $\to$ 단어 (World-to-Word) | 욕망 (Desire) | 요청, 명령, 간청, 질문 |
| **약속 (Commissives)** | 세계 $\to$ 단어 (World-to-Word) | 의도 (Intention) | 약속, 맹세, 서약, 보증 |
| **표현 (Expressives)** | 없음 (Null - 전제된 사실) | 다양한 정서 태도 | 감사, 사과, 축하, 환영 |
| **선언 (Declarations)** | 양방향 (Both Words $\leftrightarrow$ World) | 없음 (제도적 권능) | 해고, 선전포고, 명명, 판결 |

---

## 4. 적정 조건(Felicity Conditions)과 오스틴의 결함 분류

발화 행위가 유효하게 기능하기 위해 충족해야 하는 4대 규칙(Searle, 1969):

1. **명제 내용 조건(Propositional Content Condition)**:
   - 약속은 반드시 화자 자신의 '미래 행위'를 명제 내용으로 삼아야 합니다. (과거 행위나 타인의 행위를 약속할 수 없음)
   - 명령/요청은 반드시 청자의 '미래 행위'를 명제 내용으로 삼아야 합니다.
2. **준비 조건(Preparatory Condition)**:
   - 선언의 경우, 화자가 해당 사회 제도(법원, 군대, 교회, 회사)에서 요구하는 적법한 **권한(Authority)**을 보유해야 합니다.
   - 명령의 경우, 청자가 해당 행위를 물리적·법적으로 수행할 능력이 있어야 합니다.
3. **성실성 조건(Sincerity Condition)**:
   - 화자가 발화와 일치하는 내적 심리 상태를 실제로 지녀야 합니다. (약속 시 실제 이행 의도 보유, 단언 시 실제 참이라고 믿음)
4. **본질 조건(Essential Condition)**:
   - 발화가 청자에게 특정한 의무를 생성하거나 제도적 상태를 변경하는 행위로 공식 간주되어야 합니다.

### 오스틴의 결함(Infelicities) 분류:
- **불발/실효(Misfire)**: 준비 조건이나 절차적 권한 결여로 인해 행위 자체가 원천 무효(Null and void)가 되는 현상. (권한 없는 관객이 배의 이름을 명명하는 경우)
- **남용/불성실(Abuse)**: 행위 자체는 외관상 성립되었으나, 성실성 조건을 위반하여 공허하거나 사기적인 행위가 되는 현상. (지킬 생각 없이 거짓 약속을 하거나 거짓말을 하는 경우)

---

## 5. 인공지능 및 다중 에이전트 시스템(MAS)에서의 의의

화행 이론은 FIPA-ACL(Foundation for Intelligent Physical Agents - Agent Communication Language), 대화형 AI(Conversational Agents), 자율 에이전트 간 협상 프로토콜 및 스마트 컨트랙트 상태 전이의 핵심 수학적·논리적 모델로 널리 응용되고 있습니다.
