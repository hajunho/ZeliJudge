# 085 - 크롬 탭 30개 띄웠더니 컴퓨터가 왜 벽돌이 돼요?!: 가상 메모리 페이지 폴트(Page Fault)와 스래싱(Thrashing) & 시계(Clock) 알고리즘

## 1. 현실 비유 & 배경 스토리

공시생 철수의 좁은 원룸 책상을 상상해 보세요. 📚📖  
철수의 책상(물리 메모리 RAM)은 너무 좁아서 책을 딱 **3권(3 프레임)**만 올려둘 수 있습니다.  
하지만 철수가 오늘 시험공부를 위해 봐야 할 전공 서적은 국어, 영어, 한국사, 행정법, 행정학 등 총 **10권(가상 메모리 Virtual Memory)**입니다.

철수는 책상에 없는 책을 볼 때마다 일어나서 베란다 책장(하드디스크/SSD 스왑 영역)으로 가야 합니다.
- **책상에 있는 책 읽기 (Page Hit)**: 손만 뻗으면 되므로 **1초** 소요.
- **책장에 가서 책 바꿔오기 (Page Fault & Disk Swap)**: 베란다까지 걸어가서 책을 찾고 가져오느라 **10초** 소요.

```text
[철수의 공부 순서 (페이지 참조 스트림)]
국어 -> 영어 -> 한국사 -> 국어 -> 영어 -> 행정법 -> 국어 -> 영어 -> 행정학 ...
```

철수는 1시간 동안 공부를 5분밖에 못 했습니다.  
왜냐고요? 55분 동안 책상과 베란다 책장 사이를 왔다 갔다 하며 **책을 뺐다 꽂았다 하느라 체력이 방전(Thrashing)**되었기 때문입니다!

이것이 바로 현대 운영체제(Windows, Linux, macOS)에서 크롬 탭을 30개 띄우거나 대용량 프로그램을 여러 개 실행했을 때,  
**CPU 사용률은 100%를 찍고 팬이 굉음을 내는데 컴퓨터는 마우스 커서조차 굳어버리는 '스래싱(Thrashing, 가상 메모리 지옥)'**의 정체입니다.

프로세스들의 작업 집합(Working Set)이 물리 메모리(RAM) 용량을 초과하면, CPU는 실제 애플리케이션 코드를 실행하지 못하고 **하루 종일 디스크에서 페이지만 바꿨다 뺐다(Swap In/Out) 하느라 시스템 전체가 완전히 벽돌**이 됩니다.

운영체제는 이 문제를 완화하기 위해 어떤 페이지를 쫓아낼지 결정하는 **페이지 교체 알고리즘(Page Replacement Algorithm)**을 사용합니다.  
단순히 먼저 들어온 순서대로 쫓아내는 **FIFO**는 자주 쓰이는 핵심 페이지까지 쫓아내어 페이지 폴트 폭풍을 유발하지만,  
리눅스 커널이 채택한 **시계 알고리즘 (Clock Algorithm / Second-Chance)**은 하드웨어 참조 비트(Reference Bit)를 통해 최근에 사용된 인기 페이지에게 **두 번째 기회(Second Chance)**를 주어 보존함으로써, 페이지 폴트 발생률을 획기적으로 낮추고 스래싱을 방어합니다!

당신은 가상 메모리 시뮬레이터를 구축하여, 동일한 메모리 접근 스트림에 대해 **FIFO**와 **Clock** 엔진의 페이지 폴트 수, 총 지연 틱 비용, 스래싱 발생 여부를 비교 계측해야 합니다!

---

## 2. 시뮬레이션 상세 사양

물리 메모리는 $F$개의 프레임(Frame)을 가지며, 페이지 접근 비용은 다음과 같습니다:
- **페이지 적중 (Page Hit)**: 원하는 페이지가 이미 프레임에 존재함 $\to$ **1틱** 소요.
- **페이지 부재 (Page Fault)**: 원하는 페이지가 프레임에 없음 $\to$ **`fault_penalty` 틱** 소요.

### 1) FIFO 엔진 (`FIFO`)
- 빈 프레임이 있으면 순서대로 적재합니다.
- 프레임이 가득 찬 상태에서 부재가 발생하면, **가장 먼저 메모리에 들어왔던 페이지(First-In)**를 희생자(Victim)로 교체합니다.

### 2) 시계 알고리즘 엔진 (`CLOCK`, Second-Chance)
- 각 프레임은 `(page_id, ref_bit)`를 가지며, 원형 시계 바늘(`hand`, 초기 0)이 존재합니다.
- **페이지 적중 (Page Hit)**:
  - 해당 페이지가 위치한 프레임의 참조 비트를 `ref_bit = 1`로 세팅합니다.
