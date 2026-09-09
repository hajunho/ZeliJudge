# 095. AWS RDS 장애 복구해서 새 서버 띄웠는데 왜 우리 자바 백엔드는 계속 죽은 DB로 쿼리를 날려요?!: JVM DNS 캐싱(networkaddress.cache.ttl=Forever)과 DNS 피닝(DNS Pinning)의 배신

---

## 1. 비극의 시작 (Real-World Disaster)

새벽 3시, 대규모 트래픽을 처리하던 이커머스 서비스의 AWS RDS Primary 데이터베이스 인스턴스에 갑작스러운 하드웨어 장애가 발생했습니다.

AWS RDS의 Multi-AZ 자동 페일오버(Automated Failover) 엔진이 즉시 가동되었습니다:
1. 대기 중이던 읽기 전용 복제본(Read Replica)을 새로운 마스터(Master)로 승격시켰습니다 (`10.0.1.60`).
2. Route 53 DNS 네임서버가 CNAME 도메인(`mydb.cluster-xxx.rds.amazonaws.com`)이 가리키는 IP를 구 서버(`10.0.1.50`)에서 신규 서버(`10.0.1.60`)로 변경했습니다.
3. 이 모든 과정은 단 30초 만에 완벽하게 끝났습니다!

Node.js로 작성된 알림 서비스와 Python 데이터 파이프라인은 5초(DNS TTL) 뒤 신규 마스터 IP로 정상 접속하여 서비스를 재개했습니다.

**하지만 회사의 핵심 결제 및 주문을 담당하는 Java / Spring Boot 백엔드는 30분이 지나도, 1시간이 지나도 복구되지 않았습니다!**
```text
org.postgresql.util.PSQLException: Connection to mydb.cluster-xxx.rds.amazonaws.com:5432 refused. 
Check that the hostname and port are correct and that the postmaster is accepting TCP/IP connections. (IP: 10.0.1.50)
```

모니터링 대시보드를 본 준호는 경악했습니다.  
DNS는 분명 `10.0.1.60`으로 바뀐 지 한참인데, **자바 서버들은 죽어서 응답도 없는 구버전 IP `10.0.1.50`을 향해 수만 건의 쿼리를 끊임없이 난사**하고 있었습니다!

결국 선임 아키텍트가 뛰어와 스프링 부트 프로세스를 강제 재시작(`systemctl restart app`)하자마자 거짓말처럼 1초 만에 정상화되었습니다.  
도대체 왜 자바는 프로세스를 껐다 켜기 전까지 죽은 IP를 놓지 못했던 걸까요?

---

## 2. 우체부의 비극: 왜 JVM은 DNS를 영원히 캐싱하는가?

마을의 유명한 '서울 빵집'이 1번가(`10.0.1.50`)에서 건너편 5번가(`10.0.1.60`)로 이사를 갔습니다:

1. **우체국 게시판 공지 (DNS Update)**:  
   빵집 사장님은 마을 우체국 게시판(DNS 서버)에 **"저희 5번가로 이사했습니다! 5초 뒤(TTL=5초)부터는 5번가로 배달해 주세요!"**라고 대문짝만하게 공지했습니다.
2. **정상적인 배달원들 (Node.js, Python, Go)**:  
   동네 배달원들은 5초 뒤 게시판을 보고 5번가 새 빵집으로 잘 찾아갔습니다.
3. **자바(Java) 우체부의 고집 (networkaddress.cache.ttl = Forever)**:  
   자바 우체부는 3년 전 수첩에 "서울 빵집 = 1번가"라고 적어둔 뒤, **"나는 은퇴(프로세스 종료)할 때까지 죽어도 수첩 주소를 다시 고쳐보지 않는다!"**라며 게시판을 영원히 쳐다보지 않습니다(**DNS Pinning**).
4. **대참사**:  
   불 꺼진 1번가 빈 건물 문을 하루 종일 쿵쿵 두드리며 **"왜 빵을 안 파냐! 문 열어라!"(`Connection refused`)**며 배달을 멈춰버렸습니다!

