# 문제 052: 촘스키-할레 SPE 변별 자질 및 음운 재작성 규칙 파서 (Chomsky-Halle SPE Distinctive Features & Phonological Rewrite Engine)

## 문제 설명

1968년 노엄 촘스키(Noam Chomsky)와 모리스 할레(Morris Halle)는 저서 『영어의 음성 패턴(The Sound Pattern of English, 약칭 **SPE**』을 통해 현대 생성음운론(Generative Phonology)의 초석을 놓았습니다. SPE 이론에서는 언어의 개별 음소(Segment)를 더 이상 분할 불가능한 원자적 기호로 보지 않고, 조음 기관의 상태와 음향적 특성을 나타내는 **이진 변별 자질(Binary Distinctive Features, $[+F]$ 또는 $[-F]$)의 묶음(Matrix/Bundle)**으로 정의합니다.

심층에 존재하는 기저형(Underlying Representation, UR)은 순차적으로 적용되는 **음운 규칙(Phonological Rewrite Rules)**을 거쳐 표면형(Surface Representation, SR)으로 도출(Derivation)됩니다:
$$\text{Underlying Representation} \xrightarrow{\text{Rule 1}} \text{Intermediate Form}_1 \xrightarrow{\text{Rule 2}} \dots \xrightarrow{\text{Rule } n} \text{Surface Representation}$$

전통적인 SPE 음운 규칙의 표준 표기법은 다음과 같습니다:
$$A \to B \ / \ C \ \_ \ D$$
- $A$ (**Target / Focus**): 규칙이 적용될 대상 음소의 자질 조건.
- $B$ (**Structural Change**): 규칙 적용 후 변화할 자질 또는 결과. (삽입 규칙의 경우 $\emptyset \to B$, 탈락 규칙의 경우 $A \to \emptyset$)
- $C$ (**Left Context**): 대상 음소 바로 앞에 선행해야 하는 환경 자질 조건열. 단어 경계 $\#$가 포함될 수 있습니다.
- $D$ (**Right Context**): 대상 음소 바로 뒤에 후행해야 하는 환경 자질 조건열. 단어 경계 $\#$가 포함될 수 있습니다.

본 문제에서는 음소 인벤토리(Phoneme Inventory), 기저형 음소 연쇄(Underlying Representation), 그리고 외적으로 순서화된(Extrinsically Ordered) SPE 음운 규칙 목록이 주어졌을 때, SPE의 동시 적용 원칙(Simultaneous Application Principle)을 준수하여 표면형 및 각 단계별 유도 과정(Derivation)을 도출하는 **SPE 음운 연쇄 파서 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "inventory": {
    "k": {"cons": "+", "son": "-", "cont": "-", "voice": "-", "ant": "-", "cor": "-", "back": "+"},
    "l": {"cons": "+", "son": "+", "cont": "+", "voice": "+", "ant": "+", "cor": "+", "back": "-"},
    "u": {"cons": "-", "son": "+", "cont": "+", "voice": "+", "ant": "-", "cor": "-", "back": "+"},
    "b": {"cons": "+", "son": "-", "cont": "-", "voice": "+", "ant": "+", "cor": "-", "back": "-"},
    "p": {"cons": "+", "son": "-", "cont": "-", "voice": "-", "ant": "+", "cor": "-", "back": "-"}
  },
  "underlying_representation": ["k", "l", "u", "b"],
  "rules": [
    {
      "name": "Final Obstruent Devoicing",
      "action": "change",
      "target": {"cons": "+", "son": "-"},
      "change": {"voice": "-"},
      "left_context": [],
      "right_context": [{"boundary": "#"}]
    }
  ]
}
```

- `inventory`: 음소 기호(string)를 키로 하고, 해당 음소의 이진 자질 딕셔너리(`{"자질명": "+/-"}`)를 값으로 갖는 매핑 객체.
- `underlying_representation`: 기저형 음소 기호들의 순서 있는 리스트.
- `rules`: 순차적으로 적용될 규칙들의 리스트. 각 규칙은 다음 필드를 가집니다:
  - `name`: 규칙 이름 (string)
  - `action`: 규칙 동작 유형 (`"change"`, `"delete"`, `"insert"`)
  - `target`: `action`이 `"change"` 또는 `"delete"`일 때 매칭되어야 할 자질 조건 딕셔너리.
  - `change` (선택): 변경할 자질 값 딕셔너리.
  - `copy_from` (선택): 인접 분절음으로부터 자질을 복사(동화 현상)할 때 사용되는 객체:
    - `direction`: `"left"` 또는 `"right"`
    - `offset`: 오프셋 정수 (0은 바로 인접한 분절음)
    - `features`: 복사할 자질 이름 리스트
  - `result_symbol` (선택): 변환 후 부여할 특정 음소 기호. 지정되지 않은 경우 인벤토리에서 자질이 가장 잘 일치하는 기호를 자동 탐색.
  - `insert_segment` (선택): `action`이 `"insert"`일 때 삽입할 분절음 정보 (`{"symbol": "...", "features": {...}}`).
  - `left_context`: 대상 위치 바로 선행해야 하는 조건 리스트. 단어 시작 경계는 `{"boundary": "#"}`로 지정.
  - `right_context`: 대상 위치 바로 후행해야 하는 조건 리스트. 단어 끝 경계는 `{"boundary": "#"}`로 지정.

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "surface_representation": ["k", "l", "u", "p"],
  "surface_string": "klup",
  "derivation": [
    {
      "stage": "Underlying Representation",
      "form": ["k", "l", "u", "b"],
      "applied_at": []
    },
    {
      "stage": "Final Obstruent Devoicing",
      "form": ["k", "l", "u", "p"],
      "applied_at": [3]
    }
  ]
}
```