- **페이지 부재 (Page Fault)**:
  - 시계 바늘이 가리키는 프레임부터 순환 탐색합니다:
    1. 빈 프레임(`None`)을 만나면: 해당 위치에 새 페이지를 적재하고 `ref_bit = 1`, 시계 바늘을 다음 위치로 전진(`hand = (hand + 1) % F`)하고 종료.
    2. 프레임의 `ref_bit == 1`이면: **기회를 한 번 더 줌(Second Chance)!** `ref_bit = 0`으로 내리고 시계 바늘을 다음 위치로 전진.
    3. 프레임의 `ref_bit == 0`이면: **이 페이지를 희생자(Victim)로 즉시 교체!** 새 페이지를 적재하고 `ref_bit = 1`, 시계 바늘을 다음 위치로 전진하고 종료.

### 3) 스래싱 (Thrashing) 판정
- 최근 `thrashing_window`개의 접근 이력 중, **페이지 부재(Fault) 비율이 `thrashing_threshold_pct`% 이상**이면 `THRASHING: TRUE`, 미만이면 `FALSE`로 판정합니다.
- 단, 총 접근 횟수가 `thrashing_window` 미만일 때는 항상 `FALSE`입니다.

---

## 3. 입력 명령 프로토콜

표준 입력(stdin)으로 다음 명령어들이 한 줄씩 주어집니다:

1. `INIT <num_frames> <fault_penalty> <thrashing_window> <thrashing_threshold_pct>`
   - 시뮬레이터를 초기화합니다.
   - `num_frames`: 물리 프레임 수 $F$ ($1 \le F \le 20$).
   - `fault_penalty`: 페이지 폴트 지연 틱 ($1 \le \text{fault\_penalty} \le 100$).
   - `thrashing_window`: 스래싱 감지 윈도우 크기 ($1 \le W \le 100$).
   - `thrashing_threshold_pct`: 스래싱 임계치 백분율 ($0.0 \le T \le 100.0$).
   - 출력: `INITIALIZED FRAMES=<num_frames> PENALTY=<fault_penalty>`

2. `ACCESS <page_id>`
   - 페이지 `<page_id>` 1개를 접근합니다.
   - 출력: `ACCESS <page_id>`

3. `ACCESS_STREAM <page_1> <page_2> ...`
   - 여러 개의 페이지를 순차적으로 접근합니다.
   - 출력: `ACCESSED <n> PAGES`

4. `STATUS`
   - 두 엔진의 현재 상태를 다음 형식으로 출력합니다:
     ```
     === FIFO ENGINE ===
     TOTAL_ACCESSES: <총 메모리 접근 횟수>
     PAGE_HITS: <적중 횟수>
     PAGE_FAULTS: <부재 횟수>
     TOTAL_COST_TICKS: <총 소요 비용 틱>
     CURRENT_FRAMES: [p1, p2, ...]
     THRASHING: <TRUE or FALSE>
     === CLOCK ENGINE ===
     TOTAL_ACCESSES: <총 메모리 접근 횟수>
     PAGE_HITS: <적중 횟수>
     PAGE_FAULTS: <부재 횟수>
     TOTAL_COST_TICKS: <총 소요 비용 틱>
     CURRENT_FRAMES: [p1, p2, ...]
     THRASHING: <TRUE or FALSE>
     ```
     *(단, `CURRENT_FRAMES`는 현재 적재된 페이지들의 Python 리스트 문자열 `['4', '2', '5']` 형태로 출력)*

---

## 4. 제약 조건

- $1 \le \text{num\_frames} \le 20$
- $1 \le \text{fault\_penalty} \le 100$
- 총 메모리 접근 횟수 $\le 2,000$
- `page_id`는 공백 없는 영문자/숫자/언더스코어 문자열

---

## 5. 입출력 예시

### 예시 입력
```
INIT 3 10 5 60.0
ACCESS_STREAM 1 2 3 4 2 5 2
STATUS
```

### 예시 출력
```
INITIALIZED FRAMES=3 PENALTY=10
ACCESSED 7 PAGES
=== FIFO ENGINE ===
TOTAL_ACCESSES: 7
PAGE_HITS: 1
PAGE_FAULTS: 6
TOTAL_COST_TICKS: 61
CURRENT_FRAMES: ['4', '5', '2']
THRASHING: TRUE
=== CLOCK ENGINE ===
TOTAL_ACCESSES: 7
PAGE_HITS: 2
PAGE_FAULTS: 5
TOTAL_COST_TICKS: 52
CURRENT_FRAMES: ['4', '2', '5']
THRASHING: TRUE
```

### 힌트 & 분석
- `1 2 3 4` 접근 후 프레임이 꽉 찬 상태에서 `2`가 접근됩니다.
- 이때 Clock 엔진은 `2`의 참조 비트를 `ref_bit = 1`로 세팅합니다.
- 다음으로 `5`가 들어왔을 때:
  - **FIFO**: 가장 먼저 들어온 `2`를 무자비하게 쫓아냅니다. 그 결과 바로 다음 `2` 접근에서 또다시 페이지 폴트가 발생하여 비용이 61틱으로 폭증합니다!
  - **CLOCK**: `2`의 비트가 1이므로 0으로 내리며 기회를 주고(Second Chance), 대신 최근에 참조되지 않은 다른 페이지를 방출합니다. 그 결과 마지막 `2` 접근에서 **적중(Hit)**을 기록하여 비용을 52틱으로 대폭 절감합니다!
