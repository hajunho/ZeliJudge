# 문제 253 이론: TCP 4-Tuple과 아웃바운드 포트 고갈, TIME_WAIT 라이프사이클 및 tcp_tw_reuse 아키텍처

---

## 1. TCP 4-Tuple과 Ephemeral Port 고갈의 수학

인터넷 프로토콜 스택에서 하나의 완전한 TCP 연결은 다음의 **4개 튜플(4-Tuple)**로 정의됩니다:
$$	ext{Connection ID} = (	ext{Source IP}, 	ext{Source Port}, 	ext{Destination IP}, 	ext{Destination Port})$$

```
+-------------------------------------------------------------+
| Outbound Proxy / API Gateway Egress Bottleneck              |
|                                                             |
| Source IP:      192.168.1.10 (Single Egress IP)             |
| Dest IP:        10.0.0.50    (Fixed Backend Service)        |
| Dest Port:      8080         (Fixed HTTP Port)              |
|                                                             |
| Variable:       Source Port  (32768 ~ 60999 = 28,232 ports) |
+-------------------------------------------------------------+
```

백엔드 서버의 IP와 포트가 고정되어 있고 프록시의 송신 IP가 1개뿐이라면, 호스트가 동시에 맺을 수 있는 고유한 연결의 수는 **임시 포트(Ephemeral Port)의 개수(최대 28,232개)**를 넘을 수 없습니다.

---

## 2. 능동 종료(Active Close)와 TIME_WAIT ($2	ext{MSL} = 60	ext{s}$)의 필연성

TCP 연결을 먼저 끊는 쪽(Active Closer)은 소켓을 즉시 파괴하지 않고 반드시 `TIME_WAIT` 상태로 진입하여 $2 	imes 	ext{MSL} = 60$초 동안 유지합니다.

### TIME_WAIT의 두 가지 필수 목적:
1. **마지막 ACK 유실 보상**: 클라이언트가 보낸 최종 ACK가 유실되면, 서버는 FIN을 재전송합니다. 클라이언트가 TIME_WAIT 상태를 유지하고 있어야 재전송된 FIN에 대해 다시 ACK를 보내 서버가 정상적으로 세션을 닫을 수 있습니다.
2. **지연 패킷(Duplicate Segments)의 소멸 보장**: 네트워크 라우터나 버퍼에 갇혀있던 과거 세션의 지연 패킷이 새로 생성된 동일 4-Tuple의 신규 세션 데이터로 오인 혼입(Data Corruption)되는 것을 방지합니다.

### 고갈 메커니즘:
초당 500개의 요청을 처리하는 API 게이트웨이가 매번 연결을 닫으면, 60초 동안 $500 	imes 60 = 30,000$개의 소켓이 `TIME_WAIT`에 누적됩니다. 가용 포트(28,232개)를 초과하는 순간 `connect()`는 커널 에러 **`-EADDRNOTAVAIL` (Cannot assign requested address)**를 반환합니다.

---

## 3. 해결책 분석: tcp_tw_recycle의 퇴출과 tcp_tw_reuse의 승리

### (1) `tcp_tw_recycle` (Linux 4.12에서 영구 제거됨)
과거에는 `tcp_tw_recycle=1`을 켜서 TIME_WAIT 시간을 1초 미만으로 단축시켰으나, 이는 호스트별 타임스탬프를 캐싱하므로 NAT 게이트웨이 뒤에 있는 여러 클라이언트의 SYN을 드롭시키는 대참사를 유발하여 리눅스 커널에서 완전히 삭제되었습니다.

### (2) `tcp_tw_reuse = 1` (안전하고 검증된 아웃바운드 솔루션)
`tcp_tw_reuse`는 오직 **아웃바운드 `connect()` 연결 요청에 대해서만 동작**합니다:
- 새 SYN 패킷의 TCP 타임스탬프가 이전 `TIME_WAIT` 연결에서 기록된 마지막 타임스탬프보다 엄격히 클 경우(RFC 1323 PAWS 원칙), 커널은 해당 `TIME_WAIT` 소켓을 0초 만에 즉시 가로채서 새 연결에 재사용합니다.
- **치명적 전제조건**: `tcp_tw_reuse`는 반드시 **`net.ipv4.tcp_timestamps = 1`**이 함께 켜져 있어야만 작동합니다. 타임스탬프가 꺼져 있으면 `tw_reuse`는 조용히 무시되며 `-EADDRNOTAVAIL`이 계속 발생합니다.

---

## 4. `tcp_max_tw_buckets` 오버플로우 방어

시스템 전역의 `TIME_WAIT` 소켓 수가 `net.ipv4.tcp_max_tw_buckets`를 초과하면:
- 커널은 시스템 메모리 보호를 위해 가장 오래된 소켓을 즉시 강제 폐기하고 상대방에게 **TCP RST**를 날립니다.
- 정상 트래픽이 끊기는 것을 방지하려면 서버 메모리 용량에 맞게 버킷 한도를 65,536 ~ 262,144 이상으로 넉넉히 증설해야 합니다.

---

## 5. 엔터프라이즈 프로덕션 아키텍처 및 튜닝 레시피

### (1) HTTP Keep-Alive 커넥션 풀링 적용 (가장 근본적인 해결책)
```yaml
# Envoy / Nginx upstream keepalive 설정
upstream backend {
    server 10.0.0.50:8080;
    keepalive 256;          # 유휴 커넥션 256개 유지
    keepalive_timeout 60s;
}
```
커넥션을 매번 맺고 끊지 않고 재사용하면 아웃바운드 커넥션 생성률이 99% 이상 급감하여 포트 고갈 자체가 발생하지 않습니다.

### (2) 이그레스 IP 멀티 바인딩 (Multi-IP Egress Scaling)
단일 IP당 28,232개의 튜플 한계를 극복하기 위해, 프록시가 4개의 로컬 IP(`10.0.1.1 ~ 10.0.1.4`)를 라운드로빈으로 바인딩하면 $4 	imes 28,232 = 112,928$개의 튜플을 확보할 수 있습니다.

### (3) 커널 sysctl 최적화
```bash
# 1. Ephemeral 포트 범위 확장 (최대 64,512개)
sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# 2. tcp_tw_reuse 및 타임스탬프 활성화
sysctl -w net.ipv4.tcp_timestamps=1
sysctl -w net.ipv4.tcp_tw_reuse=1

# 3. TIME_WAIT 버킷 상한 증설
sysctl -w net.ipv4.tcp_max_tw_buckets=262144
```
