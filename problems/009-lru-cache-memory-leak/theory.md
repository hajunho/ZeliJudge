# 📘 [CS 이론 #009] 캐시의 배신과 메모리 누수: LRU 캐시의 마법

> **"응답 속도 높이려고 딕셔너리에 캐시를 넣었을 뿐인데 왜 3일 뒤 서버가 OOM으로 죽었을까?"**  
> 메모리 계층 구조(Memory Hierarchy), 시간 지역성, 그리고 해시 맵과 이중 연결 리스트의 결합.

---

## 1. 달콤한 인메모리 캐시의 배신

데이터베이스 쿼리가 느리거나 LLM API 호출 비용이 비쌀 때, AI 코딩 툴은 너무나 자연스럽게 다음과 같은 코드를 추천합니다:

```python
# 가장 흔하게 쓰이지만 회사를 위험에 빠뜨리는 무한 캐시
cache = {}

def get_user_profile(user_id):
    if user_id not in cache:
        cache[user_id] = db_query(user_id)  # 한 번 들어오면 영원히 메모리에 상주!
    return cache[user_id]
```

개발 환경에서는 몇 번의 테스트 후 속도가 100배 빨라졌다며 기뻐합니다.  
하지만 **이 코드는 캐시(Cache)가 아닙니다. 정확한 이름은 '메모리 누수(Memory Leak) 유발 장치'입니다.**

---

## 2. 왜 무한 딕셔너리는 서버를 죽이는가? (OOM Killer의 등장)

실제 프로덕션 환경에서는 매일 수십만 명의 사용자가 방문합니다.
* 사용자의 검색어, UUID, 일회성 토큰 등은 끊임없이 새로운 키(`key`)를 만들어냅니다.
* 3일 전 새벽 2시에 딱 한 번 로그인하고 다시는 안 오는 유저의 프로필 데이터가 `cache` 딕셔너리에 영원히 남습니다.
* 파이썬의 딕셔너리는 데이터가 늘어날 때마다 힙 메모리를 기하급수적으로 확장합니다.

```
[ 서버 RAM 사용량 추이 ]
Day 1: 500 MB (정상)
Day 2: 4.2 GB (위험)
Day 3: 15.8 GB ──► [ Linux 커널 OOM Killer 발동! ]
                      "메모리가 고갈되었습니다. 가장 메모리를 많이 먹는 프로세스를 사살합니다."
                      kill -9 python (SIGKILL) 💥 ──► 서비스 전면 마비!
```

> **컴퓨터 과학의 대원칙: 캐시 메모리는 유한하다.**  
> 메모리는 비싸고 한정된 자원입니다.  
> **"새로운 데이터를 넣을 때, 가장 가치 없는 오래된 데이터를 버리는 축출 정책(Eviction Policy)"**이 없는 캐시는 시한폭탄입니다.

---

## 3. 시간 지역성(Temporal Locality)과 LRU 알고리즘

그렇다면 캐시 용량이 꽉 찼을 때 **어떤 데이터를 버려야 가장 손해가 적을까요?**

컴퓨터 아키텍처의 가장 위대한 경험적 법칙이 있습니다:

$$\text{"최근에 참조된 데이터는 가까운 미래에 다시 참조될 가능성이 높다 (시간 지역성, Temporal Locality)}"}$$

이를 바탕으로 고안된 인류 최고의 캐시 교체 알고리즘이 바로 **LRU (Least Recently Used)**입니다:
* **"가장 오랫동안 사용(조회/수정)되지 않은 데이터를 가장 먼저 버린다!"**

---

## 4. 왜 단순 리스트나 배열로 구현하면 망할까?

AI에게 LRU를 짜달라고 하면 흔히 파이썬 리스트를 씁니다:

```python
# [나이브한 리스트 LRU - 재앙의 시작]
cache_keys = []  # 순서 기억용 리스트
cache_data = {}

def get(key):
    if key in cache_data:
        cache_keys.remove(key)     # 1. 리스트에서 찾아서 삭제: O(N) 선형 탐색!
        cache_keys.append(key)     # 2. 맨 뒤로 추가
        return cache_data[key]
```

