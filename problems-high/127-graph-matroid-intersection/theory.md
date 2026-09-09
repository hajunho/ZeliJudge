# 두 개의 독립성을 동시에 만족하라! 매트로이드 교집합 (Matroid Intersection)

## 핵심 개념 및 알고리즘 개요
- **태그**: 그래프, 매트로이드(Matroid), 매트로이드 교집합(Matroid Intersection), 증가 경로, 독립 집합, $O(R^2 E)$
- **핵심 요약**: 간선 색상 중복 제한(분할 매트로이드)과 사이클 없음(그래픽 매트로이드)을 동시에 만족하는 최대 간선 집합을 구합니다.

---

### 매트로이드 교집합 (Matroid Intersection)

매트로이드 $M = (E, \mathcal{I})$는 탐욕 알고리즘(Greedy)이 최적해를 보장하는 수학적 구조(독립성, 유전성, 교환성)를 갖는 시스템입니다:
- **그래픽 매트로이드(Graphic Matroid)**: 포레스트(사이클이 없는 간선 부분집합)
- **분할 매트로이드(Partition Matroid)**: 각 색상별로 최대 1개의 간선만 선택하는 부분집합

1. **두 매트로이드의 교집합**:
   - 두 매트로이드 $M_1 = (E, \mathcal{I}_1)$과 $M_2 = (E, \mathcal{I}_2)$가 주어졌을 때, 두 매트로이드에서 **동시에 독립(Independent)**인 최대 부분집합 $I \in \mathcal{I}_1 \cap \mathcal{I}_2$를 찾는 문제입니다.
   - 단일 매트로이드의 독립 집합은 그리디로 풀리지만, 두 매트로이드의 교집합은 **증가 경로(Augmenting Path)** 기법을 사용하여 다항 시간에 해결됩니다.

2. **교환 그래프(Exchange Graph)와 증가 경로**:
   - 현재 공통 독립 집합 $I$에 대해:
     - 소스 집합 $X_1 = \{ y \notin I \mid I \cup \{y\} \in \mathcal{I}_1 \}$
     - 싱크 집합 $X_2 = \{ y \notin I \mid I \cup \{y\} \in \mathcal{I}_2 \}$
     - 유향 간선: $I \setminus \{x\} \cup \{y\}$가 여전히 독립을 만족하도록 하는 교환 간선 추가.
   - 교환 그래프에서 $X_1$에서 $X_2$로의 최단 증가 경로를 BFS로 찾아 대칭차(Symmetric Difference)로 $I$를 1씩 증강합니다.

---

## 복잡도 분석
- **시간 복잡도**: 본문 이론 및 구현 참조
- **공간 복잡도**: $O(N)$ 또는 $O(V + E)$

## 추천 연습 문제
- 관련 백준(BOJ) 및 Codeforces / ICPC 기출 고난도 문제