오라클 JDK의 `java.security` 파일에는 **`networkaddress.cache.ttl=-1` (Forever / 영구 캐시)**이라는 1990년대의 고대 유물이 기본값으로 박혀 있습니다. 클라우드 환경에서는 IP가 수시로 바뀌는데, JVM은 한번 조회한 IP를 평생 잊지 않는 치명적인 모순이 발생한 것입니다.

---

## 3. 핵심 아키텍처 및 요구사항

당신은 DNS 네임서버, AWS RDS 자동 페일오버 FSM, 그리고 JVM DNS 캐시 및 DB 커넥션 풀을 시뮬레이션하는 엔진을 구현해야 합니다.

### 1) DNS 네임서버 설정 (`CONFIG_DNS`)
- `CONFIG_DNS <domain> <initial_ip> <record_ttl_ms>`
  - 도메인과 초기 IP 주소를 등록합니다. 해당 IP의 상태는 `UP` (활성)입니다.
  - 출력: `DNS_CONFIG_OK domain=<domain> ip=<ip> ttl=<record_ttl_ms>ms`

### 2) 클라이언트 런타임 설정 (`CONFIG_CLIENT`)
- `CONFIG_CLIENT <client_id> <dns_cache_ttl_ms> <conn_pool_lifetime_ms>`
  - `dns_cache_ttl_ms`:
    - `-1`: 오라클 JVM 기본값 (Forever / 영구 캐시. 프로세스 재시작 전까지 절대 만료되지 않음).
    - `> 0`: 튜닝된 DNS 캐시 만료 시간(ms) (예: `5000` = 5초).
  - `conn_pool_lifetime_ms`:
    - `> 0`: DB 커넥션 풀(HikariCP)의 소켓 최대 수명. 연결 수립 후 이 시간이 지나면 소켓을 닫고 새 연결을 맺습니다.
    - `0`: 풀 미사용 (단발성 연결. 매 쿼리마다 DNS 캐시를 확인).
  - 출력: `CLIENT_CONFIG_OK id=<id> dns_ttl=<dns_cache_ttl_ms> pool_lifetime=<conn_pool_lifetime_ms>ms`

### 3) 쿼리 실행 및 DNS 해석 (`QUERY`)
- `QUERY <client_id> <domain> <query_id>`
  - `total_queries += 1`
  - **1단계 (커넥션 풀 확인)**:
    - 풀에 활성 연결(`active_conn`)이 존재하고, `current_time - created_at < conn_pool_lifetime_ms`이면:
      - 기존 TCP 연결을 그대로 재사용 (`target_ip = active_conn.target_ip`, `dns_status = POOL_REUSED`).
  - **2단계 (새 연결 수립 및 DNS 해석)**:
    - 풀에 유효한 연결이 없다면 DNS 해석을 진행합니다:
      - 클라이언트 내부 DNS 캐시에 해당 도메인이 있고, (`dns_ttl_ms == -1` 또는 `current_time < expires_at`):
        - 캐시 적중: `target_ip = cache.ip`, `dns_cache_hits += 1`, `dns_status = DNS_HIT`
      - 캐시가 없거나 만료되었다면:
        - 네임서버 질의: `dns_resolves += 1`
        - 도메인이 네임서버에 없으면: `0.0.0.0`, `DNS_NXDOMAIN`
        - 도메인이 존재하면: 새 IP 획득, 캐시에 저장 (`expires_at = inf` if `dns_ttl == -1` else `current_time + dns_ttl_ms`), `dns_status = DNS_RESOLVED`
      - `conn_pool_lifetime_ms > 0`이면 새 연결을 생성하여 풀에 보관.
  - **3단계 (목표 서버 가용성 검증)**:
    - 대상 `target_ip`가 네임서버에서 `UP` 상태이면:
      - 성공! `success_count += 1`
      - 출력: `QUERY_OK client=<id> ip=<ip> status=SUCCESS [<dns_status>]`
    - 대상 `target_ip`가 `DOWN` (사망) 상태이면:
      - 실패! `fail_count += 1`
      - 망가진 연결이므로 풀 연결을 즉시 파기(`active_conn = None`).
      - 출력: `QUERY_FAIL client=<id> ip=<ip> status=CONNECTION_REFUSED [<dns_status>]`

