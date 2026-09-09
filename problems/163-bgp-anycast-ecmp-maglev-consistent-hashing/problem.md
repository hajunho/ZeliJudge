# Problem #163: 로드 밸런서 1대 늘렸을 뿐인데 왜 수만 명의 연결이 일제히 끊어져요?!: BGP Anycast ECMP 패킷 리셔플링과 TCP RST 폭발 참사 vs Google Maglev 일관된 해싱 (BGP Anycast ECMP Reshuffling & Maglev Consistent Hashing)

---

## 🏢 실무 장애 시나리오

초당 수백만 건의 트래픽을 처리하는 글로벌 핀테크 결제 게이트웨이 및 파일 전송 CDN 서비스는 **BGP Anycast**와 상위 Tier-1 스위치의 **ECMP(Equal-Cost Multi-Path)** 라우터를 통해 트래픽을 3대의 고성능 L4 소프트웨어 로드 밸런서(Director-1, 2, 3)로 분산 처리하고 있었습니다.

블랙 프라이데이 트래픽 급증을 대비하여, 데브옵스 팀은 L4 디렉터 계층을 3대에서 4대로 증설하는 **오토스케일링(HPA Scale-out)** 작업을 실행했습니다.
새로운 디렉터(`director-4`)가 클러스터에 합류하고 상위 BGP 라우터에 자신을 알린 바로 그 순간, 전 세계 모니터링 시스템에 대재앙을 알리는 알람이 쏟아졌습니다:

1. **대규모 TCP Reset(RST) 폭발**: 수십만 명의 사용자가 `Connection reset by peer`, `Broken pipe`, `WebSocket closed unexpectedly` 에러를 맞으며 결제 세션과 대용량 파일 업로드가 일제히 중단되었습니다.
2. **연쇄 재접속 스톰(Thundering Herd)**: 끊어진 클라이언트들이 일제히 SYN 패킷을 재전송하며 백엔드 서버로 밀려들어 DB와 API 서버 CPU가 100%로 마비되었습니다.

패킷 캡처(Wireshark/tcpdump) 분석 결과, 치명적인 현상이 발견되었습니다:
- 클라이언트가 맺은 기존 TCP 연결의 첫 번째 패킷(`SYN`)은 `director-1`을 거쳐 `backend-1`에 정상 도착하여 연결이 수립되었습니다.
- 하지만 디렉터가 4대로 늘어난 직후, 상위 ECMP 스위치는 해시 모듈로 값($K: 3 \to 4$)이 변경되면서 해당 플로우의 두 번째 데이터 패킷(`DATA`)을 신규 노드인 `director-4`로 전송했습니다.
- `director-4`는 로컬 커넥션 트래킹(Conntrack) 테이블에 해당 플로우 정보가 없자, 나이브 라우팅을 수행하여 패킷을 `backend-2`로 전달했습니다.
- `backend-2`는 자신에게 존재하지 않는 낯선 TCP 연결의 패킷을 수신하자마자 **RFC 793 규격에 따라 즉시 TCP RST(Reset) 패킷을 클라이언트로 발송하여 연결을 강제 폭파**시킨 것이었습니다!

