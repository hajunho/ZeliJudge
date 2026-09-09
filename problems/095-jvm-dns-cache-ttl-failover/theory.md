# CS 이론 백서: JVM DNS 캐싱(networkaddress.cache.ttl)과 클라우드 페일오버의 배신

> **"AWS RDS 장애 복구해서 새 인스턴스로 넘겼는데, 왜 우리 자바 백엔드는 1시간이 지나도 계속 죽은 구버전 DB IP로 쿼리를 날리나요?!"**  
> 이 문제는 AWS나 네트워크의 버그가 아니라, **1990년대에 설계된 Java 가상 머신(JVM)의 'DNS 영구 캐싱(DNS Pinning)' 기본 설정과 현대 클라우드 인프라의 동적 IP 철학이 정면 충돌**해서 발생합니다.

---

## 1. 현실 비유: 이삿집 명함과 영구 기억상실증 우체부의 비극

마을에 유명한 '서울 빵집'이 있습니다. 빵집이 번창해서 1번가(구 주소, `10.0.1.50`)에서 건너편 5번가(신 주소, `10.0.1.60`)로 이사를 갔습니다.

```
[구 주소: 1번가 (폐점/단전)]                 [신 주소: 5번가 (영업 중)]
          ^                                           ^
          | (문 두드림: 쾅쾅!)                          |
   [자바 우체부 (JVM)]                         [파이썬/노드 우체부]
```

1. **빵집 사장님의 이사 공지 (DNS Update)**:  
   사장님은 마을 우체국 게시판(DNS 서버)에 **"저희 5번가로 이사했습니다! 5초 뒤(TTL=5초)부터는 5번가로 배달해 주세요!"**라고 대문짝만하게 써 붙였습니다.
2. **동네 배달원들의 정상 적응 (Python, Node.js, Go)**:  
   다른 배달원들은 5초 뒤 우체국 게시판을 다시 확인하고, 5번가 새 빵집으로 빵과 편지를 잘 배달했습니다.
3. **자바(Java) 우체부의 독특한 고집 (networkaddress.cache.ttl = Forever)**:  
   자바 우체부는 3년 전 수첩에 "서울 빵집 = 1번가"라고 적어둔 뒤, **"나는 은퇴(프로세스 재시작)할 때까지 죽어도 수첩 주소를 다시 고쳐보지 않는다!"**라며 게시판을 영원히 쳐다보지 않습니다.
4. **대참사**:  
   불 꺼지고 전기가 끊긴 1번가 빈 건물 문을 하루 종일 쿵쿵 두드리며 **"왜 빵을 안 파냐! 문 열어라!"(`Connection refused`)**며 배달을 전면 중단해 버렸습니다!

---

## 2. 클라우드 인프라의 핵심: DNS 기반 자동 페일오버 (Multi-AZ Failover)

AWS RDS, Aurora DB, ElastiCache, ALB(Application Load Balancer) 등 현대 클라우드 서비스는 고가용성(HA)을 위해 **DNS 기반 라우팅**을 기본으로 사용합니다:

```
[클라이언트 앱] ---> (mydb.cluster-xyz.rds.amazonaws.com) ---> Route 53 (DNS)
                                                                 |
                                       [구 마스터: 10.0.1.50] <----+ (페일오버 전)
                                       [신 마스터: 10.0.1.60] <----+ (페일오버 후! TTL=5s)
```

1. **장애 발생**: 기본(Primary) DB 인스턴스에 정전이나 하드웨어 결함이 발생합니다.
2. **복제본 승격**: AWS는 수십 초 만에 대기 중이던 Replica 인스턴스를 새로운 Master로 승격시킵니다.
3. **DNS CNAME 업데이트**: 도메인이 가리키는 IP를 `10.0.1.50`에서 `10.0.1.60`으로 바꿉니다.
4. **DNS TTL**: 전파 지연을 최소화하기 위해 AWS는 RDS 도메인의 TTL(Time-To-Live)을 **5초**로 극도로 짧게 설정합니다.

---

## 3. JVM의 역사적 유물: 왜 기본값이 영구 캐시(Forever, -1)인가?

