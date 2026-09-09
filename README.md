# 🧠 ZeliJudge (젤리저지)

> **"AI 바이브 코더(Vibe Coder)를 진짜 소프트웨어 엔지니어로 진화시키는 컴퓨터 과학 & 알고리즘 오픈 저지"**  
> An open-source, community-driven algorithm & computer science judge for AI-native developers.

---

## 🌟 프로젝트 비전과 철학 (Why ZeliJudge?)

최근 Cursor, GitHub Copilot, ChatGPT, Claude 등 강력한 AI 코딩 도구들이 등장하면서, 문법을 외우지 않고도 자연어로 명령하여 소프트웨어를 만드는 **'바이브 코딩(Vibe Coding)'**의 시대가 열렸습니다.

그러나 AI가 짜준 코드로 서비스를 런칭한 수많은 개발자들이 실무에서 **치명적인 재앙**을 마주합니다:
* *"100개 테스트할 땐 빨랐는데, 유저 10만 명이 되자 서버가 10분째 멈춰요..."* (시간 복잡도 O(N²)의 함정)
* *"쇼핑몰 결제 합산에서 거스름돈 1원이 계속 비어요..."* (IEEE 754 부동소수점 오차)
* *"폴더를 조금 깊게 탐색시켰더니 프로그램이 에러도 없이 꺼져요..."* (재귀 콜 스택 오버플로우)
* *"비동기로 DB에 잔액을 깎았는데 계좌에 돈이 복사돼요..."* (Race Condition 동시성 이슈)

**AI는 코드를 빠르게 써줄 수 있지만, 컴퓨터 시스템의 물리적 한계(메모리, CPU 클럭, 레지스터, 캐시)를 대신 책임져 주지 않습니다.**

`ZeliJudge`는 단순한 취업용 알고리즘 퍼즐 사이트가 아닙니다.  
**"AI 코딩 도구에만 의존하던 개발자가 반드시 알아야 할 컴퓨터 과학(CS)의 본질적 뼈대와 실무 트러블슈팅 소양"**을 이론과 문제로 함께 제공하는 공공 오픈소스 프로젝트입니다.

---

## 📂 문제 세트 표준 구조 (Standard Problem Structure)

모든 문제는 누구나 읽고 기여할 수 있도록 순수 **Markdown(`.md`) 및 JSON**으로 구성됩니다:

```
problems/
 └── [문제번호]-[문제슬러그]/
      ├── problem.md       <- 실무 버그 시나리오, 입출력 정의, 제약조건, 입출력 예시
      ├── theory.md        <- 이 문제가 다루는 핵심 Computer Science 이론 백서
      ├── testcases.json   <- 채점용 입출력 데이터셋 (공개 예제 + 대용량 엣지케이스)
      └── solution.py      <- 모범 정답 풀이 코드 및 복잡도 분석
```

---

## 🚀 문제 목록 (Problem Index)

