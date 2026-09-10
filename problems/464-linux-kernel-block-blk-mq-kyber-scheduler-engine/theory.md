# 리눅스 커널 블록 다중 큐(blk-mq) 및 Kyber I/O 스케줄러 심층 분석

## 1. 전통적 블록 계층(Single-Queue)의 한계와 blk-mq의 탄생

전통적인 리눅스 블록 계층(`block/blk-core.c`)은 회전식 미디어(HDD)의 기계적 헤드 이동 시간(Seek time)을 최소화하기 위해 고안되었습니다. 요청 엘리베이터(Elevator) 알고리즘(NOOP, Deadline, CFQ)은 디바이스당 존재하는 단일 `struct request_queue`에 순차적으로 정렬하여 삽입했습니다. 이 큐는 전역 `queue_lock` 스핀락으로 보호되었습니다.

하지만 SATA SSD와 고성능 PCIe NVMe SSD의 등장으로 I/O 장치의 근본적 특성이 완전히 바뀌었습니다:
1. **IOPS의 폭발적 증가**: 초당 수백 회(HDD)에서 수백만 회(NVMe)로 10,000배 이상 급증.
2. **초저지연**: 밀리초(ms) 단위에서 수 마이크로초(\(\mu s\)) 단위로 단축.
3. **하드웨어 병렬성**: 디바이스 컨트롤러 내부에 독립된 수백~수천 개의 Submission Queue(SQ) 및 Completion Queue(CQ) 내장.

멀티코어 시스템에서 수많은 CPU 코어가 단일 `queue_lock`을 획득하기 위해 스핀락 경합을 벌이면서 CPU 사용률이 100%에 달해도 실제 I/O 처리량은 오히려 급감하는 역설적 병목이 발생했습니다. 또한, 서로 다른 CPU 간의 `request_queue` 구조체 캐시 라인 핑퐁(Cache Line Bouncing) 현상으로 인해 메모리 버스 트래픽이 마비되었습니다.

---

## 2. blk-mq의 2단계 큐잉(Two-Level Queueing) 아키텍처

리눅스 커널 3.13부터 도입된 `blk-mq`는 큐잉 레이어를 2단계로 명확히 분리하여 락 경합을 원천 제거했습니다:

### 2.1 Level 1: 소프트웨어 스테이징 큐 (`struct blk_mq_ctx`)
- 시스템의 모든 논리적 CPU 코어마다 1개의 `blk_mq_ctx`가 할당됩니다.
- 사용자 스레드가 `read()`, `write()`, `io_uring` 시스템 콜을 통해 BIO를 제출하면, 현재 스레드가 실행 중인 CPU의 로컬 `blk_mq_ctx`에 무경합(Per-CPU Lock 또는 Lockless)으로 적재됩니다.
- CPU 간 캐시 라인 공유가 전혀 발생하지 않으므로 완벽한 선형 확장성(Linear Scalability)을 제공합니다.

### 2.2 Level 2: 하드웨어 디스패치 큐 (`struct blk_mq_hw_ctx`, hctx)
- 블록 디바이스의 물리적 컨트롤러가 지원하는 하드웨어 큐 개수에 맞춰 생성됩니다.
- CPU 수보다 하드웨어 큐 수가 적은 경우, 커널은 CPU 토폴로지(NUMA 노드, 코어 거리)를 고려하여 여러 CPU의 `blk_mq_ctx`를 최적의 `hctx`로 매핑(`tag_set->map`)합니다.
- `hctx`는 하드웨어 명령 태그 할당기(`sbitmap_queue`)를 내장하여 디바이스 실행 슬롯을 고속으로 배정합니다.

---

## 3. 확장 가능 비트맵 (`sbitmap`) 기반 태그 할당

고성능 NVMe 디바이스는 비동기 완료를 식별하기 위해 고유한 명령 태그(Command Tag, \(0 \le \text{tag} < \text{queue\_depth}\))를 요구합니다. 수백만 IOPS 환경에서 전통적인 원자적 비트맵(`atomic_bitops`)을 사용할 경우 단일 메모리 워드에 대한 CAS(Compare-And-Swap) 경합이 심화됩니다.

