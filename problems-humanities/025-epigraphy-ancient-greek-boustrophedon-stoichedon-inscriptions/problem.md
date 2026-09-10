# 고문서 금석학(Epigraphy)과 계산 고고학: 고대 그리스 부스트로페돈(Boustrophedon)·스토이케돈(Stoichedon) 결손 비문 복원 엔진

## 문제 설명

수천 년 전 지중해 고대 아테네 아고라, 델피 신전, 크레타 고르틴(Gortyn) 등지에 세워진 대리석 비석(Stele)들은 고대 민주주의의 법령, 공공 조세 장부, 군사 동맹 조약, 신전 봉헌문을 새긴 인류 역사상 가장 중요한 1차 사료입니다.

그러나 수천 년에 걸친 풍화 작용, 지진, 전란, 그리고 석재 파손으로 인해 현대 고고학자들과 금석학자(Epigrapher)들이 발굴하는 비문 조각들은 글자가 심각하게 마모되거나 결실된 **결손(Lacuna, 缺損)** 상태를 띱니다.

고대 그리스 비문은 현대 텍스트와 근본적으로 다른 두 가지 고유한 서사 전통(Calligraphic Tradition)을 지니고 있습니다:

1. **부스트로페돈 (Boustrophedon, βουστροφηδόν, '소가 밭을 갈듯 좌우 교대 서법')**:
   - 농부가 소를 몰고 밭을 갈 때 이랑 끝에서 반대 방향으로 되돌아오듯, **짝수 행(0, 2, 4...)은 좌에서 우($L \to R$)로 읽고, 홀수 행(1, 3, 5...)은 우에서 좌($R \to L$)로 교대하며 읽는 방식**입니다.
   - 독자가 행 끝에서 시선을 비석 반대편으로 멀리 이동시킬 필요 없이 연속해서 글을 읽을 수 있도록 고안된 지혜로운 방식입니다. 돌 표면의 물리적 행에서 홀수 행은 읽는 순서와 좌우가 반대로 음각됩니다.
2. **스토이케돈 (Stoichedon, στοιχηδόν, '바둑판 격자 정렬 서법')**:
   - 기원전 5~4세기 고전기 아테네 공공 비문에서 확립된 기하학적 서법으로, **모든 글자가 행($R$)과 열($C$)의 엄격한 2차원 직사각형 바둑판 격자에 1:1로 정렬**됩니다.
   - 단어 사이의 띄어쓰기가 없는 연속 서법(*Scriptio continua*)을 따르며, 단어가 행의 끝에서 잘릴 때도 하이픈(`-`) 없이 다음 행의 첫 격자 칸으로 자연스럽게 이어집니다.
   - 격자 열 너비($C$)가 전 행에 걸쳐 완전히 일정하므로, 풍화로 글자가 지워진 결손부(Lacuna)의 정확한 글자 수와 2차원 공간 좌표를 수학적으로 100% 특정할 수 있습니다.

당신은 고문서 금석학 및 계산 고고학 연구소의 디지털 휴머니티스 수석 엔지니어로서, 결손부(`?` 또는 `_`)가 포함된 고대 비석 표면의 2차원 격자 행렬 데이터를 입력받아:
1. 결손율 및 보존 글자의 빈도 분포를 통계적으로 분석하고,
2. 부스트로페돈 경로를 따라 물리적 2차원 격자를 1차원 의미 독서 스트림(Reading Stream)으로 전개(Unfold)하며,
3. 고대 어휘 사전(`lexicon`) 및 표준 공공 관용구 공식(`target_formula`)을 활용한 와일드카드 단어 분할(Wildcard Word Segmentation) 알고리즘으로 결손 문자를 무결하게 복원한 뒤,
4. 복원된 텍스트를 다시 원래의 2차원 돌 표면 스토이케돈 물리 격자로 완벽하게 재합성하는 복원 엔진을 완성해야 합니다.

---

## 시스템 상세 사양