- `surface_representation`: 최종 표면형 음소 기호 리스트.
- `surface_string`: 표면형 음소 기호들을 결합한 단일 문자열.
- `derivation`: 규칙 적용 단계별 기록 리스트:
  - `stage`: 단계 명칭 (기저형 또는 규칙 이름).
  - `form`: 해당 단계 완료 후의 음소 기호 리스트.
  - `applied_at`: 해당 규칙이 매칭되어 적용된 인덱스 번호 리스트 (오름차순).

---

## 입출력 예시

### 예시 1: 러시아어 어말 장애음 무성음화 (Final Obstruent Devoicing)

**입력:**
```json
{
  "inventory": {
    "k": {"cons": "+", "son": "-", "cont": "-", "voice": "-", "ant": "-", "cor": "-", "back": "+"},
    "l": {"cons": "+", "son": "+", "cont": "+", "voice": "+", "ant": "+", "cor": "+", "back": "-"},
    "u": {"cons": "-", "son": "+", "cont": "+", "voice": "+", "ant": "-", "cor": "-", "back": "+"},
    "b": {"cons": "+", "son": "-", "cont": "-", "voice": "+", "ant": "+", "cor": "-", "back": "-"},
    "p": {"cons": "+", "son": "-", "cont": "-", "voice": "-", "ant": "+", "cor": "-", "back": "-"}
  },
  "underlying_representation": ["k", "l", "u", "b"],
  "rules": [
    {
      "name": "Final Obstruent Devoicing",
      "action": "change",
      "target": {"cons": "+", "son": "-"},
      "change": {"voice": "-"},
      "left_context": [],
      "right_context": [{"boundary": "#"}]
    }
  ]
}
```

**출력:**
```json
{"surface_representation": ["k", "l", "u", "p"], "surface_string": "klup", "derivation": [{"stage": "Underlying Representation", "form": ["k", "l", "u", "b"], "applied_at": []}, {"stage": "Final Obstruent Devoicing", "form": ["k", "l", "u", "p"], "applied_at": [3]}]}
```

---

## 제약 사항

- 단어 길이(분절음 개수): $1 \le N \le 100$
- 음소 인벤토리 크기: $1 \le M \le 50$
- 규칙 개수: $1 \le R \le 20$
- 모든 음운 규칙은 주어진 순서대로 1회씩 적용되며, 규칙 내부적으로는 단어 전체를 일괄 스캔하여 모든 매칭 위치에 대해 동시 적용(Simultaneous Application)됩니다.
