# #378 - 리눅스 커널 트래픽 제어 (TC / cls_bpf): Direct-Action (da) 모드, 패킷 분류·헤더 변환(Mangle) 및 리다이렉트 엔진

## 📖 문제 배경과 역사적 맥락

> *"전통적인 Linux Traffic Control (TC) 프레임워크는 분류기(Classifier)와 동작(Action)을 엄격히 분리하여, 분류기가 클래스 ID를 반환하면 별도의 액션 모듈이 패킷을 처리하는 다단계 파이프라인 구조를 취했다. 그러나 고성능 클라우드 네이티브 네트워킹(Cilium, Calico) 환경에서는 이 구조의 오버헤드가 치명적이었다. `cls_bpf`의 Direct-Action(`da`) 모드는 단일 eBPF 프로그램이 패킷의 파싱, 헤더 수정(Mangle), 그리고 최종 처분(`TC_ACT_OK`, `TC_ACT_SHOT`, `TC_ACT_REDIRECT`)을 커널 컨텍스트 스위칭 없이 즉시 단일 패스로 결정하는 혁신을 달성했다."*  
> — **Linux Kernel Network Subsystem (`net/sched/cls_bpf.c`, `include/uapi/linux/pkt_cls.h`)**

현대 쿠버네티스(Kubernetes) 환경에서 수만 개의 파드(Pod) 간 통신을 초저지연으로 중계하기 위해, 전통적인 `iptables`/`conntrack` 기반 라우팅은 eBPF 기반의 **TC(Traffic Control) 서브시스템**으로 급격히 전환되었습니다.

XDP(eXpress Data Path)가 드라이버 수신 링 버퍼 단계에서 `sk_buff` 할당 전에 초고속으로 작동하는 반면, **TC eBPF (`cls_bpf`)**는 다음과 같은 독보적인 강점을 가집니다:
1. **양방향 제어(Ingress & Egress)**: 수신(Ingress)뿐만 아니라 송신(Egress) 경로에서도 완벽하게 작동합니다.
2. **소켓 버퍼(`sk_buff`) 완전 접근**: 소켓 구조체, 메타데이터, QoS 우선순위(`skb->priority`), 방화벽 마크(`skb->mark`)를 직접 수정할 수 있습니다.
3. **Direct-Action (`da`) 모드**: 전통적 TC의 번거로운 액션 모듈 체인을 건너뛰고 eBPF 프로그램이 직접 액션 코드(`TC_ACT_*`)를 반환하여 처리 속도를 비약적으로 향상시킵니다.

```
                     [Linux Kernel TC Packet Pipeline]
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           ▼                                                   ▼
   [Ingress Hook (clsact)]                             [Egress Hook (clsact)]
           │                                                   │
   cls_bpf Program (da mode)                           cls_bpf Program (da mode)
           │                                                   │
  ┌────────┼────────┬────────┐                        ┌────────┼────────┬────────┐
  ▼        ▼        ▼        ▼                        ▼        ▼        ▼        ▼
TC_ACT   TC_ACT   TC_ACT   Header                    TC_ACT   TC_ACT   TC_ACT   Header
 _OK     _SHOT    _REDIR    Mangle                    _OK     _SHOT    _REDIR    Mangle
 (Pass)  (Drop)   (bpf_    (NAT/VLAN)                 (Pass)  (Drop)   (bpf_    (QoS/VLAN)
                  redir)                                               redir)
```

### TC cls_bpf Direct-Action의 핵심 메커니즘
1. **액션 반환 코드**:
   - `TC_ACT_OK` (0): 패킷을 정상적인 상위 네트워크 스택으로 통과시킵니다.
   - `TC_ACT_SHOT` (2): 패킷을 즉시 폐기(Drop)합니다.
   - `TC_ACT_REDIRECT` (7): 패킷을 스택을 거치지 않고 지정된 다른 네트워크 인터페이스(예: 파드 veth)로 고속 바이패스 전송합니다.
2. **패킷 헤더 변환 (Mangle)**:
   - 클러스터 내부 서비스 프록시(Kube-Proxy 대체)를 위해 목적지 IP를 파드 IP로 실시간 변환(DNAT)하거나 출발지 IP를 변환(SNAT)합니다.
   - 메타데이터 마킹: `skb->mark` 및 `skb->priority`를 주입하여 하드웨어 트래픽 셰이핑(QoS)을 수행합니다.
3. **VLAN 캡슐화 제어**:
   - 멀티테넌트 네트워크 가상화를 위해 `vlan_push` 및 `vlan_pop` 동작을 단일 패스에서 수행합니다.