리스트에서 특정 원소를 찾아 삭제(`remove()`)하는 연산은 리스트 전체를 뒤져야 하므로 **$O(N)$**입니다.  
캐시 용량 $C = 10,000$일 때 쿼리 10만 번을 처리하면:
$$100,000 \times 10,000 = \mathbf{10억\text{ 번의 연산 (수십 초 지연)}}!$$

캐시를 쓰는 이유는 $0.001$초 만에 빠르게 데이터를 읽으려는 것인데, **캐시 자체를 조회하는 데 $O(N)$이 걸린다면 캐시를 쓸 이유가 전혀 없습니다.**

---

## 5. 구원투수: 해시 맵(Hash Map) + 이중 연결 리스트(Doubly Linked List)

LRU 캐시의 모든 연산(`GET`, `PUT`, `Evict`)을 **완벽한 $O(1)$**으로 끝내기 위해 엔지니어들은 두 가지 자료구조를 천재적으로 결합했습니다:

```
[ LRU 캐시의 하이브리드 아키텍처 ]

   Hash Map (O(1) 주소 탐색)
┌─────────┬──────────────┐
│  Key 1  │ ──► [Node 1] │
│  Key 2  │ ──► [Node 2] │
│  Key 3  │ ──► [Node 3] │
└─────────┴──────────────┘
               ▲
               │
   Doubly Linked List (O(1) 노드 이동 및 삭제)
[ Head ] ◄──► [Node 1] ◄──► [Node 2] ◄──► [Node 3] ◄──► [ Tail ]
 (LRU: 가장 오래됨)                               (MRU: 가장 최근)
```

1. **해시 맵(Hash Map)**:
   * `key`를 주면 해당 데이터가 담긴 **노드의 메모리 주소(포인터)를 $O(1)$ 만에 즉시 반환**합니다.
2. **이중 연결 리스트(Doubly Linked List)**:
   * 각 노드는 이전 노드(`prev`)와 다음 노드(`next`)의 포인터를 가지고 있습니다.
   * 주소를 알고 있는 노드를 리스트 중간에서 떼어내어(Disconnect) 맨 뒤(`Tail`)로 옮기는 연산은 **단 4개의 포인터 변경만으로 $O(1)$에 완료**됩니다!
   * 용량이 넘쳤을 때 맨 앞(`Head`) 노드를 잘라내는 축출(Evict) 연산도 **정확히 $O(1)$**입니다.

두 자료구조가 결합함으로써 **조회(`GET`)도 $O(1)$, 삽입 및 갱신(`PUT`)도 $O(1)$, 축출(`Evict`)도 $O(1)$**이라는 기적이 완성됩니다!

---

## 6. 파이썬 실무 구현: `collections.OrderedDict`

파이썬의 표준 라이브러리 `OrderedDict`는 내부적으로 C 언어 레벨의 **해시 테이블과 이중 연결 리스트**로 완벽하게 구현되어 있습니다:

```python
from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity: int):
        self.cap = capacity
        self.cache = OrderedDict()

    def get(self, key: int) -> int:
        if key not in self.cache:
            return -1
        # 조회가 일어났으므로 가장 최근(맨 뒤)으로 O(1) 이동
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: int, value: int) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        # 용량 초과 시 가장 오래된(맨 앞, FIFO) 원소를 O(1) 축출
        if len(self.cache) > self.cap:
            self.cache.popitem(last=False)
```

더 나아가 파이썬 3에서는 단 한 줄의 데코레이터로 함수에 고성능 LRU 캐시를 붙일 수 있습니다:

```python
from functools import lru_cache

@lru_cache(maxsize=1000)  # 최대 1,000개만 보관하는 완벽한 O(1) LRU 캐시!
def get_user_profile(user_id):
    return db_query(user_id)
```

---

## 💡 AI 바이브 코더를 위한 실무 체크리스트
1. **용량 제한(`maxsize` 또는 `TTL`)이 없는 전역 딕셔너리를 캐시로 쓰지 마세요.** 무조건 메모리 누수로 이어져 언젠가 서버가 OOM으로 폭파됩니다.
2. **함수 캐싱이 필요하다면 `@functools.lru_cache(maxsize=N)`을 적극 활용하세요.**
3. **Redis 등 외부 캐시를 쓸 때도 반드시 `maxmemory-policy allkeys-lru`를 설정하세요.**