### 4) AWS RDS 자동 페일오버 트리거 (`FAILOVER`)
- `FAILOVER <domain> <new_ip>`
  - 기존 마스터 IP는 즉시 `DOWN` (정전/장애).
  - 네임서버의 해당 도메인 IP가 `new_ip` (`UP`)로 업데이트됩니다.
  - 출력: `FAILOVER_TRIGGERED domain=<domain> old_ip=<old_ip> new_ip=<new_ip>`

### 5) 클라이언트 프로세스 재시작 (`RESTART_CLIENT`)
- `RESTART_CLIENT <client_id>`
  - JVM 재기동 시뮬레이션:
  - 해당 클라이언트의 DNS 캐시와 커넥션 풀을 완전히 초기화(비움)합니다.
  - 출력: `CLIENT_RESTARTED id=<client_id>`

### 6) 시간 경과 (`TICK <delta_ms>`)
- `current_time_ms += delta_ms`
- 출력: `TICK_OK time=<current_time_ms>ms`

### 7) 클라이언트 상태 및 가용성 진단 (`STATS`)
- `total`: 누적 쿼리 수
- `success`: 성공 쿼리 수
- `fail`: 실패 쿼리 수
- `dns_resolves`: DNS 네임서버 질의 횟수
- `hits`: DNS 로컬 캐시 적중 횟수
- `avail`: 가용성 ($\frac{\text{success}}{\text{total}} \times 100\%$, 소수점 1자리)
- `target_ip`: 가장 최근 DNS 캐시에 저장된 대상 IP
- `health` 판정 기준:
  - `target_ip`가 현재 네임서버에서 `DOWN` 상태인 경우:
    - `dns_ttl_ms == -1`: **`STALE_DNS_PINNED_OUTAGE`** (죽은 구 IP에 영구 고착된 재앙)
    - 그 외: **`DEGRADED`** (일시적 지연)
  - `avail < 70.0%`: **`DEGRADED`**
  - 그 외: **`HEALTHY`**
- 출력 형식:
  `STATS client=<id> total=<tot> success=<succ> fail=<fail> dns_resolves=<res> hits=<hits> avail=<avail>% target_ip=<ip> health=<health>`

---

## 4. 입출력 형식

### 입력
표준 입력(stdin)으로 여러 줄의 명령어가 주어집니다. 빈 줄이나 `#`으로 시작하는 주석은 무시합니다.

- `CONFIG_DNS <domain> <ip> <ttl_ms>`
- `CONFIG_CLIENT <client_id> <dns_ttl_ms> <conn_pool_lifetime_ms>`
- `QUERY <client_id> <domain> <query_id>`
- `FAILOVER <domain> <new_ip>`
- `RESTART_CLIENT <client_id>`
- `TICK <delta_ms>`
- `STATS <client_id>`

### 출력
각 명령어의 실행 결과를 표준 출력(stdout)으로 한 줄씩 출력합니다.

---

## 5. 입출력 예시

### 예시 1: JVM 기본 영구 캐시 vs 튜닝된 5초 TTL 캐시 비교
**입력:**
```text
CONFIG_DNS mydb.rds.internal 10.0.1.50 5000
CONFIG_CLIENT jvm_default -1 30000
CONFIG_CLIENT jvm_tuned 5000 10000
QUERY jvm_default mydb.rds.internal q1
QUERY jvm_default mydb.rds.internal q2
QUERY jvm_tuned mydb.rds.internal q3
QUERY jvm_tuned mydb.rds.internal q4
FAILOVER mydb.rds.internal 10.0.1.60
QUERY jvm_default mydb.rds.internal q5
QUERY jvm_tuned mydb.rds.internal q6
TICK 6000
QUERY jvm_default mydb.rds.internal q7
QUERY jvm_tuned mydb.rds.internal q8
STATS jvm_default
STATS jvm_tuned
RESTART_CLIENT jvm_default
QUERY jvm_default mydb.rds.internal q9
STATS jvm_default
```