| 번호 | 문제명 | 핵심 CS 이론 | 실무 시나리오 |
|:---:|---|---|---|
| **#001** | [10만 건 데이터 참사: O(N²)의 늪과 해시 검색](problems/001-big-o-hash-search/problem.md) | **시간 복잡도 (Big-O)**, 해시 테이블 O(1) vs 선형 탐색 O(N) | AI가 짜준 중복 유저 필터링으로 서버가 먹통이 된 사건 |
| **#002** | [사라진 1원의 저주: IEEE 754 부동소수점](problems/002-floating-point-trap/problem.md) | **컴퓨터의 실수 표현 (IEEE 754)**, 2진수 소수 변환의 한계 | 장바구니 결제 합산에서 0.1 + 0.2 != 0.3 오차 발생 |
| **#003** | [순진한 재귀함수의 최후: 콜 스택 오버플로우](problems/003-call-stack-overflow/problem.md) | **콜 스택(Call Stack) 프레임**, 재귀(Recursion)와 반복문 변환 | 디렉토리 구조 순회 중 깊은 폴더에서 프로세스 강제 종료 |
| **#004** | [비동기의 배신과 한정판 티켓 참사: Race Condition & Mutex](problems/004-race-condition-mutex/problem.md) | **동시성 제어(Concurrency)**, 경쟁 상태, 원자성(Atomicity), 뮤텍스 락 | 비동기로 짠 티켓팅/포인트 차감에서 동시 클릭으로 잔고 마이너스(-380) 발생 |
| **#005** | [문자열 덧셈의 늪: 불변 객체(Immutable)와 메모리 복사 지옥](problems/005-string-immutability/problem.md) | **메모리 구조**, 문자열 불변성(Immutability), $O(N^2)$ 메모리 복사, 가변 버퍼와 `join()` | 10만 건 로그를 `+=`로 합치다가 1시간 동안 서버 멈춘 사건 |
| **#006** | [쿼리 지옥과 DB 사망: N+1 문제와 스트리밍 집계](problems/006-n-plus-one-generator/problem.md) | **데이터베이스 인덱싱**, N+1 쿼리 최적화, 해시 맵 그룹핑, Eager Loading vs 지연 평가 | 루프 안에서 주문상품을 개별 쿼리하다가 DB 커넥션 풀 고갈 및 OOM 폭발 |
| **#007** | [정렬의 배신과 최악의 분할: 퀵소트 O(N²) 함정과 Timsort](problems/007-quicksort-worst-case/problem.md) | **분할 정복**, 퀵소트 최악 시간 복잡도($O(N^2)$), 3-Way 분할, Timsort 하이브리드 원리 | 이미 정렬된 체결 데이터에서 퀵소트가 $O(N^2)$로 10분간 멈춰버린 참사 |
| **#008** | [끝없는 폴링과 소켓 고갈: Polling vs Event-Driven](problems/008-polling-vs-event-driven/problem.md) | **네트워크 I/O 모델**, Short Polling의 비극, 이벤트 기반 푸시, I/O 다중화(epoll/웹소켓) | 0.1초마다 상태 확인 요청을 날리다가 소켓 FD 고갈로 서버실 폭파된 사건 |
| **#009** | [캐시의 배신과 메모리 누수: LRU 캐시의 마법](problems/009-lru-cache-memory-leak/problem.md) | **메모리 계층 구조**, 캐시 지역성(Locality), 해시 맵 + 이중 연결 리스트 $O(1)$ LRU 캐시 | 무한 증식 딕셔너리 캐시로 인해 3일 뒤 리눅스 OOM Killer로 프로세스 사살된 사건 |
| **#010** | [복사했는데 왜 둘 다 바뀌어?: 얕은 복사와 참조의 덫](problems/010-shallow-vs-deep-copy/problem.md) | **메모리 참조(Reference)**, 변수의 본질(포스트잇), 얕은 복사(Shallow) vs 깊은 복사(Deep) | 게임 인벤토리 복사 후 강화 취소했는데 원본까지 같이 깎여버린 버그 |
| **#011** | [반복문에서 지웠는데 왜 남아?: 기차 좌석과 인덱스 시프트의 저주](problems/011-iterating-mutation-trap/problem.md) | **자료구조와 반복자(Iterator)**, 인덱스 시프트(Index Shift), 불변 리스트 컴프리헨션 vs 필터링 | 채팅 금지어 연속 필터링 루프 돌렸는데 욕설이 절반이나 살아남아 검열 뚫린 참사 |
| **#012** | [남의 장바구니에 내 물건이 왜 있어?: 가변 기본 인자(Mutable Default)의 저주](problems/012-mutable-default-argument/problem.md) | **언어 런타임**, 정의 시점(Definition Time) vs 호출 시점, 함수의 `__defaults__` 속성, None 센티넬 패턴 | 장바구니 기본 인자를 `cart=[]`로 뒀다가 이전 손님 물건이 다음 손님에게 유출된 참사 |
| **#013** | [256은 되고 257은 왜 안 돼?: 값(Equality)과 주소(Identity)의 배신 (is vs ==)](problems/013-equality-vs-identity/problem.md) | **메모리 아키텍처**, 값(Value) vs 객체 주소(Identity), Small Integer Cache(-5~256), 문자열 인터닝 | 250원 테스트는 다 통과했는데 300원부터 결제 승인 거절된 `is` 비교 참사 |
| **#014** | [닫히지 않는 문과 사라진 손잡이: 파일 디스크립터(FD) 누수와 with 문의 구원](problems/014-file-descriptor-leak/problem.md) | **운영체제 커널**, 파일 디스크립터(FD) 한도(`ulimit`), RAII 패턴, 컨텍스트 매니저(`with`)의 `__exit__` 보장 | 예외 발생 시 `close()` 건너뛰어 서버의 모든 소켓/파일이 마비된 참사 |
| **#015** | [비밀번호를 그냥 해시하면 털려요!: 레인보우 테이블과 솔트(Salt)의 방패](problems/015-password-hash-and-salt/problem.md) | **정보보안/암호학**, 단방향 해시(SHA-256)의 한계, 레인보우 테이블(역추적 사전), 솔트(Salt)의 2대 방어 원리 | 단순 해시로 DB 저장했다가 레인보우 테이블로 0.001초 만에 전 회원 비밀번호 털린 참사 |
| **#016** | [사라진 공지사항과 식탐 괴물: 정규표현식 탐욕적(Greedy) vs 게으른(Lazy) 매칭](problems/016-regex-greedy-vs-lazy/problem.md) | **오토마타/문자열 파싱**, 정규식 엔진의 탐욕적 수량자(`.*`), 백트래킹과 최장 일치, 게으른 수량자(`.*?`) | HTML 태그 지우려다 첫 태그부터 끝 태그 사이 공지사항 본문 전체가 증발한 참사 |
| **#017** | [9시간 늦게 산 사람이 1등?: 시간대(Timezone)의 덫과 UTC 절대 시계](problems/017-timezone-and-utc/problem.md) | **글로벌 시간/분산 시스템**, Naive vs Aware Datetime, Unix Epoch Time, ISO 8601 및 서머타임 | 시차 오프셋 무시하고 날짜 문자열로 정렬했다가 해외 선착순 구매 순위 뒤바뀐 참사 |
| **#018** | [롤러코스터 대기열과 50억 번의 발걸음: list.pop(0) vs collections.deque](problems/018-queue-shift-vs-deque/problem.md) | **자료구조/메모리 물리배치**, 동적 배열의 원소 메모리 시프트($O(N)$), 이중 연결 리스트 덱($O(1)$) | 10만 명 대기열에서 `pop(0)` 썼다가 50억 번 메모리 복사로 서버 CPU 100% 뻗은 참사 |
| **#019** | [C++을 검색했는데 왜 C가 나와?: URL 인코딩(Percent-Encoding)과 예약어의 배신](problems/019-url-percent-encoding/problem.md) | **네트워크/웹 프로토콜**, RFC 3986 퍼센트 인코딩, 예약어 충돌(`+`, `&`, `#`), 쿼리 파라미터 파싱 왜곡 | f-string으로 URL 조립했다가 `+`는 공백, `&`/`#`은 잘려나가 검색어 다 훼손된 참사 |
| **#020** | [도서관 신청서에 불을 지르다: SQL Injection과 파라미터 바인딩](problems/020-sql-injection-prepared-stmt/problem.md) | **정보보안/데이터베이스**, Code as Data vs Data as Code, AST 파싱 왜곡, Prepared Statement | f-string으로 쿼리 합쳤다가 주석 공격(`--`)과 `' OR '1'='1`로 최고관리자 털린 참사 |
| **#021** | [async로 짰는데 왜 1초씩 멈춰요?: 이벤트 루프와 블로킹 I/O의 배신](problems/021-asyncio-event-loop-blocking/problem.md) | **비동기 런타임/동시성**, 싱글 스레드 이벤트 루프, 협력적 멀티태스킹, time.sleep() 동결 지연 | FastAPI에 무심코 time.sleep() 넣었다가 전 사용자 화면이 2초씩 멈춘 참사 |
| **#022** | [로컬에선 되는데 왜 배포하니까 빨간 줄이 떠요?: CORS와 Preflight](problems/022-cors-preflight-handshake/problem.md) | **웹 보안/HTTP 프로토콜**, 동일 출처 정책(SOP), OPTIONS 정찰병(Preflight), 와일드카드 크레덴셜 모순 | Postman에선 잘 되는데 브라우저에서만 빨간 에러 뜨고 OPTIONS 405로 본 요청 사살된 참사 |
| **#023** | [A는 B를 기다리고 B는 A를 기다린다: 데드락과 락 획득 순서의 저주](problems/023-deadlock-lock-ordering/problem.md) | **동시성 제어/운영체제**, 코프먼 4대 조건, 원형 대기(Circular Wait), 글로벌 락 정렬(Global Lock Ordering) | 맞송금 트랜잭션에서 서로 상대 계좌 락을 기다리며 CPU 0%로 서버 침묵 마비된 참사 |
| **#024** | [새로고침 5번 눌렀더니 결제가 5번 됐어요?!: 멱등성과 멱등키](problems/024-api-idempotency-key/problem.md) | **분산 시스템/API 설계**, 멱등성(Idempotency), 네트워크 타임아웃 재시도, 멱등키(Idempotency-Key) 캐시 재생 | 결제 중 와이파이 단절로 새로고침 광클했다가 5번 중복 결제 터져 통장 털린 참사 |
| **#025** | [1초에 1,000명이 몰려왔다!: 처리율 제한 장치와 토큰 버킷](problems/025-rate-limiting-token-bucket/problem.md) | **시스템 아키텍처/트래픽 제어**, 토큰 버킷(Token Bucket), 버스트(Burst) 트래픽 수용, 지연 충전(Lazy Refill) | 무료 AI API 열었다가 무한 루프 매크로 폭탄 맞아 DB 터지고 수백만 원 과금된 참사 |
| **#026** | [캐시가 만료된 그 1초, DB가 폭발했다: 캐시 스탬피드와 뮤텍스](problems/026-cache-stampede-mutex/problem.md) | **캐싱 아키텍처/성능 최적화**, 캐시 스탬피드(Cache Stampede), 동시 DB 돌진, 싱글플라이트(Singleflight) 락 | 인기 검색어 캐시 만료 순간 수백 개 쿼리 동시 폭주로 DB 커넥션 풀 사망한 참사 |
| **#027** | [옆 동네 서버가 터졌는데 우리 서버까지 죽어요?: 서킷 브레이커](problems/027-circuit-breaker-pattern/problem.md) | **분산 시스템/장애 격리**, 서킷 브레이커(Circuit Breaker), 연쇄 장애(Cascading Failure), FSM 상태 머신 | 외부 카드사 화재로 30초 타임아웃 기다리다 우리 쇼핑몰 스레드 풀 전멸한 참사 |
| **#028** | [서버 1대 늘렸더니 캐시 99%가 날아갔어요?!: 안정 해시(Consistent Hashing)](problems/028-consistent-hashing/problem.md) | **분산 해싱/샤딩**, 모듈로 연산($\% N$)의 재배치 저주($\frac{N}{N+1}$), 원형 링(Ring)과 $O(\log N)$ 안정 해시 | 캐시 서버 1대 증설했다가 캐시 적중률 0%로 곤두박질치며 DB 폭발한 참사 |
| **#029** | [존재하지 않는 1억 개의 유령 아이디를 조회해서 DB를 죽였다?!: 블룸 필터(Bloom Filter)](problems/029-bloom-filter/problem.md) | **확률적 자료구조**, 캐시 관통(Cache Penetration) 방어, 비트 배열과 다중 해시, 거짓 긍정(False Positive)과 $O(K)$ 필터 | 무작위 유령 아이디 10만 건 DDoS 공격에 캐시 뚫리고 DB 커넥션 풀 사망한 참사 |
| **#030** | [결제 트랜잭션 안에서 카카오페이 외부 API를 불렀더니 DB가 멈췄어요?!: 커넥션 풀(HikariCP)](problems/030-connection-pool-exhaustion/problem.md) | **DB 아키텍처/동시성**, 커넥션 풀(HikariCP) 고갈, 트랜잭션 경계 분리(Lean Transaction), 리틀의 법칙 | 트랜잭션 안에서 3초 외부 결제 API 호출했다가 커넥션 고갈로 전사 시스템 올스톱된 참사 |
| **#031** | [쓰기가 왜 이렇게 빨라요?!: LSM-Tree와 MemTable/SSTable 컴팩션](problems/031-lsm-tree-memtable/problem.md) | **스토리지 엔진/I/O 모델**, 디스크 랜덤 I/O vs 순차 쓰기(Append-Only), MemTable 플러시, SSTable K-Way 병합 컴팩션 | 초당 수만 건 로그 RDB에 넣다가 디스크 I/O 100% 찍고 서버 뻗어버린 참사 |
| **#032** | [동시에 상품 수정 눌렀더니 이전 사람 수정한 게 통째로 날아갔어요?!: 갱신 분실과 락](problems/032-optimistic-vs-pessimistic-lock/problem.md) | **동시성 제어/DB 트랜잭션**, 갱신 분실(Lost Update), 버전 기반 낙관적 락(OCC) vs 배타적 비관적 락(PCC) | 두 MD가 동시에 상품 수정했다가 이전 사람 수정한 100페이지가 감쪽같이 사라진 참사 |
| **#033** | [파일 1GB 보냈을 뿐인데 CPU가 100% 찍고 뻗었어요?!: Zero-Copy의 마법](problems/033-zero-copy-memory-transfer/problem.md) | **운영체제 I/O/네트워크**, 커널 모드 vs 유저 모드 4회 컨텍스트 스위칭, CPU 2회 메모리 복사 vs Zero-Copy(`sendfile`) | 정적 동영상 서빙하다 CPU 100% 병목으로 전사 다운로드 멈춘 참사 |
| **#034** | [조회수 1 올라갈 때마다 DB UPDATE 쳤더니 DB가 터졌어요?!: Write-Back 캐시](problems/034-write-back-cache-flush/problem.md) | **캐시 쓰기 전략/배치 처리**, 행 단위 배타락(X-Lock) 경합, Write-Through vs Write-Back, 크기/시간 기반 배치 플러시 | 초당 3천 번 조회수 UPDATE 때리다 DB 커넥션 풀 고갈 사망한 참사 |
| **#035** | [주문은 성공했는데 결제가 취소되면 어떡하죠?!: 2PC vs Saga 패턴](problems/035-two-phase-commit-vs-saga/problem.md) | **분산 트랜잭션/MSA**, 2PC 동기 블로킹/SPOF vs Saga 보상 트랜잭션(Compensating Transaction) 역순 롤백 | DB 쪼갰다가 결제 실패 시 주문/재고 롤백 안 되어 데이터 불일치 터진 참사 |
| **#036** | [인덱스를 5개나 걸었는데 왜 10초나 걸려요?!: 복합 인덱스와 Leftmost Prefix의 저주](problems/036-composite-index-leftmost-prefix/problem.md) | **DB 인덱싱/옵티마이저**, B-Tree 사전식 다차원 정렬, Leftmost Prefix 규칙, 등치(=) vs 범위(RANGE) 무력화 경계, 최적 인덱스 재배치 | AI가 짜준 복합 인덱스 믿었다가 첫 컬럼 누락 및 범위 조건 뒤 컬럼 인덱스 무효화로 슬로우 쿼리 폭사한 참사 |
| **#037** | [방금 글 썼는데 새로고침하니 사라졌어요?!: DB 복제 지연과 Read-Your-Own-Writes](problems/037-replication-lag-read-your-writes/problem.md) | **분산 데이터베이스/복제**, Master-Slave 비동기 복제 지연, Monotonic Read 붕괴, Time Window vs LSN 기반 정밀 라우팅 | DB 분산하겠다고 Slave로 보냈다가 글 작성 직후 404 및 구버전 노출로 중복 작성 폭탄 터진 참사 |
| **#038** | [새로고침 10번 눌렀더니 똑같은 알림이 10개 왔어요?!: 메시지 큐 At-Least-Once와 컨슈머 멱등성](problems/038-message-queue-idempotent-consumer/problem.md) | **메시지 큐/비동기 처리**, At-Least-Once 전달 보장, ACK 타임아웃 재전송, 2단계 멱등 컨슈머(Message ID & Business Key) | 비동기 큐 도입 후 네트워크 재전송과 결제 광클로 1명에게 쿠폰/알림 5연타 중복 지급된 대형 손실 사고 |
| **#039** | [서버 3대로 늘렸더니 로그인 세션이 자꾸 풀려요?!: Sticky Session vs Redis 분산 세션 vs JWT](problems/039-session-consistency-redis-jwt/problem.md) | **웹 아키텍처/세션 클러스터링**, 무상태(Stateless) 웹 서버, 라운드로빈 세션 불일치, Sticky Session 한계 vs Redis 중앙 분산 세션 | 서버 스케일아웃 후 클릭할 때마다 '로그인이 필요합니다'로 튕겨나가고 서버 재기동 시 세션 증발한 참사 |
| **#040** | [DB 1대에 1억 건이 넘어가니 죽으려고 해요?!: 데이터베이스 샤딩과 리밸런싱](problems/040-database-sharding-rebalancing/problem.md) | **분산 스토리지/샤딩**, 수평 분할(Sharding), 모듈로 해시의 재배치 저주($\frac{K}{K+1}$) vs 디렉토리 샤딩 선택적 리밸런싱 | 단일 DB 용량 폭발 후 샤드 1대 증설했다가 데이터 80%를 다른 DB로 이사보내느라 3일간 서비스 마비된 참사 |
| **#041** | [동시에 좋아요를 1,000명이 눌렀더니 숫자가 50밖에 안 올라가요?!: 분산 카운터와 샤디드 카운터](problems/041-distributed-sharded-counter/problem.md) | **동시성 제어/분산 카운터**, 단일 행 배타락(X-Lock) 경합, Lock Wait Timeout 폭발 방어, 샤디드 카운터(Sharded Counter) 병렬 확장 | 실시간 라이브 방송에서 10만 명이 동시 하트 연타하다 단일 행 UPDATE 락 대기열 폭발로 99% 요청 롤백된 참사 |
| **#042** | [DB가 잠깐 끊겼는데 왜 서버 100대가 전부 강제 재부팅돼요?!: 헬스체크와 Liveness vs Readiness Probe](problems/042-health-check-liveness-readiness/problem.md) | **클라우드 네이티브/인프라**, 쿠버네티스 헬스체크 3총사, 딥 헬스체크 안티패턴, 연쇄 재시작 폭풍(Cascading Restart Storm) 방어 | 외부 DB 3초 지연에 딥 헬스체크 걸어뒀다가 100대 파드 동시 재부팅으로 DB 영구 폭사한 참사 |
| **#043** | [로그를 많이 남겼더니 서버가 멈췄어요?!: 동기식 로깅 vs 비동기 링 버퍼(Disruptor Ring Buffer)](problems/043-async-logging-ring-buffer/problem.md) | **시스템 아키텍처/I/O 모델**, 파일 쓰기 배타락 병목, LMAX Disruptor 링 버퍼, 배치 I/O 플러시, 지능형 드롭 정책(discardingThreshold) | 디버깅한다고 logger.info 남발했다가 디스크 I/O 락 경합으로 톰캣 스레드 풀 고갈 서버 다운된 참사 |
| **#044** | [DB 타임아웃을 3초로 걸었는데 왜 60초 동안 안 풀려요?!: 네트워크 소켓 타임아웃의 3대 덫 (Connect vs Socket Read vs Statement Timeout)](problems/044-socket-timeout-layering/problem.md) | **네트워크/분산 시스템**, TCP SYN 지수 백오프(127초), 방화벽 패킷 블랙홀(Silent Drop), 4대 타임아웃 위계질서, 스레드 기아(Thread Starvation) 방어 | 쿼리 타임아웃만 믿고 소켓 타임아웃 누락했다가 방화벽 드롭 시 127초간 스레드 풀 전멸한 참사 |
| **#045** | [카프카 컨슈머를 10대로 늘렸는데 왜 3대만 일해요?!: 파티션(Partition)과 컨슈머 그룹의 1:1 매핑 법칙](problems/045-kafka-partition-consumer-mapping/problem.md) | **메시지 브로커/스트리밍**, 카프카 파티션 순서 보장 철칙, Range vs RoundRobin 할당 전략, 리밸런싱, 유휴 컨슈머(Idle) 자원 낭비 방어 | 메시지 밀린다고 컨슈머 10대로 늘렸다가 파티션 3개 병목으로 7대가 놀며 서버비만 날린 참사 |
| **#046** | [외부 API 5개 불렀을 뿐인데 응답이 15초나 걸려요?!: 직렬 동기 호출 vs 병렬 비동기 I/O (Async Fan-Out / Gather)](problems/046-parallel-fanout-async-gather/problem.md) | **비동기 프로그래밍/분산 I/O**, 직렬 지연($\sum T_i$) vs 병렬 지연($\max T_i$), Fan-Out/Fan-In, Fail-Fast vs All-Settled 우아한 저하 | 외부 API를 for 루프 순차 호출했다가 지연시간 10초 돌파로 전 사용자 화면 멈춰버린 참사 |
| **#047** | [100장 한정 쿠폰인데 왜 105장이 발급돼요?!: 트랜잭션 격리 수준(Isolation Level)과 팬텀 리드(Phantom Read)](problems/047-transaction-isolation-phantom-read/problem.md) | **DB 트랜잭션/동시성**, ANSI SQL 4대 격리 수준, MVCC 스냅샷 격리의 한계, 넥스트 키 락(Next-Key Lock), 팬텀 오버부킹 방어 | 트랜잭션 걸고 count 확인 후 INSERT 쳤는데 스냅샷 뒤에 숨은 유령 데이터로 105장 초과 발급된 참사 |
| **#048** | [새로 배포했더니 502 Bad Gateway가 10초 동안 떠요?!: 쿠버네티스 무중단 배포와 그레이스풀 셧다운(Graceful Shutdown & PreStop Hook)](problems/048-zero-downtime-graceful-shutdown/problem.md) | **클라우드 네이티브/배포 아키텍처**, 인플라이트 요청 보존, Kube-Proxy 엔드포인트 전파 딜레이 완충, PreStop sleep 훅, Zero-Downtime 롤링 업데이트 | 롤링 배포 믿고 preStop 없이 배포했다가 엔드포인트 전파 지연으로 502 에러 뿜어 결제 터진 참사 |
| **#049** | [100만 건 INSERT 쳤더니 새벽 내내 안 끝나요?!: 단건 쿼리 RTT 지옥 vs JDBC 배치 인서트(Batch Insert & rewriteBatchedStatements)](problems/049-batch-insert-rewrite-statements/problem.md) | **DB 아키텍처/네트워크 I/O**, 네트워크 RTT(Round-Trip Time) 병목, JPA IDENTITY 배치 무력화 저주, rewriteBatchedStatements=true 다중 행 재작성 | saveAll 불렀는데 IDENTITY 때문에 단건 10만 번 호출로 야간 배치 5시간 지연된 참사 |
| **#050** | [서버가 죽었는데 왜 트래픽이 죽은 서버로 계속 가요?!: DNS 캐싱(TTL)의 덫 vs BGP Anycast / Floating VIP 페일오버](problems/050-dns-ttl-vs-anycast-vip/problem.md) | **네트워크 인프라/고가용성(HA)**, DNS 계층 캐싱, Java JVM 영구 캐시(-1) 좀비 트래픽, BGP Anycast, Keepalived VRRP Floating VIP | DNS 레코드 바꿨는데 클라이언트/JVM 캐시 때문에 30분 넘게 불탄 서버로 트래픽 쏟아져 결제 폭망한 참사 |
| **#051** | [캐시가 만료되는 순간 DB가 폭발했어요?!: 캐시 스탬피드(Cache Stampede)와 분산 락 vs stale-while-revalidate](problems/051-cache-stampede-xfetch/problem.md) | **분산 캐시/동시성**, 캐시 스탬피드(Thundering Herd), Single-Flight 분산 락(Mutex), RFC 5861 stale-while-revalidate, XFetch 확률적 조기 만료 | 캐시 만료 순간 동시 5,000건 요청이 DB로 직행해 커넥션 풀 고갈 및 CPU 100%로 DB 폭사한 참사 |
| **#052** | [서버가 잠깐 멈췄는데 재시도가 폭풍처럼 몰아쳐요?!: 재시도 폭풍(Retry Storm)과 지수 백오프 + 지터(Exponential Backoff with Jitter)](problems/052-retry-storm-exponential-backoff-jitter/problem.md) | **분산 시스템/네트워크 회복 탄력성**, 재시도 폭풍(Retry Storm), 고정 백오프의 동기화 파동(Synchronization Waves), AWS Full Jitter 지수 백오프, 재시도 예산(Retry Budget) | 서버가 1초 순단됐는데 수만 대 클라이언트가 동시 재시도 때려서 영구 재부팅 불가 빠진 참사 |
| **#053** | [DB에 없는 데이터만 골라서 공격당했어요?!: 캐시 관통(Cache Penetration)과 블룸 필터(Bloom Filter)](problems/053-bloom-filter-cache-penetration/problem.md) | **확률적 자료구조/보안**, 캐시 관통(Cache Penetration), Null 객체 캐싱 한계, 블룸 필터(Bloom Filter), 위음성 0% 원칙, Kirsch-Mitzenmacher 이중 해싱 | 해커가 존재하지 않는 음수/난수 ID만 초당 수만 건 요청해 캐시 관통하고 DB 풀스캔으로 마비시킨 참사 |
| **#054** | [배포했더니 구버전 서버와 신버전 서버가 서로 데이터를 깨먹어요?!: 하위 호환성 없는 DB 마이그레이션과 Expand-and-Contract 패턴](problems/054-zero-downtime-schema-migration/problem.md) | **데이터베이스 엔지니어링/무중단 배포**, DDL 스키마 변경, Expand-and-Contract 패턴, Dual Write(동시 쓰기), Fallback Read, Online DDL 락 | 롤링 배포 중에 컬럼 삭제/이름 변경했다가 구버전 팟과 신버전 팟이 500 SQL 에러 폭탄 터진 참사 |
| **#055** | [CDN 캐시를 날렸는데 왜 유저 화면에 옛날 CSS/JS가 나와요?!: 정적 자산 캐싱과 Content Hashing (Cache Busting)](problems/055-cache-busting-content-hash/problem.md) | **웹 인프라/브라우저 캐싱**, HTTP Cache-Control(max-age vs no-cache vs no-store), immutable 디렉티브, Content-Based Hashing, Cache Busting | 프론트 배포 후 CDN 무효화 돌렸는데 브라우저 로컬 디스크 캐시 때문에 옛날 JS 실행돼 500 에러 폭발한 참사 |
| **#056** | [동시 접속자 1만 명이 들어왔더니 서버가 숨도 못 쉬어요?!: C10K 문제와 Thread-per-Client vs I/O Multiplexing (Epoll / Reactor)](problems/056-c10k-thread-vs-io-multiplexing/problem.md) | **시스템 아키텍처/네트워크 I/O**, C10K 문제, 블로킹 스레드 스택(1MB) OOM, 리눅스 epoll I/O 다중화, Reactor 패턴, Nginx/Netty/Node.js | 동시 접속자 수천 명 들어왔을 뿐인데 스레드 1만 개 폭증해 10GB 메모리 고갈 및 컨텍스트 스위칭으로 서버 다운된 참사 |
| **#057** | [한 번만 결제했는데 왜 통장에서 돈이 두 번 빠져나가요?!: 네트워크 타임아웃과 API 멱등성 (Idempotency Key & Deduplication)](problems/057-idempotency-key-deduplication/problem.md) | **분산 시스템/결제 아키텍처**, Fallacies of Distributed Computing, 네트워크 타임아웃 vs Lost ACK, Idempotency-Key, 분산 락(IN_FLIGHT), 결과 캐싱, 페이로드 변조 방어 | 결제 완료 후 통신 순단으로 응답만 유실됐는데 재시도 버튼 눌렀다가 2번 연속 결제돼 통장 잔고 털린 참사 |
| **#058** | [배송 완료된 상품이 왜 '결제 대기'로 되돌아가요?!: 네트워크 패킷 지연과 시퀀스 번호 재정렬 버퍼 (Out-of-Order Delivery & Reordering Buffer)](problems/058-out-of-order-reordering-buffer/problem.md) | **분산 이벤트 스트리밍/네트워크**, Out-of-Order 패킷 지연, 상태 역전(State Regression) 참사, 시퀀스 번호 단조 증가, 재정렬 버퍼(Reordering Buffer), 연쇄 드레인(Drain), HOL 블로킹 타임아웃 | 분산 네트워크 지연으로 이벤트가 뒤죽박죽 도착해 이미 배송 완료된 상품이 '결제 대기'로 되돌아가 중복 배송된 참사 |
| **#059** | [이메일 발송 API가 느려졌는데 왜 쇼핑몰 전체가 마비돼요?!: 롱 러닝 트랜잭션과 커넥션 풀 고갈 (Long-Running Transaction & HikariCP Pool Starvation)](problems/059-long-running-transaction-connection-starvation/problem.md) | **데이터베이스 엔지니어링/동시성**, 습관성 `@Transactional` 안티패턴, HikariCP 커넥션 풀 라이프사이클, 외부 I/O 블로킹 고갈, 트랜잭션 범위 최소화, 아웃박스 패턴 | 외부 이메일/결제 API 지연 발생 시 10개 커넥션이 영구 묶여 로그인/메인페이지 등 전사 500 타임아웃 폭사한 참사 |
| **#060** | [질문보다 답변이 먼저 뜨는 타임머신 버그?!: 분산 시계 드리프트와 램포트 논리적 시계 (Physical Clock Drift vs Lamport Logical Clock)](problems/060-lamport-logical-clock/problem.md) | **분산 시스템/시간과 인과율**, 레슬리 램포트 튜링상 논문, NTP 시계 드리프트/스큐, 일어남-선행($\to$) 인과 관계, 램포트 논리 시계 알고리즘, 전체 순서화(Total Ordering) | 노드 간 시계 오차로 질문보다 답변이 먼저 도착해 메신저 대화 타임라인이 거꾸로 뒤집힌 참사 |
| **#061** | [분산 락을 걸었는데 왜 두 명이 동시에 결제돼요?!: 분산 락의 덫과 펜싱 토큰 (Distributed Lock STW Pause & Martin Kleppmann's Fencing Token)](problems/061-distributed-lock-fencing-token/problem.md) | **분산 시스템/동시성 격리**, 마틴 클레프만 vs 안티레즈 논쟁, Stop-The-World GC 락 만료, 펜싱 토큰(Fencing Token), 스토리지 기반 울타리 검증, 락 하이재킹 방어 | GC 일시정지로 락이 만료된 사이 다른 노드가 락을 얻었는데, 깨어난 유령 노드가 데이터를 덮어써 결제 데이터가 파괴된 참사 |
| **#062** | [결제 서버 하나 뻗었다고 쇼핑몰 전체 DB가 잠겼어요?!: 분산 트랜잭션의 2PC 블로킹 지옥과 Saga 보상 트랜잭션 (Two-Phase Commit vs Saga Pattern)](problems/062-two-phase-commit-vs-saga/problem.md) | **분산 트랜잭션/MSA 아키텍처**, 2PC(Two-Phase Commit) XA 표준, 코디네이터 크래시와 Indoubt 영구 블로킹, Saga 패턴, 역순 보상 트랜잭션(Compensating Tx), 최종 일관성(Eventual Consistency) | 2PC 코디네이터 노드 장애로 참여 노드들이 Row Lock을 풀지 못해 수천 개 정상 주문이 Lock Wait Timeout으로 폭사한 참사 |
| **#063** | [카프카 컨슈머 한 대 재배포했더니 3분 동안 전사 메시지가 멈췄어요?!: 리밸런싱 폭풍과 협력적 스티키 할당자 (Kafka Rebalance Storm & Cooperative Sticky Assignor)](problems/063-kafka-consumer-rebalance-storm/problem.md) | **이벤트 스트리밍/분산 큐**, Eager Rebalance 전면 반환 프로토콜의 STW 참사, KIP-429 Cooperative Sticky Assignor, 선별적 점진 반환, 파티션 마이그레이션 최소화 | 팟 롤링 배포 시 살아있는 컨슈머의 파티션까지 뺏는 Eager 할당자 때문에 5분간 Lag 폭증 및 전사 알림 지연된 참사 |
| **#064** | [DB에서 한 번 삭제했을 뿐인데 데이터 1000만 건이 복구 불가능하게 사라졌어요?!: 물리 삭제의 위험과 소프트 딜리트 & CDC 툼스톤 (Hard Delete vs Soft Delete & CDC Tombstone)](problems/064-soft-delete-and-cdc-tombstone/problem.md) | **데이터베이스 엔지니어링/분산 캐시**, 물리 삭제(Hard Delete)와 FK CASCADE 연쇄 소각 참사, 소프트 딜리트(Soft Delete), CDC(Change Data Capture) 툼스톤(Tombstone), 유령 캐시(Ghost Cache) 제거 | 유저 1명 탈퇴시켰다가 CASCADE로 과거 5년치 100만 건 결제 영수증이 영구 증발하고 검색창에 유령 프로필이 잔류한 참사 |