본 과제에서는 리눅스 커널 `cls_bpf`의 Direct-Action 패킷 처리 파이프라인을 정밀하게 모델링하는 시뮬레이션 엔진을 구현합니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "initial_state": {
    "interfaces": ["eth0", "veth_pod1"]
  },
  "events": [
    {
      "type": "ATTACH_FILTER",
      "params": {
        "iface": "eth0",
        "hook": "INGRESS",
        "filter_name": "dnat_redirect_bpf",
        "rules": [
          {
            "match": {"dst_ip": "1.2.3.4", "dst_port": 80},
            "action": {
              "type": "TC_ACT_REDIRECT",
              "target_iface": "veth_pod1",
              "set_dst_ip": "10.244.0.5",
              "set_mark": 100
            }
          },
          {
            "match": {"dst_port": 23},
            "action": {"type": "TC_ACT_SHOT"}
          }
        ]
      }
    },
    {
      "type": "INGRESS_PACKET",
      "params": {
        "iface": "eth0",
        "packet": {
          "id": "p1",
          "src_ip": "8.8.8.8",
          "dst_ip": "1.2.3.4",
          "dst_port": 80,
          "protocol": "TCP"
        }
      }
    },
    {
      "type": "INGRESS_PACKET",
      "params": {
        "iface": "eth0",
        "packet": {
          "id": "p2",
          "src_ip": "8.8.8.8",
          "dst_ip": "1.2.3.4",
          "dst_port": 23,
          "protocol": "TCP"
        }
      }
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `initial_state`:
   - `interfaces`: 초기 등록할 네트워크 인터페이스 식별자 목록 (기본값 `["eth0", "eth1", "veth0"]`).
2. `events`: 다음 4가지 이벤트가 발생합니다:
   - `ATTACH_FILTER`:
     - 파라미터: `iface`, `hook` (`"INGRESS"` 또는 `"EGRESS"`), `filter_name`, `rules` 배열.
     - 동작: 지정된 인터페이스의 훅에 새 필터 등록. 상태: `FILTER_ATTACHED`.
   - `DETACH_FILTER`:
     - 파라미터: `iface`, `hook`, `filter_name`.
     - 동작: 해당 필터를 훅에서 제거. 상태: `FILTER_DETACHED`.
   - `INGRESS_PACKET`:
     - 파라미터: `iface`, `packet` (사전: `id`, `src_ip`, `dst_ip`, `src_port`, `dst_port`, `protocol`, `vlan_id`, `mark`, `priority` 등).
     - 동작:
       1. 수신 인터페이스의 `rx_packets` 1 증가.
       2. `INGRESS` 훅에 부착된 필터의 규칙들을 순서대로 검사하여 첫 번째로 매칭되는 규칙 적용.
       3. 매칭된 액션에서 헤더 수정(`set_dst_ip`, `set_src_ip`, `set_mark`, `set_priority`, `vlan_push`, `vlan_pop`)이 발생하면 `mangled` 플래그 활성화 및 통계 1 증가.
       4. 최종 액션:
          - `TC_ACT_SHOT`: 패킷 폐기, 해당 인터페이스의 `dropped` 1 증가, 상태: `PACKET_DROPPED`.
          - `TC_ACT_REDIRECT`: 패킷 리다이렉트, 수신 인터페이스의 `redirected` 1 증가, 목적지 인터페이스의 `tx_packets` 1 증가, 상태: `PACKET_REDIRECTED`.
          - `TC_ACT_OK` (또는 매칭 규칙 없음): 패킷 통과, 상태: `PACKET_PASSED`.
   - `EGRESS_PACKET`:
     - 파라미터: `iface`, `packet`.
     - 동작:
       1. `EGRESS` 훅 필터 규칙 평가.
       2. 헤더 변환 시 `mangled` 통계 증가.
       3. 최종 액션:
          - `TC_ACT_SHOT`: 패킷 폐기, `dropped` 1 증가, 상태: `PACKET_DROPPED`.
          - `TC_ACT_REDIRECT`: 리다이렉트, `redirected` 1 증가, 목적지 `tx_packets` 1 증가, 상태: `PACKET_REDIRECTED`.
          - `TC_ACT_OK`: 정상 송신, 송신 인터페이스의 `tx_packets` 1 증가, 상태: `PACKET_TRANSMITTED`.

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 완료 후 최종 네트워크 인터페이스 통계를 압축 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 표준 출력에 인쇄합니다:

```json
{
  "interfaces": {
    "eth0": {
      "stats": {
        "rx_packets": 2,
        "tx_packets": 0,
        "dropped": 1,
        "redirected": 1,
        "mangled": 1
      },
      "ingress_filter_count": 1,
      "egress_filter_count": 0
    },
    "veth_pod1": {
      "stats": {
        "rx_packets": 0,
        "tx_packets": 1,
        "dropped": 0,
        "redirected": 0,
        "mangled": 0
      },
      "ingress_filter_count": 0,
      "egress_filter_count": 0
    }
  },
  "total_dropped": 1,
  "total_redirected": 1,
  "total_mangled": 1,
  "history": [
    {
      "epoch": 1,
      "event": "ATTACH_FILTER",
      "status": "FILTER_ATTACHED",
      "detail": "cls_bpf filter dnat_redirect_bpf attached to eth0 INGRESS."
    }
  ]
}
```

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 패킷 카운트, 헤더 변환(Mangle) 여부, 리다이렉트 경로가 완벽히 일치해야 합니다.
2. Direct-Action(`da`) 모드의 우선순위 매칭 및 상태 전이를 정확히 수행해야 합니다.
3. Windows 환경에서의 UTF-8 입출력을 준수해야 합니다.
