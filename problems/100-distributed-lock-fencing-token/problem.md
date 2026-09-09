# 100. 분산 락을 잡았는데 왜 두 명이 동시에 결제돼요?!: 분산 시스템의 성배, Redis Redlock의 GC STW 시계 왜곡과 펜싱 토큰(Fencing Token)의 구원

---

## 1. 비극의 시작 (Real-World Disaster)

2016년, 캠브리지 대학의 분산 시스템 학자 **마틴 클레프만(Martin Kleppmann)** 교수는 전 세계 분산 엔지니어들을 충격에 빠뜨린 글을 기고했습니다:  
> **"Redis의 Redlock 알고리즘은 분산 락의 기본 조건인 상호 배제(Mutual Exclusion)를 보장하지 못하며, 결제나 재고처럼 데이터 무결성이 생명인 시스템에서 사용해선 안 된다."**

Redis의 창시자 **살바토레 산필리포(antirez)**가 즉각 반박하며 컴퓨터 과학 역사상 가장 뜨거운 논쟁이 불붙었습니다.  
실무에서 수많은 백엔드 개발자들이 선착순 한정 수량 티켓팅이나 특가 상품 결제 시스템에 Redis 분산 락을 도입했다가 다음과 같은 **기괴한 동시성 버그**를 목격합니다:

```text
[Client 1] Redis 분산 락 획득 성공 (key="ticket:101", TTL=5000ms)
... (5초 동안 아무런 응답 없음: JVM Full GC STW 발생!) ...
[Redis] 5000ms 경과 -> ticket:101 락 자동 만료(Expire)
[Client 2] Redis 분산 락 획득 성공 (key="ticket:101", TTL=5000ms)
[Client 2] DB 재고 차감: 1개 -> 0개 (Commit 성공)
[Client 1] 6초 만에 GC에서 깨어남! 자신이 여전히 락 소유자라고 착각하고 DB에 쓰기 시도!
[Client 1] DB 재고 차감: 0개 -> -1개 (Commit 성공?!)
```

**"분명히 두 클라이언트 모두 분산 락을 통과한 뒤에만 결제 로직을 실행했는데, 어떻게 동시에 두 명이 같은 티켓을 결제해서 재고가 -1개가 된 거지?!"**

---

## 2. 호텔 401호 도어락과 복도 얼음땡 마법 비유

이 미스터리를 호텔 객실에 비유해 봅시다:
1. **카드키 발급 (분산 락 획득)**:  
   프런트 데스크(Redis 락 서버)에서 손님 A(Client 1)에게 카드키를 주며 말합니다:  
   *"손님, 401호 카드키는 배터리 절약을 위해 **5분(TTL=5초)** 뒤에 도어락이 자동 초기화됩니다!"*
2. **복도 얼음땡 마법 (JVM Stop-The-World GC)**:  
   손님 A가 401호로 걸어가던 도중, 갑자기 **얼음땡 마법(Full GC STW / 6초 멈춤)**에 걸려 돌처럼 굳어버렸습니다!
3. **도어락 자동 만료 & 손님 B 입실**:  
   - 5분이 지나자 401호 도어락은 자동으로 초기화되었습니다.
   - 프런트 데스크는 "A가 방을 다 썼나 보네!" 하고 손님 B(Client 2)에게 새 카드키를 줬습니다.
   - 손님 B는 401호에 들어가서 침대에 짐을 풀었습니다.
4. **마법 해제와 유령의 습격**:  
   - 6분 뒤, 얼음땡에서 풀려난 손님 A는 자신이 굳어있었다는 사실조차 모른 채 **"난 아까 정상적으로 카드키를 받았으니 들어가야지!"** 하고 401호 문을 벌컥 열고 들어왔습니다.
   - 방 안에서 손님 A와 손님 B가 "내가 진짜 주인이야!"라며 몸싸움을 벌이는 **동시성 붕괴, 데이터 오염 참사**가 터진 것입니다!

---

## 3. 핵심 아키텍처 및 요구사항

당신은 분산 락 서비스(Redlock), TTL 기반 자동 만료, 비결정적 시간 지연(TICK / GC Pause), 취약한 쓰기(UNSAFE_WRITE), 그리고 마틴 클레프만이 제시한 **단조 증가 펜싱 토큰(Fencing Token) 기반의 안전한 스토리지 보호 엔진(SAFE_WRITE)**을 시뮬레이션해야 합니다.

### 1) 저장소 자원 초기화 (`INIT_RESOURCE`)
- `INIT_RESOURCE <resource_id> <initial_value>`
  - 저장소에 관리 대상 자원을 등록합니다.
  - 저장소의 초기 최대 승인 펜싱 토큰(`max_fencing_token`)은 0입니다.
  - 출력: `INIT_RESOURCE_OK resource=<resource_id> value=<initial_value> initial_token=0`

### 2) 락 서버 기본 설정 (`CONFIG_LOCK_SERVER`)
- `CONFIG_LOCK_SERVER <default_ttl_ms>`
  - 락 서버의 기본 TTL(ms)을 설정합니다.
  - 전역 펜싱 토큰 카운터는 0부터 시작합니다.
  - 출력: `CONFIG_LOCK_SERVER_OK default_ttl=<default_ttl_ms>ms`