---

## 🖥️ 채점 환경 및 ZeliDesk 연동

`ZeliJudge`는 특정 회사의 독점 서버나 유료 채점 인프라에 의존하지 않습니다.

1. **ZeliDesk 데스크톱 연동**:
   * ZeliDesk 앱 내부의 로컬 샌드박스 엔진을 통해 **내 컴퓨터에서 0초 만에 무료로 즉시 채점**할 수 있습니다.
2. **LLM 동적 변형 출제**:
   * 교사나 스터디 리더는 `problem.md`의 이론 뼈대를 기반으로, ZeliDesk에 탑재된 sLM/LLM을 통해 스토리와 입출력 변수를 동적으로 변형하여 **부정행위 없는 맞춤형 과제**를 생성할 수 있습니다.
3. **서버비 0원**:
   * 중앙 집중식 채점 서버가 필요 없으므로 인프라 적자 없이 영구히 공공재로 유지됩니다.

### 🛠️ 로컬 CLI 채점기 실행 방법
저장소를 클론한 후, 터미널에서 바로 문제를 채점할 수 있습니다:

```bash
# 전체 문제 채점
python tools/test_runner.py

# 특정 문제만 채점 (예: #001, #002, #003)
python tools/test_runner.py 001
```

---

## 🤝 기여 방법 (Contribution)

전국의 초·중·고 정보 교사, 컴퓨터공학과 교수 및 학생, 현업 개발자 누구나 새로운 문제를 기여할 수 있습니다!

1. 저장소를 Fork 합니다.
2. `problems/` 디렉토리 아래에 다음 번호(예: `004-...`)로 폴더를 생성합니다.
3. `problem.md`, `theory.md`, `testcases.json`, `solution.py`를 작성합니다.
4. Pull Request(PR)를 제출하면 커뮤니티 검수를 거쳐 정식 문제 세트로 등록됩니다.

---

## 📄 라이선스 (License)
본 프로젝트의 문제 지문 및 이론 자료는 **CC-BY-SA 4.0**, 정답 코드는 **MIT License**를 따릅니다. 누구나 교육 및 비상업적 목적으로 자유롭게 활용할 수 있습니다.
