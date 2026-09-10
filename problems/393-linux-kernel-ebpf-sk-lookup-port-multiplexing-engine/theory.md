# Theory: Linux Kernel eBPF sk_lookup & Programmable Socket Routing (`net/core/filter.c`)

## 1. BSD 소켓 API의 태생적 한계와 대규모 엣지 프록시의 고충

BSD 소켓 모델은 1980년대 초 단일 IP와 소수의 정적 포트 환경을 전제로 설계되었습니다:
- 애플리케이션은 `socket()` -> `bind(ip, port)` -> `listen()` 순서로 특정 로컬 엔드포인트를 선점합니다.
- 패킷이 수신되면 커널 네트워킹 스택(`net/ipv4/inet_hashtables.c`)은 `inet_lookup_listener()` 함수를 호출하여 4-튜플 해시 테이블에서 일치하는 리스닝 소켓(`struct sock`)을 조회합니다.

### 1.1 Anycast 및 수백만 가상 IP 환경의 병목
현대 글로벌 CDN/DDoS 완화 인프라(Cloudflare Magic Transit, Envoy, Cilium Ingress)에서는:
- 수만~수십만 개의 Anycast IP 대역과 임의의 포트 범위(예: 1~65535)를 수용해야 합니다.
- 수만 개의 IP에 대해 각각 소켓을 바인드하면 커널 소켓 해시 테이블이 거대해져 캐시 미스가 폭증하고, 와일드카드 `0.0.0.0` 바인드와 특정 IP 바인드가 공존할 때 라우팅 충돌이 발생합니다.

---

## 2. eBPF `sk_lookup`의 동작 원리 (`BPF_PROG_TYPE_SK_LOOKUP`)

Linux 5.9에서 메인라인에 병합된 `sk_lookup`은 인그레스 패킷 처리 경로에서 커널 해시 테이블 조회를 가로채는 혁신적 후크입니다:

```c
struct bpf_sk_lookup {
    union {
        __be32 ipv4_src;
        __u32  ipv6_src[4];
    };
    union {
        __be32 ipv4_dst;
        __u32  ipv6_dst[4];
    };
    __u16 sport;
    __u16 dport;
    __u32 protocol;
    __u32 ingress_ifindex;
};
```

### 2.1 주요 헬퍼 함수 및 반환 코드
1. **`bpf_sk_assign(ctx, sk, flags)`**:
   - eBPF 프로그램이 BPF Map(예: LPM Trie, Hash Map)을 조회하여 선택한 `struct bpf_sock *`을 패킷에 직접 바인딩합니다.
   - 커널은 기존 `inet_lookup_listener()` 검색을 즉각 건너뛰고 해당 소켓의 수신 큐로 직행합니다 (**Zero Hashtable Lookup Overhead**).
2. **`BPF_DROP`**:
   - 포트 스캔이나 DoS 공격 트래픽을 감지한 경우 즉시 패킷을 폐기합니다.
   - 커널이 TCP RST 패킷을 송신하지 않으므로 공격자에게 호스트 존재 여부를 노출하지 않고 네트워크 자원을 방어합니다.
3. **`BPF_OK` (Without Assign)**:
   - eBPF 프로그램이 소켓을 할당하지 않고 종료되면 커널은 기존 레거시 해시 테이블 검색으로 안전하게 폴백합니다.
