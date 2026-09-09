# 2-SAT과 강결합 컴포넌트 (SCC)

## 1. 함의 그래프 (Implication Graph)
- 절 $(A \lor B)$는 대우 명제와 동치인 두 함의 조건 $(\neg A \implies B)$와 $(\neg B \implies A)$를 생성합니다.
- 변수 $x_i$와 그 부정 $\neg x_i$를 정점으로 갖는 방향 그래프를 구축합니다.

## 2. 2-SAT 만족성 정리
- 그래프에서 SCC를 추출했을 때, 어떤 변수 $x_i$에 대해 **$x_i$와 $\neg x_i$가 같은 SCC에 속해 있다면**, $x_i \implies \neg x_i$이고 $\neg x_i \implies x_i$가 되어 모순(Contradiction)이 발생하므로 만족 불가능(0)입니다.
- 모든 $x_i$에 대해 두 정점이 서로 다른 SCC에 속한다면 항상 만족 가능한 진리 할당이 존재(1)합니다.