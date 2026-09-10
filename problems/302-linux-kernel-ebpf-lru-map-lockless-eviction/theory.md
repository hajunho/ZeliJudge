# 이론 정리: 리눅스 커널 eBPF LRU 맵의 락 경합 회피와 이중 리스트 축출 아키텍처

## 1. eBPF LRU 맵(`BPF_MAP_TYPE_LRU_HASH`)의 설계 배경

리눅스 커널의 eBPF 프로그램(XDP, TC, 소켓 필터 등)은 네트워크 패킷 처리 경로에서 나노초(ns) 단위로 실행됩니다. 일반적인 `BPF_MAP_TYPE_HASH`는 엔트리 수가 `max_entries`에 도달하면 `-ENOSPC` 오류를 반환하며 신규 삽입이 실패합니다.

사용자 공간 데몬이 주기적으로 오래된 항목을 삭제하는 방식은 수천만 PPS(Packets Per Second)의 네트워크 트래픽 환경에서 실시간성을 보장할 수 없습니다. 따라서 커널 공간 내부에서 실시간으로 오래된 항목을 밀어내는 LRU(Least Recently Used) 기능이 필수적입니다.

그러나 전통적인 LRU 캐시 구현은 모든 읽기(`bpf_map_lookup_elem`)마다 전역 LRU 연결 리스트를 조작해야 하므로, 멀티코어 환경에서 심각한 병목을 유발합니다:
1. **스핀락 경합**: 모든 CPU 코어가 동일한 리스트 보호용 스핀락을 획득하려 경쟁하여 CPU 사용률이 100%로 치솟고 패킷 드롭이 발생합니다.
2. **캐시 라인 바운싱**: 리스트 포인터 갱신으로 인해 CPU L1/L2/L3 캐시 무효화 메시지(Cache Coherency Invalidation)가 버스를 점유합니다.

---

## 2. 리눅스 커널의 해결책: `kernel/bpf/bpf_lru_list.c`

리눅스 커널은 메타(구 Facebook) 엔지니어 Martin KaFai Lau에 의해 설계된 락 분할 및 이중 리스트 LRU 알고리즘을 사용합니다.

```
       [ 신규 노드 삽입 ]
               │
               ▼
   [ Per-CPU Pending List ]  (로컬 락/무락 버퍼링)
               │ (배치 Flush)
               ▼
   [ Inactive List (비활성) ] ◄─── 강등 (Demotion) ───┐
     Head               Tail                          │
      │                  │ (스캔)                     │
      │                  ▼                            │
      │           [ ref == 1 ? ]                      │
      │             │         │                       │
      │         (Yes)        (No)                     │
      │             │         │                       │
      │             ▼         ▼                       │
      │      [ Active List ] [ Victim 축출! ]         │
      │        Head     Tail                          │
      │         │        │                            │
      └─────────┴────────┴────────────────────────────┘
```

### 1) Lockless Lookup과 `BPF_LRU_NODE_ACTIVE`
- `bpf_map_lookup_elem()` 실행 시 어떠한 리스트 락도 획득하지 않습니다.
- 노드의 플래그 비트(`node->ref`)에 대해 단 한 번의 원자적 비트 연산(`set_bit`)만 수행합니다.
- 이로써 읽기 경로는 거의 무락(Lock-Free) 수준의 극단적인 속도를 유지합니다.

### 2) 이중 리스트 구조 (Active vs Inactive)
- **Inactive List**: 주로 최근에 유입되었거나 참조 빈도가 낮은 콜드(Cold) 노드들이 대기합니다. 실제 축출은 항상 이 리스트의 꼬리(Tail)에서 이루어집니다.
- **Active List**: 활발하게 재참조된 핫(Hot) 노드들이 보관됩니다. 이 리스트에 머무는 동안에는 직접 축출되지 않습니다.

### 3) 2차 기회 회전(Second-Chance Page-Replacement 유사)
- 용량이 꽉 차서 신규 엔트리를 위해 메모리를 확보해야 할 때, 엔진은 `Inactive List`의 꼬리부터 역방향 스캔합니다:
  - 노드의 `ref` 비트가 `1`이면: "이 노드는 비활성 리스트에 있는 동안 최소 1번 이상 참조되었다"는 의미입니다. 따라서 `ref = 0`으로 리셋하고 `Active List`의 헤드로 승격(Promotion)시킵니다.
  - 노드의 `ref` 비트가 `0`이면: "비활성 리스트에 머무는 동안 단 한 번도 참조되지 않았다"는 의미이므로, 즉시 해당 노드를 **희생자(Victim)**로 선택하여 해시 테이블에서 축출하고 재사용합니다.

### 4) 활성 리스트 크기 제어와 강등(Demotion)
- 승격이 지속되어 `Active List`의 크기가 `Inactive List`보다 커지면, 캐시의 신선도를 유지하기 위해 `Active List`의 꼬리 노드를 `Inactive List`의 헤드로 강등시킵니다.

---

## 3. 핵심 설계 원칙의 의의

이 알고리즘은 가상 메모리 관리자(VMM)의 페이지 교체 알고리즘(Two-List Clock Algorithm)을 커널 eBPF 고속 해시 테이블에 성공적으로 이식한 모범 사례입니다.
- **스케일러빌리티**: 코어 수가 늘어나도 `LOOKUP` 병목이 발생하지 않습니다.
- **단기 스캔 내성(Scan Resistance)**: 한 번만 조회되고 사라지는 일회성 트래픽(DDoS 공격 패킷 등)이 기존의 장기 활성 세션(Active List)을 즉시 밀어내지 못하도록 강력하게 방어합니다.
