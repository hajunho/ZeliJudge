# [CS-110] 연결 1개 들어왔는데 왜 워커 100개가 동시에 깨어나서 CPU 100%를 찍어요?!: 리눅스 천둥 치는 무리(Thundering Herd)와 `EPOLLEXCLUSIVE` & `SO_REUSEPORT`

> **"선생님! 멀티코어를 활용하려고 워커 프로세스를 32개 띄우고 리슨 소켓 하나를 공유했거든요? 그런데 초당 연결이 몇천 개 들어오자마자 CPU가 100% 치솟고 서버가 먹통이 돼요! 연결 1개 들어올 때마다 32개 워커가 동시에 깨어나서 발작을 일으키는데 왜 이러죠?!"**
> 
> 고성능 HTTP 서버를 개발하던 주니어 시스템 프로그래머 하준이는 멀티프로세스 모델을 적용했습니다.
> 메인 프로세스가 `socket()`과 `bind()`, `listen()`을 수행한 뒤, `fork()`를 호출하여 32개의 워커 프로세스를 생성했습니다.
> 모든 워커는 동일한 리슨 소켓을 각자의 `epoll`에 등록하고 `epoll_wait()`를 돌렸습니다.
> 
> 하지만 벤치마크 툴(wrk)로 부하를 거는 순간, 서버는 마비되었습니다.
> 클라이언트 연결 1개가 들어올 때마다 32개의 워커 프로세스가 일제히 비명을 지르며 깨어났습니다.
> 32개 프로세스가 동시에 `accept()`를 호출해 난투극을 벌였고, 단 1개만 연결을 낚아채고 나머지 31개는 `EAGAIN (Resource temporarily unavailable)` 에러를 맞고 다시 잠들기를 무한 반복했습니다!
> 
> "연결 1개에 왜 32개가 다 깨어나서 싸우죠?!"  
> 시니어 커널 엔지니어는 씩 웃으며 리눅스 커널 소스코드를 가리켰습니다.
> "하준 씨, 컴퓨터 과학 역사상 가장 유명한 '천둥 치는 무리(Thundering Herd)'의 덫에 걸리셨군요. 들판에 먹이 1개를 던져놓고 100마리 소 떼를 동시에 깨우면 들판이 초토화되는 법입니다."

---

## 1. 문제 배경과 현실 비유: 소 떼의 폭주(Thundering Herd)

동일한 자원(예: 포트 80 리슨 소켓)을 여러 프로세스가 공유하여 대기하고 있을 때, **단 하나의 이벤트(신규 연결 1개)가 발생했음에도 커널이 대기 중이던 모든 프로세스를 한꺼번에 깨워버리는 현상**을 의미합니다.

### 참사의 메커니즘
1. 연결 1개가 들어오면, 커널이 리슨 소켓을 지켜보던 $W$개의 워커를 모두 깨웁니다.
2. $W$개의 프로세스가 동시에 `accept()`를 호출합니다.
3. 가장 먼저 도착한 1개 프로세스만 `accept()`에 성공하고, 나머지 $W - 1$개 프로세스는 `EAGAIN` 에러를 맞고 다시 잠듭니다.
4. 연결 1개를 맺기 위해 $W$번의 컨텍스트 스위칭과 CPU 캐시 스래싱이 발생하여, 트래픽이 몰리면 서버 CPU가 100%를 치며 마비됩니다.

### 리눅스의 역사적 해결책 3대장
- **`LEGACY_SHARED`**: 고전적인 공유 소켓 모델. 1개 연결당 모든 워커 동시 기상 ($W-1$회 헛기상/EAGAIN 발생).
- **`EPOLLEXCLUSIVE` (Linux 4.5+)**: epoll 등록 시 커널에 단일 기상을 요청하여, 신규 연결 시 정확히 **1개 워커만 선별 기상** (EAGAIN 0회!).
- **`SO_REUSEPORT` (Linux 3.9+)**: 각 워커가 독립된 소켓을 열어 동일 포트에 바인드하고, 커널이 4-Tuple 해시를 통해 **각 워커의 큐로 직접 1:1 분배** (락 경합 0, EAGAIN 0회!).

---

## 2. 요구사항 및 명령어 사양