### 1. 입력 데이터 구조
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "grid_rows": [
    "Ε?ΟΧΣΕΝΤΕΙΒΟΛ",
    "ΙΟΜΕ?ΙΟΤΙΑΚΙΕ"
  ],
  "is_boustrophedon": true,
  "lexicon": [
    "ΕΔΟΧΣΕΝ", "ΤΕΙ", "ΒΟΛΕΙ", "ΚΑΙ", "ΤΟΙ", "ΔΕΜΟΙ"
  ],
  "target_formula": null
}
```

- `grid_rows`: 돌 표면에 음각된 2차원 물리 행렬 문자열 리스트 ($R$행 $C$열).
  - 마모되거나 깨진 결손 글자는 `?` 또는 `_`로 표기됩니다.
  - 고대 그리스 대문자(예: `Ε, Δ, Ο, Χ, Σ...`) 또는 라틴 대문자 전사 표기(`EDOXSEN...`)가 사용될 수 있습니다.
- `is_boustrophedon`: 불리언. `true`이면 좌우 교대 서법 적용(짝수 행: $L \to R$, 홀수 행: $R \to L$). `false`이면 모든 행 좌에서 우($L \to R$) 직진 서법.
- `lexicon`: 고대 그리스 어휘 사전 (단어 문자열 리스트).
- `target_formula`: 표준 공문서 공식 단어 시퀀스 리스트 또는 `null`. 지정된 경우 해당 시퀀스를 우선 검증 기준으로 적용.

---

### 2. 처리 알고리즘 및 4단계 파이프라인

#### (1) 격자 통계 및 결손율(Lacuna Rate) 계산
- 전체 격자 크기: $\text{total\_cells} = R \times C$.
- 보존 글자 수(`intact_characters`) 및 결손 글자 수(`damaged_characters`, `?` 또는 `_`).
- 결손율: $\text{lacuna\_rate\_pct} = \text{round}\left(\frac{\text{damaged\_characters}}{\text{total\_cells}} \times 100, 2\right)$.
- 보존 글자 빈도 분포: 각 글자의 출현 횟수를 내림차순(빈도가 같으면 알파벳 오름차순)으로 정렬한 딕셔너리.

#### (2) 부스트로페돈 독서 스트림 전개 (Unfolding)
- 행 번호 $r$ ($0 \le r < R$):
  - `is_boustrophedon == true`이고 $r \% 2 == 1$ (홀수 행):
    - 비석 우측 끝 열($c = C-1$)부터 좌측 끝 열($c = 0$)까지 역방향으로 문자를 읽어 스트림에 추가.
  - 그 외 (짝수 행 또는 비부스트로페돈):
    - 좌측($c = 0$)부터 우측($c = C-1$)까지 순방향으로 문자를 읽어 스트림에 추가.
- 전개된 1차원 문자열을 `unfolded_raw_text`로 생성하고, 각 스트림 위치 $i$와 비석 2차원 좌표 $(r, c)$의 매핑 테이블을 기록.

#### (3) 와일드카드 단어 분할 및 결손 문자 복원 (Restoration)
- 목표 단어 시퀀스 결정:
  - `target_formula`가 주어진 경우: 연결된 글자 수가 전체 셀 수와 일치하고 패턴과 일치하면 단일 후보(`candidates_count = 1`, `status = "SUCCESS_FORMULA"`)로 채택.
  - `lexicon`만 주어진 경우: `find_segmentations(unfolded_raw_text, lexicon)`을 실행하여 어휘 사전 단어들의 조합으로 결손부를 채울 수 있는 모든 유효 분할을 탐색.
    - 해가 1개인 경우: `status = "SUCCESS_UNIQUE"`, `candidates_count = 1`.
    - 해가 2개 이상인 경우: `status = "AMBIGUOUS"`, `candidates_count = len(segs)`. 첫 번째 후보를 채택하여 복원.
    - 해가 없는 경우: `status = "UNRESOLVED"`, `candidates_count = 0`.
- 채택된 단어 시퀀스를 기반으로 결손 글자(`?`, `_`)를 해당 원형 문자로 복원하고 `restoration_log`에 기록:
  `{"pos": stream_idx, "row": r, "col": c, "original": orig_char, "restored": char, "source_word": word}`.

#### (4) 2차원 물리 스토이케돈 격자 재합성 (Refolding)
- 복원된 1차원 스트림의 문자들을 원래의 좌표 매핑 $(r, c)$에 따라 2차원 격자에 배치하여 `restored_grid_rows`를 생성.
- 홀수 행의 경우 비석 물리 표면에는 다시 우에서 좌로 읽히도록 좌우가 반전된 원래의 물리적 순서로 배치됩니다!

---

## 출력 형식

표준 출력(stdout)으로 복원 결과 및 금석학 분석 지표를 포함하는 단일 JSON 라인을 출력합니다:

```json
{
  "grid_dimensions": {
    "rows": 2,
    "cols": 13,
    "total_cells": 26
  },
  "lacuna_analysis": {
    "intact_characters": 24,
    "damaged_characters": 2,
    "lacuna_rate_pct": 7.69,
    "letter_frequencies": {
      "Ε": 5, "Ι": 4, "Ο": 3, "Τ": 2
    }
  },
  "reading_stream": {
    "unfolded_raw_text": "Ε?ΟΧΣΕΝΤΕΙΒΟΛΕΙΚΑΙΤΟΙΔΕ?ΟΙ"
  },
  "restoration": {
    "status": "SUCCESS_UNIQUE",
    "restorations_count": 2,
    "remaining_lacunae": 0,
    "candidates_count": 1,
    "restored_reading_text": "ΕΔΟΧΣΕΝΤΕΙΒΟΛΕΙΚΑΙΤΟΙΔΕΜΟΙ",
    "restored_grid_rows": [
      "ΕΔΟΧΣΕΝΤΕΙΒΟΛ",
      "ΙΟΜΕΔΙΟΤΙΑΚΙΕ"
    ],
    "restoration_log": [
      {
        "pos": 1,
        "row": 0,
        "col": 1,
        "original": "?",
        "restored": "Δ",
        "source_word": "ΕΔΟΧΣΕΝ"
      }
    ]
  }
}
```
