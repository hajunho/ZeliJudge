# 리눅스 커널 TC cls_bpf Direct-Action (da) 아키텍처와 eBPF 패킷 프로세싱 이론

## 1. 서론: Linux Traffic Control (TC)과 eBPF의 결합

전통적인 리눅스 네트워크 스택에서 패킷 스케줄링, 셰이핑(Shaping), 폴리싱(Policing)은 커널의 **Traffic Control (TC)** 서브시스템이 전담해 왔습니다. TC는 패킷을 큐잉하는 큐잉 디시플린(Qdisc: Classless / Classful), 패킷을 분류하는 분류기(Classifier / Filter), 그리고 특정 처분을 내리는 동작(Action)의 3요소로 구성됩니다.

그러나 eBPF(Extended Berkeley Packet Filter) 기술이 도입되면서, 리눅스 커널은 2015년경 `net/sched/cls_bpf.c`를 통해 TC 서브시스템에 eBPF 프로그램을 부착할 수 있는 **`cls_bpf`**를 구현했습니다. 특히 **Direct-Action (`da`) 모드**의 도입은 현대 쿠버네티스 네트워킹(Cilium)의 혁명을 이끌어냈습니다.

---

## 2. XDP vs TC eBPF: 심층 비교 분석

현업 엔지니어들이 가장 자주 직면하는 기술적 선택지는 **XDP(eXpress Data Path)**와 **TC eBPF** 간의 트레이드오프입니다:

| 비교 항목 | XDP (eXpress Data Path) | TC eBPF (`cls_bpf`) |
| :--- | :--- | :--- |
| **실행 위치** | 디바이스 드라이버 수신 링 직후 (`sk_buff` 할당 전) | 리눅스 네트워크 서브시스템 (`sk_buff` 할당 후) |
| **방향성** | **오직 수신(Ingress)** 경로만 가능 | **수신(Ingress) 및 송신(Egress)** 모두 가능 |
| **컨텍스트 객체** | 경량 구조체 `struct xdp_md` | 완전한 소켓 버퍼 `struct __sk_buff` |
| **메타데이터 조작** | 불가 (원시 패킷 바이트만 조작) | `skb->mark`, `skb->priority`, `skb->vlan_tci` 완전 조작 |
| **주요 활용처** | L4 초고속 DDoS 방어, 초고속 로드 밸런서(Katran) | 서비스 프록시(Kube-Proxy 대체), 컨테이너 보안, 트래픽 셰이핑 |

---

## 3. Direct-Action (`da`) 모드의 아키텍처 혁신

전통적인 TC 아키텍처에서는:
1. 분류기(Classifier)가 패킷을 읽어 `classid`를 반환합니다.
2. TC 코어는 해당 `classid`에 바인딩된 별도의 `sch_act` 모듈(예: `act_gact`, `act_mirred`)을 순차적으로 호출하여 패킷을 드롭하거나 리다이렉트합니다.
이 방식은 불필요한 메모리 참조와 함수 호출 간접 비용(Indirection Overhead)을 유발했습니다.

**Direct-Action 모드**에서는 eBPF 프로그램이 직접 커널 액션 코드를 반환합니다:
```c
SEC("tc")
int my_tc_filter(struct __sk_buff *skb) {
    // 패킷 파싱 및 L3/L4 검사
    if (is_ddos_attack(skb))
        return TC_ACT_SHOT; // 즉시 드롭!
        
    if (is_cluster_service(skb)) {
        bpf_skb_store_bytes(...); // DNAT
        return bpf_redirect(target_ifindex, 0); // 즉시 리다이렉트!
    }
    
    return TC_ACT_OK; // 정상 스택 전달
}
```

### 3.1 TC 반환 코드(Return Codes)
- **`TC_ACT_OK` (0)**: 패킷을 상위 네트워크 스택(IP 레이어)으로 통과시킵니다.
- **`TC_ACT_SHOT` (2)**: 패킷을 즉시 폐기하고 소켓 버퍼 메모리를 해제합니다.
- **`TC_ACT_UNSPEC` (-1)**: 다음 분류기로 패킷을 넘깁니다.
- **`TC_ACT_REDIRECT` (7)**: `bpf_redirect()` 헬퍼를 통해 스택을 바이패스하고 목적지 인터페이스의 송수신 큐로 직접 꽂아 넣습니다.

---

## 4. 클라우드 네이티브 네트워킹 응용: 헤더 변환과 메타데이터 마킹

### 4.1 서비스 프록시 (NAT Bypass)
Cilium과 같은 eBPF 데이터 플레인은 쿠버네티스 ClusterIP로 향하는 패킷을 가로채어:
1. `bpf_skb_store_bytes()`를 호출하여 `ip_hdr->daddr`을 실제 파드의 엔드포인트 IP로 재작성합니다.
2. `bpf_l3_csum_replace()`와 `bpf_l4_csum_replace()`로 체크섬을 점진적으로 재계산(Incremental Checksum Update)합니다.
3. `bpf_redirect()`를 통해 가상 이더넷(`veth`)으로 직통 전송하여 호스트 라우팅 테이블 조회를 생략합니다.

### 4.2 QoS 우선순위 및 대역폭 제어
- `skb->priority` 필드에 특정 클래스 번호를 기입하여, 하단의 HTB(Hierarchical Token Bucket)나 FQ-CoDel 큐잉 디시플린이 트래픽을 차등 대역폭으로 전송하도록 제어합니다.