### 3) 가상 시간 전진 (`TICK`)
- `TICK <ms>`
  - 가상 시간을 `<ms>`만큼 흐르게 합니다 (GC Pause, 네트워크 지연 시뮬레이션).
  - 현재 시각(`current_time`)이 락의 만료 시각(`expire_at`) 이상이 되면 락은 자동으로 해제(`EXPIRED`)됩니다.
  - 출력: `TICK_OK elapsed=<ms>ms current_time=<now>ms`

### 4) 분산 락 획득 (`ACQUIRE_LOCK`)
- `ACQUIRE_LOCK <client_id> <resource_id> [ttl_ms]`
  - 현재 유효한 락이 이미 존재하면 획득 거부:  
    `LOCK_ACQUIRE_DENIED client=<client_id> resource=<resource_id> holder=<holder> remaining_ttl=<rem>ms`
  - 락이 비어있거나 만료되었다면 획득 성공:
    - **단조 증가 펜싱 토큰 발급**: 락 서버의 전역 토큰 카운터가 1 증가하며, 이 값이 락의 펜싱 토큰이 됩니다 (`token = ++global_token_counter`).
    - 출력: `LOCK_ACQUIRED client=<client_id> resource=<resource_id> token=<token> expire_at=<expire_at>ms`

### 5) 분산 락 수동 해제 (`RELEASE_LOCK`)
- `RELEASE_LOCK <client_id> <resource_id>`
  - 해당 클라이언트가 유효한 락의 소유자일 때만 락을 해제합니다.
  - 락이 없거나 만료된 경우: `ERROR:LOCK_NOT_HELD client=<client_id> resource=<resource_id>`
  - 타인의 락인 경우: `ERROR:NOT_LOCK_HOLDER client=<client_id> holder=<holder>`
  - 정상 해제 시: `LOCK_RELEASED client=<client_id> resource=<resource_id>`

### 6) 취약한 쓰기 (`UNSAFE_WRITE`)
- `UNSAFE_WRITE <client_id> <resource_id> <new_value>`
  - 펜싱 토큰을 검사하지 않고 무조건 저장소의 값을 덮어씁니다 (전통적인 분산 락의 치명적 취약점 재현).
  - 출력: `UNSAFE_WRITE_OK client=<client_id> resource=<resource_id> value=<new_value>`

### 7) 안전한 펜싱 토큰 쓰기 (`SAFE_WRITE`)
- `SAFE_WRITE <client_id> <resource_id> <token> <new_value>`
  - 저장소는 클라이언트가 제시한 `<token>`과 자신이 기억하는 `max_fencing_token`을 비교합니다:
    - **펜싱 차단 (`token <= max_fencing_token`)**:  
      과거 세대의 좀비 클라이언트의 요청으로 판명되어 즉시 거부됩니다!  
      출력: `ERROR:FENCED_OUT client=<client_id> token=<token> storage_token=<storage_token> reason=TOKEN_STALE`
    - **정상 승인 (`token > max_fencing_token`)**:  
      저장소의 값을 `<new_value>`로 갱신하고 `max_fencing_token = token`으로 갱신합니다.  
      출력: `SAFE_WRITE_OK client=<client_id> resource=<resource_id> value=<new_value> token=<token>`

### 8) 상태 요약 (`STATS`)
- `STATS <resource_id>`
  - 현재 자원 값, 저장소의 최신 승인 펜싱 토큰, 락 소유자, 잔여 TTL, 전역 토큰 카운터를 출력합니다.
  - 출력: `STATS resource=<resource_id> value=<value> storage_max_token=<token> lock_holder=<holder|NONE> remaining_ttl=<rem>ms global_token_counter=<cnt>`

---

## 4. 실무 아키텍처 및 100문제 피날레 교훈

1. **완벽한 분산 락은 존재하지 않는다**:
   - 네트워크 지연, 프로세스 일시 정지(GC STW), 시계 드리프트가 존재하는 비동기 네트워크 환경에서 순수한 락 서비스만으로 동시성을 완벽히 보장하는 것은 수학적으로 불가능합니다.
2. **저장소 계층(Storage)의 자체 방어가 최후의 보루다**:
   - 애플리케이션 계층의 분산 락이 GC STW로 풀리더라도, 데이터베이스나 스토리지 레벨에서 **단조 증가 펜싱 토큰(Fencing Token)** 또는 **낙관적 락(@Version / CAS)**을 검증하여 과거 좀비 요청을 원천 차단해야 합니다.
3. **ZeliJudge 100문제 대단원의 마침표**:
   - 하드웨어 트랜잭션 메모리, CPU 캐시 라인, 운영체제 가상 메모리, 커널 네트워크 소켓, 데이터베이스 스토리지 엔진, 그리고 분산 합의에 이르기까지, 모든 시스템 소프트웨어의 핵심은 **"모든 계층은 거짓말을 할 수 있으며, 완벽한 추상화는 없다"**는 것을 이해하고 방어적으로 설계하는 것입니다.