blk-mq는 이를 극복하기 위해 `sbitmap`(`lib/sbitmap.c`)을 개발했습니다:
- 전체 태그 공간을 여러 개의 독립된 워드(`struct sbitmap_word`)로 분할합니다.
- 각 CPU 코어는 라운드로빈 또는 해시 기반 힌트(`alloc_hint`)를 통해 서로 다른 워드에서 비트를 탐색하므로, 코어 간 동시 태그 할당 경합을 획기적으로 줄입니다.
- 태그가 고갈된 경우, `struct sbitmap_queue`의 대기 큐(`wait_queue_head_t`)에 프로세스를 효율적으로 슬립시키고 하드웨어 인터럽트 완료 시 배치로 깨웁니다.

---

## 4. I/O 스케줄러 비교: `none` vs `kyber` vs `bfq`

| 비교 항목 | `none` (Passthrough) | `kyber` | `bfq` (Budget Fair Queueing) |
|---|---|---|---|
| **설계 목표** | 극단적 오버헤드 최소화 | 초저지연 읽기 보장 & 쓰기 제어 | 프로세스별 정밀한 대역폭/가중치 공정성 |
| **적합한 미디어** | 최고 성능 NVMe SSD | 고성능 NVMe SSD | 회전식 HDD, eMMC, 저속 SATA SSD |
| **CPU 오버헤드** | 거의 제로 (Passthrough) | 극히 낮음 (간단한 토큰 카운터) | 높음 (B-Tree 연산, 정밀 가중치 계산) |
| **도메인 분리** | 없음 (단일 FIFO) | `KYBER_READ`, `KYBER_WRITE`, `KYBER_DISCARD` | cgroup 및 프로세스별 클래스 분리 |
| **쓰기 폭주 방어** | **불가 (헤드오브라인 블로킹 발생)** | **우수 (동적 토큰 반감 및 읽기 우선)** | 보통 (대역폭 예산 분배) |

### 4.1 `none`의 치명적 약점: 헤드오브라인 블로킹(Head-of-Line Blocking)
대규모 쓰기 부하(예: 데이터베이스 체크포인트, 대용량 로그 플러시)가 발생하면, `none` 스케줄러는 하드웨어 큐의 모든 태그(`queue_depth`)를 쓰기 요청으로 채워버립니다.
이때 사용자 웹 요청 처리를 위한 단 4KB 크기의 동기식 읽기 요청이 들어오면, 앞서 들어간 모든 쓰기 작업이 완료될 때까지 하드웨어 큐에 진입하지 못하고 소프트웨어 큐에서 수 밀리초 동안 대기하게 되어 애플리케이션의 P99 응답 지연 시간이 급등합니다.

### 4.2 Kyber의 해결책: 읽기 우선순위와 적응형 쓰기 토큰
Kyber는 읽기 요청을 최우선으로 디스패치하며, 쓰기 요청은 사전에 제한된 `write_tokens` 범위 내에서만 하드웨어 큐 진입을 허용합니다.
남겨진 하드웨어 슬롯은 갑작스럽게 도착하는 읽기 요청을 위해 항상 비워져 있으므로, 읽기 요청의 큐 대기 시간(\(L_{\text{queue}}\))은 0에 수렴하게 됩니다.
더 나아가, NVMe 디바이스 내부 컨트롤러 채널의 포화로 인해 읽기 레이턴시가 목표치(\(\tau_{\text{read}}\))를 넘어서면, 즉시 `write_tokens`를 절반으로 줄여 디바이스 하드웨어 자체의 혼잡을 해소합니다.

---

## 5. 실무 프로덕션 튜닝 및 관찰 가이드

리눅스 프로덕션 환경에서 블록 스케줄러를 확인하고 튜닝하는 대표적인 sysfs 인터페이스:

```bash
# 1. 현재 블록 디바이스의 스케줄러 확인 및 변경
cat /sys/block/nvme0n1/queue/scheduler
# [none] mq-deadline kyber bfq
echo kyber > /sys/block/nvme0n1/queue/scheduler

# 2. Kyber 지연시간 목표치 설정 (단위: 마이크로초 us)
# 읽기 지연 목표: 2ms (2000us)
echo 2000 > /sys/block/nvme0n1/queue/kyber_lat_usecs/read
# 쓰기 지연 목표: 10ms (10000us)
echo 10000 > /sys/block/nvme0n1/queue/kyber_lat_usecs/write

# 3. 하드웨어 큐 깊이 및 요청 수 확인
cat /sys/block/nvme0n1/queue/nr_requests
```

Kyber는 클라우드 네이티브 환경, 대규모 분산 데이터베이스(RocksDB, TiKV, PostgreSQL) 및 마이크로서비스 환경에서 동기식 사용자 트랜잭션의 Tail Latency를 방어하는 핵심 커널 메커니즘입니다.
