# 리눅스 커널 Netfilter conntrack 헬퍼 및 NAT ALG 이론 백서

## 1. 개요 및 설계 문제

상태 기반 패킷 필터링(Stateful Packet Inspection, SPI)과 NAPT(Network Address Port Translation)는 L3(IP) 및 L4(TCP/UDP) 헤더만을 조작합니다.
그러나 일부 구형 또는 멀티미디어 프로토콜은 **제어 평면(Control Plane)과 데이터 평면(Data Plane)이 분리**되어 있으며, 데이터 전송에 사용할 소켓 주소를 제어 패킷의 애플리케이션 데이터 본문에 평문으로 기록합니다:
- **FTP (RFC 959)**: TCP 21번 포트로 로그인 후, 파일 전송 시 능동 모드(`PORT`) 또는 수동 모드(`PASV`)를 통해 별도의 동적 데이터 포트를 협상합니다.
- **SIP / SDP (RFC 3261 / RFC 4566)**: 시그널링은 UDP 5060번 포트로 교환하지만, 실제 음성/영상 RTP 스트림은 동적으로 할당된 고위 포트(예: UDP 40000번대)를 통해 양방향 전송됩니다.

---

## 2. 동적 기대치 (Dynamic Expectation)

방화벽이 1024번 이상의 모든 포트를 개방해 두는 것은 심각한 보안 침해(CVE)를 초래합니다.
리눅스 커널은 **기대치(`struct nf_conntrack_expect`, `net/netfilter/nf_conntrack_helper.c`)**를 통해 최소 권한 핀홀을 구현합니다:
- 제어 패킷에서 협상된 대상 포트와 피어 IP를 추출합니다.
- 해당 튜플에 대해 유효 시간(기본 30초~300초)을 갖는 임시 기대치를 `expect_hash` 테이블에 등록합니다.
- 첫 번째 데이터 패킷이 유입되면, 커널은 일반 룰셋(`INPUT/FORWARD`)을 통과시키기 전에 기대치 테이블을 조회하여 패킷을 **`RELATED`** 상태로 태깅합니다.
- `iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT` 단 1줄의 룰로 모든 동적 채널이 안전하게 통과됩니다.

---

## 3. TCP 시퀀스 번호 맹글링과 역방향 확인응답 보정 (`nf_nat_helper.c`)

NAT 라우터가 페이로드 내부의 사설 IP를 공인 IP로 변환하면 패킷 길이가 필연적으로 변화합니다:
- 원본: `PORT 10,0,0,2,195,80` (21 바이트)
- 변환: `PORT 203,0,113,195,156,65` (25 바이트) $\implies \Delta = +4$

이 순간 이후, 클라이언트가 전송하는 TCP 시퀀스 번호와 서버가 기대하는 시퀀스 번호 사이에 4바이트의 영구적 오차가 발생합니다:
1. **송신 패킷 (Client $	o$ Server)**:
   - 클라이언트의 TCP 스택은 원본 크기를 기준으로 $seq$를 전송합니다.
   - Netfilter는 패킷이 라우터를 통과할 때 $seq \leftarrow seq + \Delta$로 가산 보정합니다.
2. **수신 패킷 (Server $	o$ Client)**:
   - 서버는 4바이트 늘어난 데이터를 수신했으므로 $ack + 4$를 회신합니다.
   - 하지만 클라이언트 TCP 스택은 자신이 보낸 원본 크기만을 알고 있으므로, 보정 없이 전달되면 *"아직 보내지도 않은 데이터를 서버가 ACK했다"*고 판단하여 연결을 즉시 리셋(`RST`)해 버립니다.
   - Netfilter는 수신 패킷의 확인응답 번호를 $ack \leftarrow ack - \Delta$로 감산 보정하여 클라이언트에 전달합니다.
