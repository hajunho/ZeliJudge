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
