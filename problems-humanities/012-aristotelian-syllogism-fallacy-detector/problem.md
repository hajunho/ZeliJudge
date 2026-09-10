# [철학/형식논리학] 아리스토텔레스 정언 삼단논법(Categorical Syllogism) 타당성 검증과 형식적 오류(Formal Fallacy) 탐지 및 엔티메메(Enthymeme) 복원 엔진

## 문제 설명

고대 그리스 아리스토텔레스(Aristotle)의 《오르가논(Organon) - 분석론 전서(Prior Analytics)》에서 확립된 **정언 삼단논법(Categorical Syllogism)**은 2,400년 동안 서양 철학, 형식논리학, 법학(법적 추론 및 리걸 테크), 인공지능 기호주의(Symbolic AI)의 근간을 이루는 논증 형식입니다.

삼단논법은 대전제(Major Premise), 소전제(Minor Premise), 결론(Conclusion)의 세 명제와 대개념(P), 소개념(S), 매개념(M)의 세 개념으로 구성됩니다.
그러나 일상적인 토론, 법정 공방, 철학적 담론에서는 부당한 결론을 도출하는 수많은 **형식적 논리 오류(Formal Fallacies)**가 발생하며, 논증의 효율을 위해 전제 하나를 생략하는 **엔티메메(Enthymeme, 생략 삼단논법)**가 빈번히 사용됩니다.

로스쿨 법학적성시험(LEET 추리논증), 공직적격성평가(PSAT 언어논리), 인공지능 논증 마이닝(Argument Mining) 연구팀의 일원이 되어, 입력된 정언 삼단논법의 **격(Figure, 1~4격)**과 **식(Mood)**을 식별하고, **아리스토텔레스의 6대 고전 타당성 규칙**을 적용하여 논리 오류를 전수 검출하며, 전제가 생략된 **엔티메메의 숨은 전제를 자동 역추론·복원**하는 **형식논리학 추론 엔진**을 구현하십시오.

---

## 정언 명제 및 삼단논법 공리 규격

### 1. 4대 표준 정언 명제 (Standard-Form Categorical Propositions)
| 기호 | 명칭 | 기본 형식 | 주어($S$) 주연 여부 | 술어($P$) 주연 여부 |
|---|---|---|:---:|:---:|
| **A** | 전칭 긍정 (Universal Affirmative) | "All S are P" (모든 S는 P이다) | **주연 (Distributed)** | 부주연 (Undistributed) |
| **E** | 전칭 부정 (Universal Negative) | "No S are P" (어떤 S도 P가 아니다) | **주연 (Distributed)** | **주연 (Distributed)** |
| **I** | 특칭 긍정 (Particular Affirmative) | "Some S are P" (어떤 S는 P이다) | 부주연 (Undistributed) | 부주연 (Undistributed) |
| **O** | 특칭 부정 (Particular Negative) | "Some S are not P" (어떤 S는 P가 아니다) | 부주연 (Undistributed) | **주연 (Distributed)** |

*(공리: 전칭 명제 A, E는 주어를 주연시키고, 부정 명제 E, O는 술어를 주연시킵니다.)*

### 2. 삼단논법의 격(Figure) 구조
결론은 항상 "S는 P이다" (소개념 $S$, 대개념 $P$)이며, 두 전제에만 나타나는 개념을 매개념($M$)이라 합니다:
- **제1격 (Figure 1)**: 대전제 $M - P$, 소전제 $S - M$ $\implies$ 결론 $S - P$
- **제2격 (Figure 2)**: 대전제 $P - M$, 소전제 $S - M$ $\implies$ 결론 $S - P$
- **제3격 (Figure 3)**: 대전제 $M - P$, 소전제 $M - S$ $\implies$ 결론 $S - P$
- **제4격 (Figure 4)**: 대전제 $P - M$, 소전제 $M - S$ $\implies$ 결론 $S - P$

### 3. 아리스토텔레스 6대 고전 타당성 규칙 및 형식적 오류(Fallacies)
1. **Rule 1 (사개념의 오류, `FALLACY_OF_FOUR_TERMS`)**:
   - 논증 전체에 정확히 3개의 독립된 개념($S, P, M$)만 존재해야 합니다. 개념 수가 3개가 아닌 경우.
2. **Rule 2 (매개념 부주연의 오류, `UNDISTRIBUTED_MIDDLE`)**:
   - 매개념 $M$은 적어도 하나의 전제에서 반드시 주연되어야 합니다. 두 전제 모두에서 $M$이 부주연된 경우.