인프라의 동적 스케일아웃과 장애 조치 시에도 기존 TCP 세션을 단 1건도 파괴하지 않으려면 어떻게 해야 할까요?
여러분이 Google Maglev(NSDI '16) 논문의 핵심인 **소수 크기 룩업 테이블($M$)과 결정론적 의사 난수 순열 기반의 일관된 해싱(Consistent Hashing) 알고리즘**을 구현하여, 어떠한 ECMP 패킷 리셔플링 속에서도 0 TCP RST 무중단 페일오버를 달성해주세요!

---

## 🎯 문제 설명

L4 로드 밸런서 클러스터 설정(`config`)과 일련의 네트워크 패킷 및 인프라 관리 이벤트(`operations`)를 순차적으로 처리하여, 최종 처리 결과 요약 통계(`get_summary()`)를 반환하는 `solve(input_data)` 함수를 작성하세요.

### 1. 시스템 컴포넌트 동작 규칙

#### 1) 상위 BGP ECMP 라우터 디스패치
- 라우터는 들어오는 패킷의 5-tuple(`flow_key`)을 하드웨어 해시하여 활성 디렉터 노드 목록(알파벳 오름차순 정렬) 중 하나를 선택합니다:
  $$\text{Director} = \text{sorted\_directors}\left[\text{hash\_32}(\text{flow\_key}, \text{seed}=99) \pmod K\right]$$

#### 2) L4 디렉터(Director) 노드 라우팅
- **로컬 Conntrack 테이블 확인**:
  - `enable_conntrack == True`이고 `flow_key`가 로컬 테이블에 존재하며 매핑된 백엔드가 현재 살아있다면, 기존 백엔드로 즉시 라우팅합니다. (`FIN` 패킷 처리 후에는 해당 conntrack 항목 삭제)
- **Conntrack 미스(Miss) 시 폴백 라우팅**:
  - **`MAGLEV`**:
    - 모든 디렉터는 동일한 $M$ 크기의 Maglev 룩업 테이블을 보유합니다.
    - $\text{slot} = \text{hash\_32}(\text{flow\_key}, \text{seed}=0) \pmod M$
    - 테이블의 해당 슬롯에 매핑된 백엔드로 라우팅하고, 로컬 conntrack에 등록합니다.
  - **`NAIVE_MODULO`**:
    - $\text{idx} = \text{hash\_32}(\text{flow\_key}, \text{seed}=0) \pmod N_{\text{backends}}$
    - 해당 인덱스의 백엔드로 라우팅합니다.
  - **`ROUND_ROBIN`**:
    - 활성 백엔드 목록을 순차적으로 라운드로빈 라우팅합니다.

#### 3) 백엔드(Backend) 서버의 TCP 상태 머신
- **`SYN` 패킷**:
  - 백엔드는 연결을 수락하고 `flow_key`를 `ESTABLISHED` 상태로 등록합니다.
  - 결과: `SUCCESS_NEW_CONNECTION`
- **`DATA` / `ACK` 패킷**:
  - 해당 백엔드에 `flow_key`가 등록되어 있다면 정상 처리합니다. (`SUCCESS_DATA_PROCESSED`)
  - **만약 등록되어 있지 않다면(잘못된 백엔드로 도착)**, 즉시 **TCP RST**를 반환하여 연결이 폭파됩니다! (`TCP_RST_CONNECTION_SEVERED`)
- **`FIN` 패킷**:
  - 등록되어 있다면 세션을 닫고 정리합니다. (`SUCCESS_CLOSED`)
  - 등록되어 있지 않다면 **TCP RST**가 발생합니다. (`TCP_RST_CONNECTION_SEVERED`)

#### 4) 관리자 인프라 이벤트 (`ADMIN`)
- `ADD_DIRECTOR`: 새로운 디렉터 노드 추가 (ECMP $K$ 증가).
- `REMOVE_DIRECTOR`: 디렉터 노드 제거 (ECMP $K$ 감소).
- `ADD_BACKEND`: 신규 백엔드 노드 추가 (Maglev 테이블 재계산).
- `REMOVE_BACKEND`: 장애 백엔드 노드 제거 (Maglev 테이블 재계산).

---

## 📥 입력 형식 (Input Format)

```json
{
  "config": {
    "director_type": "MAGLEV",
    "enable_conntrack": true,
    "lookup_table_size": 997,
    "directors": ["director-1", "director-2", "director-3"],
    "backends": ["backend-1", "backend-2", "backend-3", "backend-4"]
  },
  "operations": [
    {
      "type": "PACKET",
      "flow_key": "192.168.1.1:50000->10.0.0.1:443/TCP",
      "packet_type": "SYN"
    },
    {
      "type": "PACKET",
      "flow_key": "192.168.1.1:50000->10.0.0.1:443/TCP",
      "packet_type": "DATA"
    },
    {
      "type": "ADMIN",
      "action": "ADD_DIRECTOR",
      "director_id": "director-4"
    },
    {
      "type": "PACKET",
      "flow_key": "192.168.1.1:50000->10.0.0.1:443/TCP",
      "packet_type": "DATA"
    },
    {
      "type": "PACKET",
      "flow_key": "192.168.1.1:50000->10.0.0.1:443/TCP",
      "packet_type": "FIN"
    }
  ]
}
```

---

## 📤 출력 형식 (Output Format)

```json
{
  "total_packets": 4,
  "success_packets": 4,
  "tcp_rst_count": 0,
  "rst_rate_percent": 0.0,
  "conntrack_hits": 2,
  "conntrack_misses": 2,
  "active_directors": 4,
  "active_backends": 4,
  "backend_packet_distribution": {
    "backend-1": 0,
    "backend-2": 4,
    "backend-3": 0,
    "backend-4": 0
  }
}
```

---

## 💡 입출력 예시

### 예제 1: 정상 안정 트래픽 (Case 1 Baseline)
- **상황**: 디렉터 3대, 백엔드 4대. 20개 플로우 총 80개 패킷 순차 전송.
- **결과**: 인프라 변경이 없으므로 Conntrack 적중률 75%, TCP RST 0건, 성공률 100%.

### 예제 2: ECMP 리셔플 시 ROUND_ROBIN 폴백 참사 (Case 2 Disaster)
- **상황**: 15개 플로우 진행 도중 `director-4` 증설 (K: 3 $	o$ 4).
- **결과**:
  - `ROUND_ROBIN` 폴백 디렉터는 신규 유입된 기존 플로우의 패킷을 엉뚱한 백엔드로 분배.
  - 백엔드에서 22건의 **TCP RST** 폭발 (`rst_rate_percent: 36.67%`), 대규모 세션 단절 발생.

### 예제 3: 동일 조건 하 Google Maglev 구원 (Case 3 Rescue)
- **상황**: 예제 2와 동일하게 15개 플로우 진행 중 `director-4` 증설.
- **결과**:
  - `director-4`는 비어있는 Conntrack에도 불구하고 동일한 Maglev 룩업 테이블을 통해 패킷을 기존 백엔드로 정확히 전달.
  - **TCP RST 0건 (`rst_rate_percent: 0.0%`)**, 60개 패킷 100% 무중단 성공 처리.

---

## ⚙️ 제약 조건 (Constraints)
- $M$은 항상 홀수 소수 (기본값: $997$).
- $1 \le N_{\text{directors}} \le 16$
- $1 \le N_{\text{backends}} \le 64$
- $1 \le N_{\text{operations}} \le 500$
- `rst_rate_percent`는 소수점 둘째 자리까지 반올림(`round(x, 2)`).
