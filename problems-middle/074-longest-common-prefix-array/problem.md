# 사전식 정렬과 공통 분모! LCP(Longest Common Prefix) 배열

### 문제 설명
단어 $N$개가 주어집니다.  
1. 먼저 주어진 단어들을 **사전순(오름차순)**으로 정렬합니다.
2. 정렬된 단어 목록에서 **인접한 두 단어 간의 최장 공통 접두사(LCP, Longest Common Prefix)의 길이**를 차례대로 구하는 프로그램을 작성하세요.

예를 들어 `["banana", "band", "apple", "bandana"]`가 주어지면:
- 정렬 결과: `apple, banana, band, bandana`
- `apple`과 `banana`: 공통 접두사 없음 $\to 0$
- `banana`와 `band`: 공통 접두사 `"ban"` $\to 3$
- `band`와 `bandana`: 공통 접두사 `"band"` $\to 4$
따라서 LCP 배열은 `[0, 3, 4]`가 됩니다.

LCP 배열은 문자열 검색 엔진, 접미사 배열(Suffix Array) 압축 인덱싱의 핵심 기초입니다!

---

### 입력 형식
- 첫째 줄에 단어의 개수 $N$ ($2 \le N \le 1000$)이 주어집니다.
- 둘째 줄에 $N$개의 단어가 공백으로 구분되어 주어집니다. 각 단어의 길이는 1 이상 100 이하입니다.

---

### 출력 형식
- 첫째 줄에 사전순으로 정렬된 단어들을 공백으로 구분하여 출력합니다.
- 둘째 줄에 인접한 단어 쌍 사이의 LCP 길이 $N-1$개를 공백으로 구분하여 출력합니다.

---

### 입출력 예시

#### 예제 입력 1
```
4
banana band apple bandana
```

#### 예제 출력 1
```
apple banana band bandana
0 3 4
```
