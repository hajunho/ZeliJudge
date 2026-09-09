# 082 - 메모리가 500MB나 남았는데 왜 64MB 할당에서 OOM이 터져요?!: 메모리 외부 단편화와 리눅스 버디 할당자 (Memory External Fragmentation & Buddy Allocator)

## 1. 현실 비유 & 배경 스토리

총 100대의 승용차를 댈 수 있는 대형 주차장이 있습니다. 🚗🅿️  
현재 주차장에 50대의 승용차가 주차되어 있고, 전광판에는 **"잔여 빈자리: 50칸"**이라고 초록색 불이 켜져 있습니다.

그때 단체 관광객 40명을 태운 대형 버스 1대가 주차장에 도착했습니다.  
버스는 4칸의 연속된 주차 공간이 필요합니다.

```text
[주차장 실제 현황]
[차][빈][차][빈][차][빈][차][빈][차][빈] ... [차][빈]
(승용차들이 1칸씩 퐁당퐁당 주차되어 있음)
```

주차장 관리원이 난처한 표정으로 버스 기사에게 말합니다:  
> **"기사님 죄송합니다. 빈자리는 50칸이나 되지만, 연속으로 4칸 비어있는 곳이 한 군데도 없어서 주차하실 수 없습니다!"**

버스 기사는 분통을 터뜨립니다:  
> **"아니, 빈자리가 50칸이나 남아있는데 왜 주차를 못 해?!"**

결국 버스는 주차하지 못하고 쫓겨납니다 (할당 실패, Out of Memory).

이 비극이 바로 운영체제(OS) 커널, 저수준 C/C++/Rust 엔진, GPU VRAM 관리, 고성능 네트워크 버퍼(Netty DirectByteBuffer)에서 끊임없이 발생하는 **외부 단편화 (External Fragmentation)**입니다.

메모리의 할당과 해제가 반복되면서 작은 자투리 메모리들이 모자이크처럼 흩어지면, **총 여유 메모리는 수백 MB가 남아있어도 연속된 물리 메모리를 확보하지 못해 시스템이 OOM으로 폭사**합니다.

리눅스 커널의 물리 메모리 관리자(Page Frame Allocator)는 1963년 고안된 **버디 시스템 (Buddy Allocator)**을 통해 이 문제를 해결합니다.  
메모리를 항상 2의 거듭제곱($2^k$) 크기의 이진 트리 블록으로 관리하며, 할당 시에는 큰 블록을 절반으로 재귀 분할(Split)하고, 해제 시에는 인접한 쌍둥이 짝꿍(Buddy) 블록을 **$O(1)$ 비트 XOR 연산(`addr ^ size`)**으로 찾아내 즉시 상위 블록으로 연쇄 병합(Coalesce)함으로써 단편화를 실시간으로 자가 치유(Self-compacting)합니다.

당신은 리눅스 커널의 버디 할당자를 직접 시뮬레이션하여, 메모리 분할 및 짝꿍 병합 메커니즘과 외부 단편화율을 계산해야 합니다!

---

## 2. 버디 시스템 상세 알고리즘 사양

메모리 풀 전체 크기 $M$은 항상 2의 거듭제곱($M = 2^K$)이며, 주소는 $0$부터 $M-1$까지입니다.  
블록의 크기는 항상 2의 거듭제곱($1, 2, 4, 8, \dots, M$)입니다.

### 1) 크기 올림 (Power-of-Two Rounding)
요청된 크기 `size`에 대해, 이를 수용할 수 있는 최소 2의 거듭제곱 크기 $target\_size = 2^k \ge size$를 계산합니다.  
(예: size=5 $\to$ target_size=8, size=16 $\to$ target_size=16)

