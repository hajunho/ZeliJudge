# 리눅스 커널 NUMA: 원격 노드 접근 지연과 zone_reclaim_mode 스톨 및 numactl 메모리 정책

## 1. 개요: UMA에서 NUMA로의 컴퓨터 구조 혁신과 과제

과거 단일 버스(Front Side Bus, FSB) 기반의 대칭형 다중 처리(SMP / UMA, Uniform Memory Access) 구조에서는 모든 CPU 코어가 단일 메모리 컨트롤러를 공유하여 메모리에 접근했습니다. 그러나 코어 수가 32개, 64개, 128개로 급증하면서 FSB 대역폭이 극단적인 병목 지점이 되었습니다.

이를 극복하기 위해 현대 멀티소켓 서버(Intel Xeon Scalable, AMD EPYC)는 **NUMA(Non-Uniform Memory Access, 비균일 메모리 접근)** 아키텍처를 전면 채택했습니다:

```
┌──────────────────────────────────────┐             ┌──────────────────────────────────────┐
│        NUMA Node 0 (소켓 0)          │             │        NUMA Node 1 (소켓 1)          │
│  ┌────────────────────────────────┐  │             │  ┌────────────────────────────────┐  │
│  │   CPU Cores (Core 0 ~ 31)      │  │             │  │   CPU Cores (Core 32 ~ 63)     │  │
│  └───────────────┬────────────────┘  │             │  └───────────────┬────────────────┘  │
│                  │                   │             │                  │                   │
│         ┌────────┴────────┐          │  Intel UPI  │         ┌────────┴────────┐          │
│         │ Local Memory    │◄─────────┼─────────────┼────────►│ Local Memory    │          │
│         │ Controller(IMC) │  AMD IF  │ Interconnect│         │ Controller(IMC) │          │
│         └────────┬────────┘ (20~30ns)│             │         └────────┬────────┘          │
└──────────────────┼───────────────────┘             └──────────────────┼───────────────────┘
                   ▼                                                    ▼
         ┌──────────────────┐                                 ┌──────────────────┐
         │ Local DRAM (64GB)│                                 │ Local DRAM (64GB)│
         │ (Latency: 60ns)  │                                 │ (Latency: 60ns)  │
         └──────────────────┘                                 └──────────────────┘
```

각 CPU 소켓은 자체 통합 메모리 컨트롤러(IMC)와 직결된 로컬 DRAM 채널을 가지며, 다른 소켓의 메모리에 접근할 때는 고속 점대점 인터커넥트(**Intel UPI / Ultra Path Interconnect, AMD Infinity Fabric**)를 건너뜁니다.

이로 인해 메모리 접근 위치에 따른 물리적 지연시간 차이가 발생합니다:
- **로컬 메모리 접근 (Local Access)**: 약 $50 \sim 80\,\text{ns}$ (직접 버스 통신)
- **원격 메모리 접근 (Remote Access)**: 약 $120 \sim 180\,\text{ns}$ (인터커넥트 횡단 페널티 $1.5\times \sim 2.5\times$, 링크 대역폭 제약)

---

## 2. ACPI SLIT과 NUMA 거리 행렬 (NUMA Distance Matrix)

리눅스 커널은 부팅 시 BIOS/UEFI의 **ACPI SLIT(System Locality Information Table)**을 파싱하여 노드 간의 상대적 접근 비용을 정규화된 거리(Distance) 행렬로 구성합니다 (`numactl --hardware`로 확인 가능):

$$\text{Distance}(Node_i, Node_j) = 
\begin{cases}
10 & (i = j, \text{로컬 노드}) \\
20 \sim 32 & (i \neq j, \text{원격 소켓 간 1홉 횡단})
\end{cases}$$

원격 노드 메모리를 읽을 때의 실제 물리 지연시간은 기본 로컬 지연시간에 거리 비율을 곱한 값에 수렴합니다:

$$\text{Latency}_{\text{access}} = \text{Latency}_{\text{local}} \times \left( \frac{\text{Distance}}{10} \right)$$

---

## 3. `vm.zone_reclaim_mode`: 고성능 데이터베이스의 사형 선고

### 3.1 탄생 배경과 목적
리눅스 커널 소스코드 `mm/vmscan.c`의 `zone_reclaim()` 함수는 원래 HPC(고성능 과학 연산) 및 배치 연산 환경을 위해 설계되었습니다.
HPC 노드에서는 원격 메모리를 참조하는 지연시간($140\,\text{ns}$)을 극도로 꺼리므로, 로컬 노드의 여유 메모리가 바닥났을 때 원격 노드로 넘어가기보다는 **로컬 노드의 파일 캐시(Page Cache)를 비워내고 항상 로컬 메모리를 사수하는 것**이 유리하다고 판단했습니다.

### 3.2 비트마스크 파라미터 구성 (`/proc/sys/vm/zone_reclaim_mode`)
- `0`: 비활성화 (기본값 권장). 로컬 노드 고갈 시 원격 노드 메모리를 즉시 할당.
- `1`: 로컬 존 회수 활성화 (Clean Page Cache를 언맵하고 재활용).
- `2`: 더티 페이지 플러시 허용 (`ZONE_RECLAIM_WRITE`, 디스크 I/O 동반).
- `4`: 슬랩 캐시 스캔 및 스왑 허용 (`ZONE_RECLAIM_SWAP`).

### 3.3 대형 데이터베이스(MySQL, Redis, PostgreSQL)에서의 참사
데이터베이스나 캐시 엔진은 대량의 테이블 스페이스, 로그 파일, 페이지 캐시를 메모리에 유지합니다:

```
[로컬 Node 0이 low 워터마크에 도달한 상황]
1. zone_reclaim_mode = 1일 경우:
   - 커널은 Node 1에 60GB의 텅 빈 여유 메모리가 있음을 완전히 무시함.
   - 메모리를 할당하려던 애플리케이션 스레드가 커널 직접 회수(Direct Reclaim) 루프에 강제 진입.
   - 수십 GB의 페이지 캐시를 스캔하고 무효화(Invalidate)하며, 더티 페이지를 디스크로 동기식 플러시!
   - 사용자 스레드가 커널 공간에서 100% sys CPU를 태우며 100ms ~ 수 초간 완전히 정지(Stop-the-World).
2. 결과:
   - MySQL InnoDB 쿼리 지연시간 수십 초 폭증.
   - Redis 이벤트 루프 블로킹으로 클라이언트 커넥션 전부 타임아웃.
   - 쿠버네티스/클라우드 오케스트레이터의 liveness probe 실패로 컨테이너 재시작 루프.
```

따라서 Red Hat, Oracle, AWS, MySQL 공식 문서에서는 데이터베이스 서버 튜닝 1순위로 반드시 다음을 요구합니다:

```bash
sysctl -w vm.zone_reclaim_mode=0
echo "vm.zone_reclaim_mode = 0" >> /etc/sysctl.conf
```

---

## 4. NUMA 메모리 할당 정책 (`numactl`과 `set_mempolicy(2)`)

리눅스는 프로세스나 스레드 단위로 다양한 NUMA 메모리 정책을 제공합니다:

| 정책 (`mode`) | 동작 원리 | 장점 | 단점 / 위험성 | 추천 사용 사례 |
| :--- | :--- | :--- | :--- | :--- |
| `MPOL_DEFAULT` | 현재 스레드가 실행 중인 CPU의 로컬 노드에 우선 할당 | 로컬 접근 지연 최소화 ($60\,\text{ns}$) | 스레드가 한쪽 소켓에 몰리면 심각한 NUMA 불균형 발생 | 단일 소켓 크기 이하의 소규모 프로세스 |
| `MPOL_INTERLEAVE` | 지정된 노드들에 1페이지(4KB)씩 라운드로빈 순환 할당 | 메모리 균등 분산, 메모리 대역폭 2배 집계, 존 고갈 방지 | 평균 지연시간이 로컬과 원격의 중간 ($100\,\text{ns}$) | **대용량 Redis, MySQL 버퍼 풀, In-Memory DB** |
| `MPOL_BIND` | 지정된 특정 노드 세트에서만 엄격히 할당 | 특정 노드 완전 격리 및 캐시 간섭 차단 | 지정 노드 소진 시 타 노드 여유가 있어도 **OOM Kill** 발생 | 특수 실시간 처리, 전용 격리 워커 |
| `MPOL_PREFERRED` | 우선 노드에 먼저 시도하되, 부족하면 원격 노드로 자연스럽게 폴백 | 로컬 우선권 유지 + OOM/스톨 방지 | 스필오버 발생 시 원격 접근 비율 증가 | 일반적인 멀티스레드 애플리케이션 |

### `numactl` 실무 명령어 패턴
```bash
# 1. 단일 대형 인메모리 DB를 전체 소켓에 인터리빙 실행 (권장)
numactl --interleave=all /usr/bin/redis-server /etc/redis.conf

# 2. 멀티 인스턴스 격리: 인스턴스 1은 소켓 0, 인스턴스 2는 소켓 1에 완전 바인딩
numactl --cpunodebind=0 --membind=0 /usr/bin/redis-server /etc/redis-6379.conf
numactl --cpunodebind=1 --membind=1 /usr/bin/redis-server /etc/redis-6380.conf
```

---

## 5. AutoNUMA와 동적 페이지 마이그레이션

리눅스 커널 3.8부터 도입된 **AutoNUMA (`kernel.numa_balancing = 1`)**는 수동 튜닝 없이도 메모리 참조 지역성을 자동으로 최적화하는 기법입니다:

1. **NUMA 힌팅 폴트 (Hinting Page Fault)**:
   - 커널 배경 태스크(`task_numa_work`)가 프로세스의 가상 메모리 페이지 테이블 엔트리(PTE)의 접근 권한을 주기적으로 `PROT_NONE`으로 전환합니다.
2. **페이지 폴트 트랩 및 통계 수집**:
   - 스레드가 해당 페이지를 읽거나 쓸 때 경량 페이지 폴트(Minor Fault)가 발생합니다.
   - 커널은 폴트를 일으킨 CPU의 소켓 ID와 페이지의 실제 물리 NUMA 노드 ID를 대조합니다.
3. **페이지 마이그레이션 (`migrate_misplaced_page`)**:
   - 스레드가 Node 0에서 실행 중인데 해당 페이지가 Node 1에 상주하며 반복적으로 접근되고 있다면, 커널은 해당 4KB 페이지를 물리적으로 Node 0으로 복사하고 페이지 테이블을 갱신합니다.
   - 마이그레이션 비용(약 $10\,\mu\text{s}$ per page)이 소요되지만, 이후의 수백만 번의 메모리 접근이 $140\,\text{ns}$ 원격 접근에서 $60\,\text{ns}$ 로컬 접근으로 전환되어 장기적인 시스템 처리량이 대폭 향상됩니다.