**출력:**
```text
DNS_CONFIG_OK domain=mydb.rds.internal ip=10.0.1.50 ttl=5000ms
CLIENT_CONFIG_OK id=jvm_default dns_ttl=-1 pool_lifetime=30000ms
CLIENT_CONFIG_OK id=jvm_tuned dns_ttl=5000 pool_lifetime=10000ms
QUERY_OK client=jvm_default ip=10.0.1.50 status=SUCCESS [DNS_RESOLVED]
QUERY_OK client=jvm_default ip=10.0.1.50 status=SUCCESS [POOL_REUSED]
QUERY_OK client=jvm_tuned ip=10.0.1.50 status=SUCCESS [DNS_RESOLVED]
QUERY_OK client=jvm_tuned ip=10.0.1.50 status=SUCCESS [POOL_REUSED]
FAILOVER_TRIGGERED domain=mydb.rds.internal old_ip=10.0.1.50 new_ip=10.0.1.60
QUERY_FAIL client=jvm_default ip=10.0.1.50 status=CONNECTION_REFUSED [POOL_REUSED]
QUERY_FAIL client=jvm_tuned ip=10.0.1.50 status=CONNECTION_REFUSED [POOL_REUSED]
TICK_OK time=6000ms
QUERY_FAIL client=jvm_default ip=10.0.1.50 status=CONNECTION_REFUSED [DNS_HIT]
QUERY_OK client=jvm_tuned ip=10.0.1.60 status=SUCCESS [DNS_RESOLVED]
STATS client=jvm_default total=4 success=2 fail=2 dns_resolves=1 hits=1 avail=50.0% target_ip=10.0.1.50 health=STALE_DNS_PINNED_OUTAGE
STATS client=jvm_tuned total=4 success=3 fail=1 dns_resolves=2 hits=0 avail=75.0% target_ip=10.0.1.60 health=HEALTHY
CLIENT_RESTARTED id=jvm_default
QUERY_OK client=jvm_default ip=10.0.1.60 status=SUCCESS [DNS_RESOLVED]
STATS client=jvm_default total=5 success=3 fail=2 dns_resolves=2 hits=1 avail=60.0% target_ip=10.0.1.60 health=DEGRADED
```

---

## 6. 실무 아키텍트 가이드: 어떻게 해결해야 하는가?

1. **클라우드 환경에서는 JVM DNS TTL을 반드시 5초~30초로 튜닝하라**:
   - 실행 옵션: `java -Dnetworkaddress.cache.ttl=5 -jar app.jar`
   - 또는 도커 이미지의 `$JAVA_HOME/conf/security/java.security` 파일에 `networkaddress.cache.ttl=5`를 추가하세요.
2. **HikariCP 커넥션 풀의 `maxLifetime`을 적절히 설정하라**:
   - 아무리 DNS TTL을 5초로 줄였어도, DB 커넥션 풀이 이미 맺어둔 TCP 연결을 무한정 붙잡고 있으면 DNS 질의 자체가 일어나지 않습니다.
   - 기본 권장값인 30분(또는 트래픽에 따라 10분)으로 `maxLifetime`을 설정하여 주기적으로 연결을 갱신하도록 하세요.
3. **AWS 공식 문서 권고사항**:
   > *"Amazon RDS DNS 엔드포인트는 페일오버 시 변경되므로, JVM의 DNS TTL을 5초와 같은 작은 값으로 반드시 설정해야 합니다. 기본적으로 JVM은 DNS 조회를 영원히 캐싱하므로 페일오버 후 재연결을 방해합니다."*
