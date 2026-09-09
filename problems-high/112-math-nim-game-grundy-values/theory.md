# 승리의 필승 전략을 XOR로 밝혀라! 스프라그-그런디 정리 (Sprague-Grundy Theorem)

## 핵심 개념 및 알고리즘 개요
- **태그**: 수학, 게임 이론, 님 게임(Nim Game), 스프라그-그런디(Sprague-Grundy), MEX 연산, $O(N)$
- **핵심 요약**: 여러 개의 독립적인 게임 상태를 그런디 수 $G(n)$로 치환하고 XOR 합으로 선공의 필승 여부를 판정합니다.

---

### 불공정 게임 이론과 스프라그-그런디 정리 (Sprague-Grundy Theorem)

두 플레이어가 번갈아가며 말을 움직이는 유한 임파셜 게임(Impartial Game)에서, 마지막 움직임을 하는 사람이 이기는 정상 규칙(Normal Play)을 다룹니다.

1. **그런디 수(Grundy Value)와 MEX**:
   - 도달할 수 있는 다음 상태들의 집합을 $S$라 할 때, 상태 $u$의 그런디 값 $G(u)$는 $S$의 그런디 값들의 **MEX (Minimum Excluded Value)**로 정의됩니다:
     $$G(u) = \text{mex}(\{G(v) \mid u \to v\}) = \min \{k \ge 0 \mid k \notin \{G(v)\}\}$$
   - 종료 상태(움직일 수 없는 상태)의 그런디 수는 $0$입니다.

2. **스프라그-그런디 정리**:
   - 서로 독립적인 여러 개의 하위 게임 $H_1, H_2, \dots, H_K$로 이루어진 복합 게임의 총 그런디 수는 **각 하위 게임의 그런디 수들의 비트 단위 XOR 합(Nim-sum)**과 정확히 같습니다:
     $$G_{total} = G(H_1) \oplus G(H_2) \oplus \dots \oplus G(H_K)$$
   - $G_{total} \ne 0$이면 **선공 필승(First-player win)** 상태이며,
   - $G_{total} = 0$이면 **후공 필승(Second-player win)** 상태입니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