### 2) 메모리 할당 (`ALLOC <req_id> <size>`)
1. 프리 리스트에서 크기가 $target\_size$ 이상인 가용 블록 중 **가장 작은 크기 $S$**의 블록을 찾습니다.
2. 만약 $S > M$ (수용 가능한 블록이 없음): `ALLOC_FAILED <req_id> (OOM)` 반환.
3. 해당 크기 $S$의 가용 블록 중 **시작 주소(`addr`)가 가장 작은 블록**을 꺼냅니다 (결정론적 Tie-breaker).
4. 만약 $S > target\_size$라면, $target\_size$가 될 때까지 블록을 절반씩 **재귀적으로 쪼갭니다(Split)**:
   - 쪼개질 때마다 남은 반쪽 짝꿍 블록(`addr + S/2`)은 크기 $S/2$의 프리 리스트에 반환합니다.
5. 최종적으로 크기 $target\_size$인 블록을 `req_id`에 할당하고 주소와 블록 크기를 반환합니다.

### 3) 메모리 해제 및 짝꿍 병합 (`FREE <req_id>`)
1. `req_id`에 할당된 블록의 시작 주소 $A$와 블록 크기 $S$를 가져옵니다.
2. **재귀적 짝꿍 병합 (Coalescing)**:
   - 짝꿍 블록의 주소는 비트 XOR로 계산합니다:
     $$\text{buddy\_addr} = A \oplus S$$
   - 만약 $S < M$이고, 주소 $\text{buddy\_addr}$의 블록이 **크기 $S$의 프리 리스트에 현재 존재한다면**:
     - 짝꿍 블록을 프리 리스트에서 제거합니다.
     - 두 블록을 병합하여 크기 $2S$인 상위 블록을 생성합니다 (시작 주소: $\min(A, \text{buddy\_addr})$).
     - 병합 횟수(`merges`)를 1 증가시키고, $A = \min(A, \text{buddy\_addr})$, $S = 2S$로 갱신한 뒤 상위 짝꿍과 계속 병합을 시도합니다.
   - 짝꿍이 사용 중이거나 다른 크기로 쪼개져 있다면 병합을 멈추고, 현재 블록 $(A, S)$를 크기 $S$의 프리 리스트에 삽입합니다.
3. 총 병합 횟수(`merges`)를 반환합니다.

---

## 3. 입력 명령 프로토콜

표준 입력(stdin)으로 다음 명령어들이 한 줄씩 주어집니다:

1. `INIT <total_size>`
   - 전체 메모리 크기 $M$ (2의 거듭제곱 정수, $1 \le M \le 65,536$)으로 할당자를 초기화합니다.
   - 출력: `INITIALIZED MEMORY_SIZE=<total_size>`

2. `ALLOC <req_id> <size>`
   - `size` 크기의 메모리 할당을 요청합니다.
   - 출력:
     - 성공 시: `ALLOCATED <req_id> ADDR=<addr> BLOCK_SIZE=<block_size>`
     - 실패 시: `ALLOC_FAILED <req_id> (OOM)`

3. `FREE <req_id>`
   - `req_id`에 할당된 메모리를 해제하고 연쇄 짝꿍 병합을 수행합니다.
   - 출력:
     - 성공 시: `FREED <req_id> (MERGES: <merges>)`
     - 실패 시 (존재하지 않거나 이미 해제됨): `FREE_FAILED <req_id>`

4. `STATUS`
   - 현재 메모리 풀의 상태를 다음 형식으로 출력합니다:
     ```
     TOTAL_MEMORY: <전체 메모리 크기>
     USED_MEMORY: <현재 할당 중인 블록 크기의 총합>
     FREE_MEMORY: <현재 가용 메모리 총합>
     MAX_CONTIGUOUS_FREE: <가장 큰 단일 연속 여유 블록 크기 (없으면 0)>
     FRAGMENTATION_RATIO: <외부 단편화 비율 %>
     FREE_BLOCKS: <가용 블록 크기별 개수 딕셔너리>
     ```
   - **외부 단편화율 계산식**:
     $$\text{FREE\_MEMORY} == 0 \implies 0.00\%$$
     $$\text{FREE\_MEMORY} > 0 \implies \left(1.0 - \frac{\text{MAX\_CONTIGUOUS\_FREE}}{\text{FREE\_MEMORY}}\right) \times 100\%$$
     *(소수점 둘째 자리까지 `XX.XX%` 형식으로 출력)*
   - `FREE_BLOCKS`는 가용 블록이 1개 이상 존재하는 크기만 오름차순 정렬하여 Python 딕셔너리 문자열 `{16: 1, 32: 1}` 형태로 출력합니다. (가용 블록이 없으면 `{}`)

