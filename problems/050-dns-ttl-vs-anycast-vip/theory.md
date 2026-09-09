# #050 DNS 캐싱(TTL)의 덫 vs BGP Anycast / Floating VIP 페일오버 완벽 가이드

---

## 1. 개요: "서버 주소를 바꿨는데 왜 죽은 서버로 트래픽이 가나요?"

인프라를 처음 운영해보는 주니어 엔지니어나 AI 바이브 코더들이 가장 많이 저지르는 치명적 실수 중 하나는  
**"서버에 장애가 나면 DNS 레코드를 대기 서버로 바꾸면 된다"**는 순진한 믿음입니다.

실제 프로덕션 환경에서 이런 방식으로 재해 복구(DR, Disaster Recovery)나 페일오버(Failover)를 시도하면,  
**DNS 레코드를 바꾼 지 30분이 지나도 트래픽의 80% 이상이 여전히 죽은 서버로 쏟아져 들어가는 대참사**를 목격하게 됩니다.

왜 이런 일이 발생할까요?  
DNS의 계층적 캐싱 구조와, 이를 극복하기 위한 네트워크 계층의 **BGP Anycast 및 Floating VIP** 메커니즘을 완벽하게 파헤쳐 봅니다.

---

## 2. DNS 기반 페일오버가 실무에서 실패하는 이유

```text
[클라이언트 앱/브라우저]
        │
   (1) 로컬 OS 리졸버 캐시 (Windows / macOS / Linux systemd-resolved)
        │
   (2) 사내 프록시 / Wi-Fi 공유기 DNS 캐시
        │
   (3) 통신사(ISP) Recursive DNS 캐시 (KT, SKT, LGU+, Comcast)
        │
   (4) 권한 네임서버 (Authoritative DNS: AWS Route53, Cloudflare)
```

### 1) DNS는 로드밸런서가 아닌 "분산 전화번호부"입니다
DNS는 원래 전 세계 수십억 대의 컴퓨터가 도메인 이름을 IP로 바꿀 때,  
최상위 네임서버에 부하가 집중되지 않도록 **철저히 캐싱(Caching)을 장려하도록 설계된 프로토콜**입니다.  
즉, "실시간 트래픽 스위칭" 용도로 태어난 기술이 아닙니다.

### 2) TTL(Time To Live)을 줄여도 안 통하는 이유
DNS 응답에는 `TTL`(유효 시간)이 포함되어 있어, "이 시간 동안은 나한테 다시 묻지 말고 캐시해서 써라"고 지시합니다.  
"그럼 TTL을 1초나 5초로 극단적으로 줄이면 되지 않나요?"라고 생각할 수 있습니다. 하지만 현실은 다음과 같습니다:

1. **중간 DNS 서버들의 TTL 덮어쓰기 (Minimum TTL Enforcement)**:
   - 전 세계 수많은 통신사(ISP)와 기업 사내 DNS 리졸버는 트래픽 절감을 위해 RFC 표준을 무시하고,  
     최소 캐시 시간을 강제로 **300초(5분) ~ 3600초(1시간)**로 고정해 버립니다.
2. **DNS 쿼리 폭풍(Query Storm) 및 비용 폭탄**:
   - 모든 클라이언트가 매 요청마다 DNS를 조회하면, 권한 DNS(AWS Route53 등) 비용이 천문학적으로 치솟고  
     매 요청마다 DNS 조회 왕복 시간(RTT 20~100ms)이 추가되어 서비스 레이턴시가 폭망합니다.

### 3) Java/JVM의 영구 캐싱 재앙 (`networkaddress.cache.ttl = -1`)
백엔드 마이크로서비스 간 통신에서 가장 치명적인 복병은 **Java JVM**입니다.
- Java 표준 라이브러리의 `InetAddress` 클래스는 성능 최적화를 위해 DNS 조회 결과를 프로세스 메모리에 캐싱합니다.
- `SecurityManager`가 활성화되어 있거나 구버전 환경에서는 **기본 TTL이 `-1`(Forever, 영구 캐시)**로 설정되어 있습니다!
- 즉, DNS 레코드가 바뀌어도 **해당 스프링부트 API 서버 팟(Pod)을 전부 재시작하지 않는 한, 영원히 옛날 죽은 IP로만 통신**을 시도하다가 전사 결제 시스템이 멈춥니다.

> [!IMPORTANT]
> **스프링/Java 환경의 필수 보안 설정**:
> JVM 시작 옵션에 반드시 다음 파라미터를 명시하여 DNS 캐시 시간을 5~10초로 제한해야 합니다:
> ```bash
> -Dsun.net.inetaddr.ttl=10
> # 또는 java.security 파일에 설정:
> # networkaddress.cache.ttl=10
> ```

---

## 3. 궁극의 해결책: Anycast VIP & Floating VIP (Keepalived / VRRP)

진정한 무중단 고가용성(HA) 아키텍처는 **"클라이언트가 바라보는 IP 자체를 절대로 바꾸지 않는다"**는 원칙에서 출발합니다.