당신은 리눅스 멀티프로세스 서버의 소켓 기상 아키텍처를 시뮬레이션하는 `ThunderingHerdSimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `INIT_SERVER <workers> <mode: LEGACY_SHARED|EPOLLEXCLUSIVE|SO_REUSEPORT>`
   - 서버를 초기화합니다. 워커 번호는 `0`부터 `workers - 1`까지 부여됩니다.
   - 출력: `INIT_SERVER workers=<workers> mode=<mode>`

2. `CONNECT <conn_id>`
   - 단일 연결 1개가 인입됩니다.
   - **`LEGACY_SHARED` 모드**:
     - 모든 워커($W$개)가 깨어남 (`woken_workers=workers`).
     - 워커 0이 `accept` 성공, 나머지 $W - 1$개는 `EAGAIN` 실패.
     - 출력: `CONNECT id=<conn_id> mode=LEGACY_SHARED woken_workers=<W> accepted_by=0 eagain_count=<W-1>`
   - **`EPOLLEXCLUSIVE` 모드**:
     - 정확히 1개 워커만 순차적으로 깨어남 (`target = rr_index % workers`, `rr_index += 1`).
     - 출력: `CONNECT id=<conn_id> mode=EPOLLEXCLUSIVE woken_workers=1 accepted_by=<target> eagain_count=0`
   - **`SO_REUSEPORT` 모드**:
     - 커널 해시 분배: `target = sum(ord(c) for c in conn_id) % workers`.
     - 해당 워커만 1회 깨어나서 성공.
     - 출력: `CONNECT id=<conn_id> mode=SO_REUSEPORT hash_target=<target> woken_workers=1 accepted_by=<target> eagain_count=0`

3. `BATCH_CONNECT <count> <prefix>`
   - `<count>`개의 연결을 연속으로 인입하고 요약 결과를 출력합니다.
   - 출력: `BATCH_RESULT count=<count> batch_wakeups=<wakeups> batch_accepts=<accepts> batch_eagain=<eagain> batch_wasted=<wasted>`

4. `STATS`
   - 전체 누적 통계와 워커별 처리 건수 분포를 출력합니다.
   - 출력: `STATS mode=<mode> workers=<workers> total_conn=<conn> total_wakeups=<wakeups> accepts=<accepts> eagain=<eagain> wasted_wakeups=<wasted> dist=[w0:cnt0,w1:cnt1,...]`

---

## 3. 입출력 예시

### 예시 입력 1
```text
INIT_SERVER 4 LEGACY_SHARED
CONNECT c1
CONNECT c2
STATS
INIT_SERVER 4 EPOLLEXCLUSIVE
CONNECT c1
CONNECT c2
STATS
INIT_SERVER 4 SO_REUSEPORT
CONNECT c1
CONNECT c2
STATS
```

### 예시 출력 1
```text
INIT_SERVER workers=4 mode=LEGACY_SHARED
CONNECT id=c1 mode=LEGACY_SHARED woken_workers=4 accepted_by=0 eagain_count=3
CONNECT id=c2 mode=LEGACY_SHARED woken_workers=4 accepted_by=0 eagain_count=3
STATS mode=LEGACY_SHARED workers=4 total_conn=2 total_wakeups=8 accepts=2 eagain=6 wasted_wakeups=6 dist=[w0:2,w1:0,w2:0,w3:0]
INIT_SERVER workers=4 mode=EPOLLEXCLUSIVE
CONNECT id=c1 mode=EPOLLEXCLUSIVE woken_workers=1 accepted_by=0 eagain_count=0
CONNECT id=c2 mode=EPOLLEXCLUSIVE woken_workers=1 accepted_by=1 eagain_count=0
STATS mode=EPOLLEXCLUSIVE workers=4 total_conn=2 total_wakeups=2 accepts=2 eagain=0 wasted_wakeups=0 dist=[w0:1,w1:1,w2:0,w3:0]
INIT_SERVER workers=4 mode=SO_REUSEPORT
CONNECT id=c1 mode=SO_REUSEPORT hash_target=2 woken_workers=1 accepted_by=2 eagain_count=0
CONNECT id=c2 mode=SO_REUSEPORT hash_target=3 woken_workers=1 accepted_by=3 eagain_count=0
STATS mode=SO_REUSEPORT workers=4 total_conn=2 total_wakeups=2 accepts=2 eagain=0 wasted_wakeups=0 dist=[w0:0,w1:0,w2:1,w3:1]
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **Nginx의 `reuseport` 옵션 활성화**:
   - Nginx 설정 파일(`nginx.conf`)에서 `listen 80 reuseport;`를 설정하면 커널 레벨에서 각 워커 소켓으로 연결을 직접 분산하여 천둥 치는 무리 문제를 100% 방지하고 처리량을 2~3배 끌어올릴 수 있습니다.
2. **`EPOLLEXCLUSIVE`의 역할**:
   - 단일 리슨 소켓을 공유해야만 하는 아키텍처(Python uWSGI/Gunicorn, Node.js cluster 등)에서는 `EPOLLEXCLUSIVE` 플래그를 통해 불필요한 기상과 EAGAIN 에러를 원천 차단해야 합니다.
