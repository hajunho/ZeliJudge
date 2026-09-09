# 다계층 DNS 캐싱과 네거티브 캐시의 저주 (Multi-Tier DNS Cache Invalidation & RFC 2308)

## 문제 설명

클라우드 환경에서 서비스를 운영하는 엔지니어들이 겪는 가장 당혹스러운 장애 중 하나는 **"DNS 레코드에서 서버 IP를 분명히 새 서버로 바꿨는데, 며칠 동안 구 서버로 트래픽이 계속 유입되어 결제 오류가 터지는 현상"**입니다.

이 문제는 도메인 이름을 IP 주소로 변환하는 과정이 단순한 1:1 조회가 아니라, **4단계의 다계층 캐시(Multi-Tier Cache)**를 통과하기 때문에 발생합니다:

1. **애플리케이션 계층 (App Cache)**:
   - Java Virtual Machine(JVM) 등 일부 애플리케이션 런타임은 과거 기본 설정으로 `networkaddress.cache.ttl = -1` (영구 캐싱) 정책을 가집니다.
   - 이 경우 권한 네임서버에서 IP가 바뀌고 아무리 오랜 시간이 흘러도 **프로세스를 재시작(`FLUSH_CACHE target=APP`)하기 전까지 죽은 구 서버 IP를 영구히 캐싱**하는 좀비 트래픽 참사가 발생합니다.
2. **운영체제 계층 (OS Cache)**:
   - Windows의 `dnscache` 서비스나 Linux의 `systemd-resolved` 등 OS 수준의 DNS 캐시입니다.
   - 상위 리졸버가 응답한 잔여 TTL만큼 캐시를 보관합니다.
3. **ISP / 공용 재귀 리졸버 계층 (ISP Resolver)**:
   - 통신사나 공용 DNS(8.8.8.8 등)가 운영하는 재귀 리졸버입니다.
   - 일부 ISP는 잦은 DNS 질의 트래픽을 아끼기 위해 권한 서버가 지정한 짧은 TTL(예: 10초)을 무시하고 **최소 TTL을 강제 상향(`min_ttl_clamp`, 예: 300초)**하여 캐싱해 버리는 관행이 있습니다.
4. **권한 네임서버 (Authoritative DNS)**:
   - 해당 도메인의 절대적 진실(Ground Truth)을 보유한 최상위 서버입니다.

또한, **RFC 2308 네거티브 캐싱(Negative Caching)** 규격에 따라, 아직 등록되지 않은 도메인을 조회했을 때 반환되는 `NXDOMAIN` (도메인 없음) 실패 응답 역시 SOA의 `negative_ttl`만큼 전 계층에 캐싱됩니다. 이 때문에 DNS 레코드를 등록하기 직전에 성급하게 호출했다가, 등록 완료 후에도 한동안 `NXDOMAIN` 에러가 지속되는 저주가 발생합니다.

당신은 이 다계층 DNS 해석 파이프라인과 캐시 만료/플러시 메커니즘을 완벽하게 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 시뮬레이션 규칙

### 1. 4단계 해석 계층 구조 (Resolution Hierarchy)
클라이언트가 도메인 해석(`RESOLVE <domain>`)을 요청하면 다음 순서로 탐색합니다:
1. **App Cache 탐색**:
   - 캐시 히트 시: 해당 값 반환 (`source=APP_CACHE ttl=<remaining_ttl>`)
2. **OS Cache 탐색**:
   - 캐시 히트 시: 해당 값으로 App Cache를 갱신하고 반환 (`source=OS_CACHE ttl=<os_remaining_ttl>`)
3. **ISP Cache 탐색**:
   - 캐시 히트 시: 해당 값으로 OS Cache와 App Cache를 갱신하고 반환 (`source=ISP_CACHE ttl=<isp_remaining_ttl>`)
4. **Authoritative DNS 질의**:
   - 권한 서버에 도메인이 존재하는 경우:
     - 레코드의 원본 `ttl`과 ISP의 `min_ttl_clamp` 중 큰 값으로 ISP Cache를 등록합니다: `isp_ttl = max(ttl, min_ttl_clamp)`
     - OS Cache는 `isp_ttl`로 등록됩니다.
     - App Cache는 `min(app_ttl, isp_ttl)` (단, `app_ttl == -1`이면 -1)로 등록됩니다. (만약 `app_ttl == 0`이면 App Cache에 저장하지 않음)
     - 결과 반환: `source=AUTHORITATIVE ttl=<ttl>`
   - 권한 서버에 도메인이 존재하지 않는 경우 (`NXDOMAIN`):
     - SOA의 `negative_ttl` (기본값 30초)로 ISP 및 OS Cache에 `NXDOMAIN`을 등록합니다.
     - App Cache는 `min(app_negative_ttl, negative_ttl)` (단, `app_negative_ttl == -1`이면 -1, 0이면 미저장)로 등록합니다.
     - 결과 반환: `source=AUTHORITATIVE_NXDOMAIN ttl=<negative_ttl>`

