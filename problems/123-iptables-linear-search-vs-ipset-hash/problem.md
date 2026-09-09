# 123. 악성 IP 1만 개 차단했더니 왜 서버 패킷 처리가 100배 느려지고 CPU가 100% 찍어요?!: 리눅스 iptables 선형 탐색($O(N)$) vs ipset 해시 테이블($O(1)$) 패킷 필터링

## 문제 설명

디도스(DDoS) 공격이나 악성 크롤러를 방어하기 위해, 보안 감시 스크립트가 의심스러운 IP를 발견할 때마다 리눅스 표준 방화벽인 `iptables`에 차단 룰을 자동으로 추가하도록 설정했습니다:
```bash
iptables -A INPUT -s 198.51.100.1 -j DROP
iptables -A INPUT -s 198.51.100.2 -j DROP
... (수천~수만 개 누적)
```

차단 룰이 10,000개가 넘어가자, 악성 IP는 막아냈지만 **더 끔찍한 대참사**가 발생했습니다! 😱  
정상적인 일반 사용자들의 API 응답 시간이 100배 이상 느려지고, 리눅스 커널의 소프트인터럽트 처리 데몬(`ksoftirqd`)이 서버의 모든 CPU 코어를 100% 독점하며 합법적인 정상 네트워크 패킷까지 줄줄이 드롭(Drop)되기 시작한 것입니다.

---

### 왜 이런 일이 발생할까? (iptables 연결 리스트 $O(N)$ 선형 탐색의 저주)

리눅스 커널의 기본 패킷 필터링 도구인 `iptables`는 내부적으로 룰들을 **단순 연결 리스트(Linked List)** 구조로 체인에 저장합니다:

```
[iptables의 O(N) 선형 탐색 체인]
패킷 유입 ──► [Rule 1: Drop 1.1.1.1?] (불일치)
               └──► [Rule 2: Drop 1.1.1.2?] (불일치)
                     └──► ...
                           └──► [Rule 10000: Drop 1.2.3.4?] (불일치)
                                 └──► [Default: ACCEPT] (10,000번 비교 후 통과!)
```

정상적인 사용자 패킷은 블랙리스트에 없기 때문에, 체인에 걸린 **모든 룰(10,000개)을 1번부터 10,000번까지 전부 순차적으로 비교($O(N)$)**하고 나서야 최종 통과(`ACCEPT`) 판정을 받습니다!
- 차단 룰이 10,000개일 때 패킷이 초당 1만 개 들어오면, 초당 **$1만 	imes 1만 = 1억 번**의 룰 매칭 연산이 커널 네트워크 계층에서 발생합니다!
- 이로 인해 CPU가 즉사하고 패킷 지연시간(Latency)이 폭증합니다.

> **쿠버네티스(K8s)의 역사적 교훈**:  
> 쿠버네티스 초기에는 모든 Service 및 Pod 라우팅을 `iptables` 체인으로 구성했습니다.  
> 하지만 대규모 클러스터에서 서비스가 수천 개를 넘어서자 iptables 룰이 수만 개로 폭증하여 네트워크 성능이 급락하는 한계(iptables Scale Limit)에 부딪혔고, 결국 K8s 팀은 이를 해결하기 위해 해시 기반의 **IPVS (IP Virtual Server)** 모드를 표준으로 도입했습니다.

---

### 구원 투수: `ipset` (커널 인메모리 해시 테이블 $O(1)$)

`ipset`은 리눅스 커널 내부에서 수만~수백만 개의 IP/CIDR 주소를 **해시 테이블(Hash Table) 및 이진 탐색 트리(rbtree)**로 관리하는 초고속 네트워크 도구입니다:

- iptables에는 단 **1개의 룰**만 등록합니다:
  ```bash
  iptables -A INPUT -m set --match-set blacklist src -j DROP
  ```
- 차단 대상 IP가 1개이든 100만 개이든, 패킷이 들어오면 커널 메모리에서 **단 1번의 해시 룩업($O(1)$)**만으로 차단 여부를 즉시 판정합니다!
- CPU 사용률 0%, 패킷 지연시간 0ms로 대규모 DDoS IP를 우아하게 방어할 수 있습니다.

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG mode=<IPTABLES|IPSET>`
   - 패킷 필터 모드를 설정합니다 (`IPTABLES` 또는 `IPSET`).
   - 출력: `OK mode=<mode>`

2. `ADD_RULE target=<ACCEPT|DROP> src_ip=<ip>`
   - `IPTABLES`: 체인의 맨 끝에 순차 룰 1개 추가.  
     출력: `RULE_ADDED mode=IPTABLES rule_index=<idx> target=<target> src=<src_ip>`
   - `IPSET`: 해시 셋에 IP 추가.  
     출력: `IPSET_ENTRY_ADDED mode=IPSET set_size=<size> target=<target> src=<src_ip>`

3. `PACKET src_ip=<ip>`
   - 패킷 1개에 대해 필터링을 수행합니다.
   - `evaluations`: 판정에 소요된 룰 비교 횟수 (iptables: $O(N)$, ipset: $O(1)$)
   - 출력: `PACKET_RESULT src=<ip> action=<ACCEPTED|DROPPED> evaluations=<evals> latency_us=<evals>`

4. `BENCHMARK src_ips=<json_list>`
   - 주어진 IP 리스트의 패킷들을 일괄 처리하고 종합 통계를 산출합니다:  
     `BENCHMARK_RESULT mode=<mode> packets=<P> accepted=<A> dropped=<D> total_evaluations=<total> avg_evaluations=<avg:.1f>`

5. `STATS`
   - 현재 누적 통계를 출력합니다:  
     `STATS mode=<mode> rules_or_entries=<count> total_packets=<P> total_evaluations=<E> avg_evaluations=<avg:.1f>`

6. `RESET`
   - 모든 룰 및 통계를 초기화합니다: `OK mode=IPTABLES rules=0 ipset_size=0`

---

## 예제 입력 1 (iptables 선형 탐색 vs ipset O(1) 해시 룩업)

```text
CONFIG mode=IPTABLES
ADD_RULE target=DROP src_ip=192.168.1.100
ADD_RULE target=DROP src_ip=192.168.1.101
ADD_RULE target=DROP src_ip=192.168.1.102
PACKET src_ip=192.168.1.100
PACKET src_ip=192.168.1.102
PACKET src_ip=10.0.0.1
STATS
```

## 예제 출력 1

```text
OK mode=IPTABLES
RULE_ADDED mode=IPTABLES rule_index=0 target=DROP src=192.168.1.100
RULE_ADDED mode=IPTABLES rule_index=1 target=DROP src=192.168.1.101
RULE_ADDED mode=IPTABLES rule_index=2 target=DROP src=192.168.1.102
PACKET_RESULT src=192.168.1.100 action=DROPPED evaluations=1 latency_us=1
PACKET_RESULT src=192.168.1.102 action=DROPPED evaluations=3 latency_us=3
PACKET_RESULT src=10.0.0.1 action=ACCEPTED evaluations=3 latency_us=3
STATS mode=IPTABLES rules=3 total_packets=3 total_evaluations=7 avg_evaluations=2.3
```

> **설명**:  
> 정상 사용자(`10.0.0.1`)는 체인에 등록된 3개의 룰을 모두 검사한 뒤에야(`evaluations=3`) 최종 통과(`ACCEPTED`)되었습니다.  
> 룰이 1만 개라면 매 패킷마다 1만 번의 룰 검사를 수행해야 합니다!\n