---

## 4. 제약 조건

- $1 \le \text{total\_size} \le 65,536$ (반드시 2의 거듭제곱)
- $1 \le \text{size} \le \text{total\_size}$
- 총 명령어 수 $\le 5,000$
- `req_id`는 공백 없는 영문자/숫자/언더스코어 문자열

---

## 5. 입출력 예시

### 예시 입력
```
INIT 64
ALLOC A 16
ALLOC B 16
STATUS
FREE A
STATUS
FREE B
STATUS
ALLOC HUGE 64
STATUS
```

### 예시 출력
```
INITIALIZED MEMORY_SIZE=64
ALLOCATED A ADDR=0 BLOCK_SIZE=16
ALLOCATED B ADDR=16 BLOCK_SIZE=16
TOTAL_MEMORY: 64
USED_MEMORY: 32
FREE_MEMORY: 32
MAX_CONTIGUOUS_FREE: 32
FRAGMENTATION_RATIO: 0.00%
FREE_BLOCKS: {32: 1}
FREED A (MERGES: 0)
TOTAL_MEMORY: 64
USED_MEMORY: 16
FREE_MEMORY: 48
MAX_CONTIGUOUS_FREE: 32
FRAGMENTATION_RATIO: 33.33%
FREE_BLOCKS: {16: 1, 32: 1}
FREED B (MERGES: 2)
TOTAL_MEMORY: 64
USED_MEMORY: 0
FREE_MEMORY: 64
MAX_CONTIGUOUS_FREE: 64
FRAGMENTATION_RATIO: 0.00%
FREE_BLOCKS: {64: 1}
ALLOCATED HUGE ADDR=0 BLOCK_SIZE=64
TOTAL_MEMORY: 64
USED_MEMORY: 64
FREE_MEMORY: 0
MAX_CONTIGUOUS_FREE: 0
FRAGMENTATION_RATIO: 0.00%
FREE_BLOCKS: {}
```

### 힌트 & 분석
1. `FREE A` (주소 0, 크기 16) 후:
   - 짝꿍인 주소 16(B)이 아직 사용 중이므로 병합할 수 없습니다 (`MERGES: 0`).
   - 가용 블록은 16바이트 1개와 32바이트 1개로 나뉩니다 (`FREE_BLOCKS: {16: 1, 32: 1}`).
   - 총 여유 메모리는 48이지만 최대 연속 블록은 32이므로, **외부 단편화율 33.33%**가 발생합니다!
2. `FREE B` (주소 16, 크기 16) 후:
   - 주소 16의 짝꿍은 주소 0($16 \oplus 16 = 0$)이며, 주소 0이 비어있으므로 크기 32 블록으로 1차 병합됩니다 (주소 0, 크기 32).
   - 이어서 크기 32 블록의 짝꿍인 주소 32($0 \oplus 32 = 32$)도 비어있으므로, 크기 64 블록으로 2차 병합됩니다 (`MERGES: 2`)!
   - 쪼개졌던 메모리가 완벽하게 64바이트 단일 블록으로 복원되며 **단편화율 0.00%**로 자가 치유됩니다!
3. `ALLOC HUGE 64`:
   - 복원된 64바이트 연속 공간 덕분에 64바이트 대형 요청이 단 한 번의 실패도 없이 깔끔하게 할당됩니다!