그런데 왜 Java/Spring Boot 애플리케이션만 유독 새 IP를 찾아가지 못할까요?

오라클 JDK의 `java.security` 파일을 열어보면 다음과 같은 경악스러운 설정이 적혀 있습니다:
```properties
# The Java-level namelookup cache policy for successful lookups:
# any negative value: cache forever
networkaddress.cache.ttl=-1
```

### 왜 영구 캐시(-1)로 만들었을까?
1. **1990년대 초창기 인터넷 보안 (DNS Spoofing 방어)**:  
   과거에는 로컬 DNS 서버가 해킹당해 도메인 IP가 악의적으로 변조되는 공격(DNS 캐시 포이즈닝)이 흔했습니다. 자바 설계자들은 "신뢰할 수 있는 IP를 한 번 받아왔다면, JVM이 살아있는 동안 영원히 그 IP만 쓰는 것이 안전하다!"고 판단했습니다.
2. **성능 최적화**:  
   매 네트워크 통신마다 DNS 네임서버에 UDP 질의를 날리는 오버헤드를 없애기 위해 무제한 메모리 캐싱을 기본값으로 삼았습니다.

### 클라우드 시대에서의 비극 (DNS Pinning)
클라우드에서는 서버가 수시로 죽고 다시 뜨며 IP가 동적으로 바뀝니다.  
하지만 JVM은 한번 IP를 캐싱하면 프로세스가 강제 종료(`kill`)될 때까지 **DNS를 다시는 질의하지 않는 'DNS 피닝(DNS Pinning)'** 상태에 갇혀버립니다.

---

## 4. 커넥션 풀(HikariCP)과의 복합적 저주

DNS TTL만 고친다고 문제가 완전히 해결되지 않는 경우가 있습니다. 바로 **DB 커넥션 풀(HikariCP, DBCP)** 때문입니다:

1. 애플리케이션 시작 시 커넥션 풀이 구 IP(`10.0.1.50`)로 10개의 TCP 소켓을 미리 맺어둡니다.
2. 페일오버가 일어나고 DNS TTL이 만료되어도, **커넥션 풀이 이미 살아있는 소켓을 계속 잡고 있다면 DNS 조회를 시도조차 하지 않습니다**.
3. 결국 구 IP가 완전히 패킷을 거부(`RST`)할 때까지 기다려야 하며, 잘못된 풀 설정 시 죽은 소켓을 재사용하려다 커넥션 타임아웃 폭풍이 발생합니다.
4. 따라서 **HikariCP의 `maxLifetime` (예: 10~30분, 트래픽에 따라 수 분)**을 적절히 설정하여 연결을 주기적으로 신선하게 재생성해야 합니다.

---

## 5. 실무 아키텍트의 해결책 (체크리스트)

### 1) JVM 옵션 추가 (가장 확실하고 추천되는 방법)
애플리케이션 실행 시 JVM 옵션으로 DNS 캐시 TTL을 5초~30초로 지정합니다:
```bash
java -Dsun.net.inetaddr.ttl=5 -Dnetworkaddress.cache.ttl=5 -jar my-app.jar
```

### 2) `java.security` 파일 전역 수정 (도커 컨테이너 이미지 빌드 시)
`Dockerfile`에 한 줄을 추가하여 컨테이너 기본값을 수정합니다:
```dockerfile
RUN echo "networkaddress.cache.ttl=5" >> $JAVA_HOME/conf/security/java.security
```

### 3) 부정적 캐시(Negative Cache)도 함께 제한
도메인 조회가 일시적으로 실패했을 때 실패 결과를 캐싱하는 `networkaddress.cache.negative.ttl` (기본 10초)도 너무 길면 복구가 지연되므로 1~5초로 짧게 유지합니다:
```properties
networkaddress.cache.negative.ttl=2
```

### 4) AWS 공식 권고 준수
AWS 공식 RDS 설명서:
> *"Because Amazon RDS DNS endpoints can change, you should configure the JVM's DNS caching TTL to a low value, such as 5 seconds. By default, the JVM caches DNS name lookups forever."*