3. **Rule 3 (부당 주연의 오류, `ILLICIT_MAJOR` / `ILLICIT_MINOR`)**:
   - 결론에서 주연된 개념은 해당 전제에서도 반드시 주연되어 있어야 합니다.
   - 결론의 $P$가 주연인데 대전제의 $P$가 부주연인 경우: `ILLICIT_MAJOR` (대개념 부당주연).
   - 결론의 $S$가 주연인데 소전제의 $S$가 부주연인 경우: `ILLICIT_MINOR` (소개념 부당주연).
4. **Rule 4 (양부정 전제의 오류, `EXCLUSIVE_PREMISES`)**:
   - 두 전제가 모두 부정 명제(E 또는 O)여서는 안 됩니다. 적어도 하나의 전제는 긍정(A 또는 I)이어야 합니다.
5. **Rule 5 (부정/긍정 정합성 오류)**:
   - 전제 중 하나라도 부정문이면 결론도 반드시 부정문이어야 합니다. 결론이 긍정이면: `NEGATIVE_PREMISE_AFFIRMATIVE_CONCLUSION`.
   - 두 전제가 모두 긍정문이면 결론도 반드시 긍정문이어야 합니다. 결론이 부정이면: `AFFIRMATIVE_PREMISES_NEGATIVE_CONCLUSION`.
6. **Rule 6 (존재 함의의 오류, `EXISTENTIAL_FALLACY`)**:
   - 두 전제가 모두 전칭(A 또는 E)인데 결론이 특칭(I 또는 O)인 경우 (현대 불리언 대수적 관점).

### 4. 15대 고전적 무조건 타당식 (Classical Valid Forms)
모든 규칙을 통과한 삼단논법은 고유의 라틴어 이름이 부여됩니다:
- 제1격: `Barbara` (AAA-1), `Celarent` (EAE-1), `Darii` (AII-1), `Ferio` (EIO-1)
- 제2격: `Cesare` (EAE-2), `Camestres` (AEE-2), `Festino` (EIO-2), `Baroco` (AOO-2)
- 제3격: `Disamis` (IAI-3), `Datisi` (AII-3), `Bocardo` (OAO-3), `Ferison` (EIO-3)
- 제4격: `Camenes` (AEE-4), `Dimaris` (IAI-4), `Fresison` (EIO-4)

### 5. 엔티메메(Enthymeme) 숨은 전제 복원
- 하나의 주어진 전제와 결론이 주어질 때:
  - 주어진 전제가 소개념 $S$를 포함하면 대전제(Major Premise)가 누락된 것이고, 대개념 $P$를 포함하면 소전제(Minor Premise)가 누락된 것입니다.
  - 가능한 명제 유형(A, E, I, O)과 항의 순서(주어/술어) 총 8가지 후보 중, 결합 시 **무조건 타당한 삼단논법이 되는 후보 전제**를 탐색하여 반환합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "syllogisms": [
    {
      "id": "SYL_01",
      "major_premise": {"type": "A", "subject": "Human", "predicate": "Mortal"},
      "minor_premise": {"type": "A", "subject": "Greek", "predicate": "Human"},
      "conclusion": {"type": "A", "subject": "Greek", "predicate": "Mortal"}
    }
  ],
  "enthymemes": [
    {
      "id": "ENTH_01",
      "given_premise": {"type": "A", "subject": "Socrates", "predicate": "Human"},
      "conclusion": {"type": "A", "subject": "Socrates", "predicate": "Mortal"}
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 계산된 결과를 JSON 문자열(단일 라인)로 출력합니다:
```json
{
  "syllogism_evaluation": {
    "total_syllogisms": 1,
    "valid_syllogisms_count": 1,
    "invalid_syllogisms_count": 0,
    "fallacy_frequency": {},
    "results": [
      {
        "id": "SYL_01",
        "is_valid": true,
        "classical_name": "Barbara",
        "figure": 1,
        "mood": "AAA",
        "fallacies": []
      }
    ]
  },
  "enthymeme_reconstruction": {
    "total_enthymemes": 1,
    "results": [
      {
        "id": "ENTH_01",
        "reconstructed": true,
        "missing_role": "MAJOR",
        "valid_candidates_count": 1,
        "candidates": [
          {
            "missing_role": "MAJOR",
            "premise": {"type": "A", "subject": "Human", "predicate": "Mortal"},
            "classical_name": "Barbara",
            "mood": "AAA",
            "figure": 1
          }
        ]
      }
    ]
  }
}
```