### 2. 시간 경과 (`TICK <seconds>`)
- App Cache, OS Cache, ISP Cache의 모든 엔트리에 대해:
  - `remaining_ttl == -1`인 엔트리는 시간을 차감하지 않습니다 (영구 보존).
  - 그 외의 엔트리는 `remaining_ttl -= seconds`를 수행합니다.
  - 차감 후 `remaining_ttl <= 0`이 된 엔트리는 캐시에서 즉시 소멸(Evict)됩니다.

### 3. 캐시 초기화 (`FLUSH_CACHE target=<APP|OS|ISP|ALL>`)
- 지정된 계층의 모든 캐시 엔트리를 즉시 비웁니다.

---

## 명령어 명세

모든 명령어는 표준 입력(stdin)으로 한 줄씩 주어지며, 빈 줄이나 `#` 주석은 무시합니다. 인자는 `key=value` 형태 또는 공백 구분 위치 인자를 지원합니다.

1. **`SET_AUTH_RECORD domain=<str> type=<str> value=<str> ttl=<int>`**
   - 권한 네임서버에 레코드를 등록하거나 갱신합니다.
   - 출력: `SET_AUTH_RECORD_OK domain=<domain> value=<value> ttl=<ttl>`

2. **`DEL_AUTH_RECORD domain=<str>`**
   - 권한 네임서버에서 레코드를 삭제합니다.
   - 출력: `DEL_AUTH_RECORD_OK domain=<domain>`

3. **`SET_AUTH_SOA domain=<str> negative_ttl=<int>`**
   - 도메인의 SOA 네거티브 캐시 TTL을 설정합니다. (기본값: 30)
   - 출력: `SET_AUTH_SOA_OK domain=<domain> negative_ttl=<negative_ttl>`

4. **`CONFIG_ISP min_ttl_clamp=<int>`**
   - ISP의 최소 TTL 강제 값을 설정합니다. (기본값: 0)
   - 출력: `CONFIG_ISP_OK min_ttl_clamp=<min_ttl_clamp>`

5. **`CONFIG_APP ttl=<int> negative_ttl=<int>`**
   - 애플리케이션의 캐시 TTL 정책을 설정합니다. (`-1`: 영구 캐싱, `0`: 비활성화, `>0`: 초 단위) (기본값: `ttl=30, negative_ttl=10`)
   - 출력: `CONFIG_APP_OK ttl=<ttl> negative_ttl=<negative_ttl>`

6. **`TICK <seconds>`**
   - 시뮬레이션 시간을 `<seconds>`초만큼 전진시킵니다.
   - 출력: `TICK_OK elapsed=<seconds>`

7. **`FLUSH_CACHE target=<APP|OS|ISP|ALL>`**
   - 대상 캐시 계층을 즉시 비웁니다.
   - 출력: `FLUSH_OK target=<target>`

8. **`RESOLVE <domain>`**
   - 도메인 해석을 수행합니다.
   - 출력 형식:
     `RESOLVED <domain> <VALUE|NXDOMAIN> source=<APP_CACHE|OS_CACHE|ISP_CACHE|AUTHORITATIVE|AUTHORITATIVE_NXDOMAIN> ttl=<ttl>`

9. **`STATUS <domain>`**
   - 각 계층의 캐시 상태를 덤프합니다.
   - 출력 형식:
     ```
     --- DNS_STATUS <domain> ---
     APP: <VALUE (ttl=N)|NXDOMAIN (ttl=N)|MISS>
     OS: <VALUE (ttl=N)|NXDOMAIN (ttl=N)|MISS>
     ISP: <VALUE (ttl=N)|NXDOMAIN (ttl=N)|MISS>
     AUTH: <VALUE (ttl=N)|NXDOMAIN>
     --- END_STATUS ---
     ```

10. **`RESET`**
    - 모든 설정과 캐시를 초기 상태로 리셋합니다.
    - 출력: `RESET_OK`

---

## 입출력 예시

### 예시 입력
```
SET_AUTH_RECORD domain=api.zeli.com type=A value=10.0.0.1 ttl=60
RESOLVE api.zeli.com
RESOLVE api.zeli.com
STATUS api.zeli.com
```

### 예시 출력
```
SET_AUTH_RECORD_OK domain=api.zeli.com value=10.0.0.1 ttl=60
RESOLVED api.zeli.com 10.0.0.1 source=AUTHORITATIVE ttl=60
RESOLVED api.zeli.com 10.0.0.1 source=APP_CACHE ttl=30
--- DNS_STATUS api.zeli.com ---
APP: 10.0.0.1 (ttl=30)
OS: 10.0.0.1 (ttl=60)
ISP: 10.0.0.1 (ttl=60)
AUTH: 10.0.0.1 (ttl=60)
--- END_STATUS ---
```
