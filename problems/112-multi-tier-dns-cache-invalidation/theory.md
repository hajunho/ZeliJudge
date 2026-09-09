# [배경 이론] 다계층 DNS 캐싱과 네거티브 캐시의 저주 (Multi-Tier DNS Cache Hierarchy & RFC 2308)

## 1. 현실 비유: 주소 이전 신고와 동네 우체부들의 수첩

여러분이 회사를 서울 강남에서 판교로 이사했다고 상상해 보세요.

1. **법인 등기소(Authoritative DNS Server)**에 공식 이전 신고를 마쳤습니다. 등기부등본에는 이제 판교 주소가 적혀 있습니다.
2. 하지만 여러분에게 우편물을 배달하는 **총괄 우체국(ISP Recursive Resolver)**, **동네 우체부(OS Resolver)**, 그리고 회사의 **경비실 안내원(Application / JVM Cache)**은 각자 자기 수첩에 옛날 주소를 적어두고 배달하고 있습니다.
3. 등기소에 "주소 유효기간(TTL)은 1분이야"라고 적어두었음에도:
   - 총괄 우체국장이 "귀찮게 1분마다 물어보지 마! 우리 우체국은 무조건 최소 5분(ISP TTL Clamping) 동안 적어둔 주소 쓸 거야"라고 무시합니다.
   - 회사 경비실 안내원(Java JVM)은 "한 번 알게 된 주소는 평생 안 바꾼다(TTL = -1)"면서 퇴사할 때까지 옛날 강남 주소만 외치고 있습니다.
4. 심지어 아직 사업자등록이 안 끝났을 때 찾아온 손님에게 "그런 회사 없는데요?(NXDOMAIN)"라고 답한 기록까지 수첩에 30분 동안 적어두어(Negative Cache), 1초 뒤에 법인이 설립되었음에도 30분 동안 유령 회사 취급을 받습니다.

---

## 2. 다계층 DNS 해석 계층 구조 (Resolution Hierarchy)

웹 브라우저나 백엔드 서버가 `https://api.example.com`을 호출할 때, DNS 질의는 총 4단계의 캐시 계층을 통과합니다.

```
[애플리케이션 계층] (App / JVM In-Memory DNS Cache)
       │  (Miss)
       ▼
[운영체제 계층] (OS Resolver: Windows dnscache, Linux systemd-resolved, nscd)
       │  (Miss)
       ▼
[인터넷/공유기 계층] (ISP / Public Recursive Resolver: KT/SKT/LG, 8.8.8.8, 1.1.1.1)
       │  (Miss)
       ▼
[권한 네임서버] (Authoritative Name Server: AWS Route 53, Cloudflare, BIND)
```

### 계층별 캐시 동작 특성
1. **애플리케이션 계층 (App Cache)**:
   - Java Virtual Machine(JVM)의 악명 높은 기본값: 보안 매니저가 활성화된 구형 JVM이나 특정 환경에서 `networkaddress.cache.ttl = -1` (영구 캐싱)로 설정되어 있습니다.
   - 이 경우 권한 네임서버에서 IP를 바꾸고 아무리 오랜 시간이 지나도 애플리케이션 프로세스를 재시작(Restart)하기 전까지는 옛날 IP로만 패킷을 보냅니다.
   - 실무 권장값: `networkaddress.cache.ttl = 30` (30초~60초) 명시적 주입.
2. **운영체제 계층 (OS Cache)**:
   - Windows의 `dnscache` 서비스(`ipconfig /flushdns`로 초기화).
   - Linux의 `systemd-resolved` 또는 `nscd` (`resolvectl flush-caches`).
   - 상위 리졸버에서 전달받은 잔여 TTL만큼 캐시를 보관합니다.
3. **ISP / 공용 재귀 리졸버 계층 (ISP Resolver)**:
   - 통신사(SKT, KT, LGU+)나 구글(8.8.8.8), 클라우드플레어(1.1.1.1)가 운영하는 캐시 서버입니다.
   - **ISP TTL Clamping (최소 TTL 강제)**: 서비스 제공자가 빠른 무중단 배포를 위해 TTL을 5초나 10초로 짧게 설정해도, 일부 ISP 리졸버는 트래픽 절감을 위해 300초(5분) 미만의 TTL을 무시하고 300초로 강제 상향(Clamping)해 버리는 관행이 존재합니다.
4. **권한 네임서버 (Authoritative DNS)**:
   - 해당 도메인의 '절대적 진실(Ground Truth)'을 가지고 있는 최상위 서버입니다.

---

## 3. RFC 2308 네거티브 캐싱(Negative Caching)과 NXDOMAIN의 함정

신규 서비스 배포 당일 자주 일어나는 참사 중 하나가 바로 **네거티브 캐싱(Negative Caching, RFC 2308)**입니다.

### 시나리오:
1. 인프라 엔지니어가 `pay.service.com` DNS 레코드를 등록하기 직전, 성급한 QA 엔지니어나 자동화 헬스체크 스크립트가 해당 도메인을 먼저 호출합니다.
2. 권한 네임서버에는 아직 레코드가 없으므로 **"해당 도메인이 존재하지 않음(`NXDOMAIN`)"** 응답을 반환합니다.
3. 이때 권한 서버의 SOA(Start of Authority) 레코드에 적힌 `MINIMUM TTL` (예: 30초~300초) 정보가 함께 전달됩니다.
4. **결과**:
   - ISP와 OS, 애플리케이션은 "이 도메인은 없는 도메인이다"라는 **실패 결과 자체를 캐싱(Negative Caching)**합니다!
   - 3초 뒤 엔지니어가 DNS 레코드를 정상 등록하더라도, 이미 실패를 캐싱한 클라이언트는 네거티브 TTL이 만료될 때까지 계속 `NXDOMAIN` 에러를 뿜으며 서비스를 찾지 못합니다.

---

## 4. 실무 DNS 마이그레이션 황금 수칙 (Playbook)

1. **사전 TTL 단축 (Pre-Migration TTL Lowering)**:
   - 서버 IP를 바꾸기 **수일 전**에 미리 DNS 레코드의 TTL을 60초~300초로 대폭 낮춰놓아야 합니다. (기존 86,400초 캐시가 전 세계에서 모두 만료되도록 대기)
2. **JVM DNS 캐시 정책 명시**:
   - 자바 백엔드 애플리케이션 기동 시 `-Dnetworkaddress.cache.ttl=30` 옵션을 명시하여 영구 캐싱 좀비 트래픽을 원천 차단합니다.
3. **네거티브 캐시 주의**:
   - 신규 도메인을 오픈할 때는 반드시 DNS 레코드 등록 및 전파 확인이 끝난 후에 클라이언트 트래픽을 유입시켜야 합니다.