```text
[고객/클라이언트] ──────> 항시 고정된 단 하나의 VIP: 10.0.0.1
                                   │
                      ┌────────────┴────────────┐
                      ▼                         ▼
             [Active L4 로드밸런서]    [Standby L4 로드밸런서]
              (192.168.1.10)            (192.168.1.20)
                      │ (헬스체크 실패 시 0.1초 전환)
                      ▼
             [정상 백엔드 서버 군집]
```

### 1) BGP Anycast (Global / CDN 레벨)
- **개념**: 전 세계 수백 개 데이터센터에 있는 라우터들이 **완전히 동일한 단일 IP(예: `1.1.1.1`, `8.8.8.8`)**를 BGP(Border Gateway Protocol)로 인터넷 백본망에 공고(Advertise)합니다.
- **동작 방식**:
  - 고객의 패킷은 인터넷 라우팅 알고리즘에 의해 물리적으로 가장 가까운 PoP(데이터센터)로 자동 전달됩니다.
  - 만약 도쿄 데이터센터가 지진으로 전원이 나가면, 도쿄 라우터가 BGP 공고를 철회(Withdraw)합니다.
  - 1~2초 만에 전 세계 인터넷 라우터들이 다음으로 가까운 오사카나 서울 PoP로 트래픽을 자동 우회시킵니다.
  - **클라이언트는 DNS를 다시 조회할 필요가 전혀 없으며, IP도 그대로 유지됩니다.**

### 2) Floating VIP with Keepalived & VRRP (데이터센터 / 온프레미스 레벨)
- **개념**: 2대의 로드밸런서(Active-Standby)가 **가상 IP(VIP, Virtual IP)** 1개를 공유합니다.
- **동작 방식**:
  - 평시에는 Active 서버가 VIP(`10.0.0.1`)를 자신의 NIC에 바인딩하고 트래픽을 처리합니다.
  - Standby 서버는 주기적으로 VRRP(Virtual Router Redundancy Protocol) 하트비트를 감시합니다.
  - Active 서버가 쓰러지면, Standby 서버가 이를 감지하고 **0.1~1초 만에 VIP를 자신의 NIC로 가져옵니다(IP Takeover)**.
  - 이때 Standby 서버는 L2 네트워크 스위치에 **GARP(Gratuitous ARP)** 패킷을 브로드캐스트하여,  
    "이제 `10.0.0.1`의 MAC 주소는 내 MAC 주소다!"라고 전파합니다.
  - 스위치의 MAC 주소 테이블이 즉시 갱신되어, 모든 패킷이 0.1초 만에 백업 서버로 포워딩됩니다.

---

## 4. DNS Failover vs Anycast/Floating VIP 기술 비교

| 비교 항목 | DNS 기반 페일오버 (NAIVE_DNS) | BGP Anycast / Floating VIP (ANYCAST_VIP) |
| :--- | :--- | :--- |
| **전환 소요 시간** | 수분 ~ 수시간 (클라이언트/ISP 캐시 만료 시까지) | **0.1초 ~ 3초 이내** (네트워크 레벨 즉각 전환) |
| **클라이언트 캐시 영향** | 치명적 (브라우저, OS, JVM 캐시로 인해 실패 지속) | **영향 없음** (고객이 접속하는 IP 자체가 불변) |
| **패킷 유실률** | 매우 높음 (캐시 만료 전까지 100% 에러 폭풍) | 극도로 낮음 (헬스체크 감지 찰나의 순간만 영향) |
| **인프라 비용/복잡도** | 단순 (DNS 레코드만 수정) | 높음 (BGP 라우팅 장비 or Keepalived/L4 구축 필요) |
| **적합한 용도** | 단순 개발 환경, SLA가 느슨한 정적 웹사이트 | **금융, 전자상거래, 실시간 결제, 글로벌 CDN** |

---

## 5. 실무 프로덕션 아키텍처 권장 패턴

실무 엔터프라이즈 환경에서는 두 기술을 대립적으로 쓰는 것이 아니라, **계층적으로 조합**하여 구축합니다:

1. **L1 (Global DNS & BGP Anycast)**:
   - AWS Route53 Geolocation / Latency 라우팅 또는 Cloudflare / AWS Global Accelerator(BGP Anycast VIP)를 통해  
     가장 가까운 리전의 VIP로 트래픽을 유입시킵니다.
2. **L2 (Regional Load Balancer)**:
   - 각 리전 내부에서는 AWS ALB/NLB 또는 온프레미스 Keepalived L4 VIP를 통해  
     수십 대의 백엔드 인스턴스로 트래픽을 무중단 분산합니다.
3. **L3 (Service-to-Service)**:
   - 쿠버네티스 내부에서는 ClusterIP(kube-proxy iptables/IPVS) 또는 Envoy Service Mesh(Istio)를 사용하여,  
     DNS를 거치지 않고 실시간 엔드포인트(xDS API) 제어로 0초 페일오버를 달성합니다.
