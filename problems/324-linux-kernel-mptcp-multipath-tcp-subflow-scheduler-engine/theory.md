# Linux Kernel MPTCP: 다중 경로 TCP 전송 계층과 차세대 인터넷 아키텍처

## 1. MPTCP (RFC 8684)의 탄생 배경

전통적인 인터넷 전송 계층 프로토콜인 TCP(RFC 793)는 **"단일 연결 = 단일 IP 인터페이스"**라는 엄격한 1:1 바인딩에 기반을 두고 있습니다:
$$	ext{Connection} = (IP_{src}, Port_{src}, IP_{dst}, Port_{dst})$$
그러나 현대의 네트워크 디바이스(스마트폰, 5G CPE, 데이터센터 멀티홈 서버)는 둘 이상의 물리적 네트워크 어댑터를 보유하고 있습니다. 이동 중 Wi-Fi 신호가 약해져 LTE/5G로 전환될 때, 단일 IP 바인딩 때문에 기존 TCP 소켓은 RST 패킷을 받으며 파괴(`Broken Pipe`)될 수밖에 없었습니다.

MPTCP(Multipath TCP)는 **단일 TCP 세션 내에서 복수의 TCP 하위 연결(Subflow)을 묶어 하나의 가상 스트림으로 제공**함으로써 완벽한 무중단 핸드오버(Make-Before-Break / Break-Before-Make)와 대역폭 집합(Bandwidth Aggregation)을 실현합니다.

---

## 2. 이중 시퀀스 번호 공간과 DSS (Data Sequence Signal)

MPTCP의 핵심 아키텍처는 **2계층 시퀀스 번호 공간의 분리**입니다.

### 2.1 메타 소켓 DSN (Data Sequence Number)
- 애플리케이션 계층이 소비하는 64비트 단조 증가 시퀀스 번호입니다.
- 개별 서브플로우의 패킷 손실이나 도착 순서 역전과 무관하게, 전체 연결 관점에서의 연속된 바이트 스트림 위치를 나타냅니다.

### 2.2 서브플로우 SSN (Subflow Sequence Number)
- 각 물리 경로(Wi-Fi, 5G 등)별로 독립적으로 할당되는 표준 32비트 TCP 시퀀스 번호입니다.
- 기존의 레거시 라우터, 방화벽, NAT 미들박스(Middlebox)는 MPTCP의 존재를 몰라도 일반 TCP 패킷으로 인식하여 정상 포워딩합니다.

### 2.3 DSS 옵션 헤더 매핑
TCP 헤더의 옵션 필드(`Kind = 30`, `Subtype = 2`)에 포함되는 DSS는 다음 튜플을 포함합니다:
$$	ext{DSS} = \langle DSN, SSN, 	ext{Length}, 	ext{Data\_ACK} angle$$
수신측 MPTCP 스택은 DSS를 읽어 서로 다른 서브플로우에서 도착한 세그먼트들을 메타 소켓의 DSN 순서대로 올바르게 정렬 및 재조립합니다.

---

## 3. 리눅스 커널 MPTCP 패킷 스케줄러 (`net/mptcp/sched.c`)

MPTCP 송신 엔진은 어떤 서브플로우에 다음 DSN 세그먼트를 실어 보낼지 결정해야 합니다.

### 3.1 `minrtt` 스케줄러
1. **혼잡 윈도우 검사**:
   $$available\_window = \max(0, cwnd_i - in\_flight_i)$$
   $available\_window \ge segment\_size$를 만족하는 서브플로우만 전송 후보가 됩니다.
2. **지연 시간 우선순위**:
   가용 윈도우가 남아있는 일반(Active) 서브플로우 중 평활 왕복 시간($srtt$)이 가장 짧은 경로를 선택합니다:
   $$i^* = rg\min_{i \in 	ext{Active}, avail_i \ge MSS} srtt_i$$
3. **스필오버 및 백업 활성화**:
   최저 RTT 경로의 $cwnd$가 가득 차면, 차순위 RTT 경로로 트래픽이 자연스럽게 분산(Spillover)됩니다. 모든 일반 경로가 포화되면 비로소 `backup` 플래그가 지정된 고비용(예: 위성/종량제 셀룰러) 경로를 사용합니다.

### 3.2 `redundant` 스케줄러
- 금융 거래, 자율주행 원격 제어, 초고신뢰 저지연 통신(URLLC)을 위해 설계되었습니다.
- 모든 가용 서브플로우에 동일한 DSN 세그먼트의 복제본을 동시에 송신합니다.
- 수신측은 가장 먼저 도착한 세그먼트를 처리하고, 늦게 도착한 중복 세그먼트는 DSN 중복 감지를 통해 커널 수준에서 자동 폐기(`Duplicate Drop`)합니다.

---

## 4. 무중단 경로 복구 (Failover Retransmission)

특정 서브플로우가 기지국 이탈로 인해 갑작스럽게 단절(`FAILED`)되었을 때:
1. 커널은 해당 서브플로우를 비활성화하고 잔여 `in_flight`를 회수합니다.
2. 해당 서브플로우에 탑승했으나 아직 상위 Data ACK를 받지 못한 미확인 DSN 세그먼트들을 즉시 추출합니다.
3. 이 세그먼트들을 건강한 다른 서브플로우(예: 5G)의 송신 큐에 재스케줄링하여 새로운 $SSN$으로 재송신합니다.
4. 애플리케이션 입장에서는 일시적인 지연만 발생할 뿐, 소켓 연결이 끊어지지 않고 투명하게 데이터 전송이 지속됩니다.
