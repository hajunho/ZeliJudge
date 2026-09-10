# Theory: Linux Kernel x86 Split Lock Detection & Bus Lock Rate Limiting (`arch/x86/kernel/cpu/intel.c`)

## 1. 캐시 락킹(Cache Locking)과 스플릿 락(Split Lock)의 하드웨어 메커니즘

대칭형 다중 처리(SMP) x86 아키텍처에서 원자적 RMW(Read-Modify-Write) 명령어(`LOCK CMPXCHG`, `LOCK XADD`, `LOCK BTS` 등)는 다중 코어 간 공유 데이터의 무결성을 유지합니다.

### 1.1 정상 원자 연산: 캐시 라인 락킹 (Cache Locking)
- 피연산자가 단일 64바이트 캐시라인 내부에 정렬되어 있는 경우, CPU 코어는 L1D 캐시에서 해당 라인을 **Exclusive(E)** 또는 **Modified(M)** 상태로 획득(MESI 프로토콜)하고 내부 파이프라인에서 원자 연산을 완료합니다.
- 시스템 전체 메모리 버스를 잠그지 않으므로 수 나노초(몇 CPU 사이클) 내에 초고속으로 완료됩니다.

### 1.2 비정렬 원자 연산: 스플릿 락 (Split Lock)
- 피연산자의 메모리 주소가 64바이트 캐시라인 경계에 걸쳐 있는 경우(예: 주소 `0x3E`, 크기 4바이트 $\rightarrow$ 바이트 `0x3E..0x3F`는 0번 라인, `0x40..0x41`은 1번 라인에 위치):
- 하드웨어는 두 개의 독립된 캐시라인을 동시에 원자적으로 갱신할 수 없습니다.
- 결국 CPU는 인텔 펜티엄 시대의 레거시 신호인 **LOCK# 버스 핀(Bus Lock Signal)**을 프로세서 인터커넥트에 발신합니다.
- 버스 락이 활성화되는 수백~수천 사이클 동안 메모리 컨트롤러와 동일 소켓 내의 모든 다른 CPU 코어는 메모리 접근이 강제 동결(Bus Stall)됩니다.

---

## 2. 보안 취약점과 리눅스 커널 완화책

비특권 유저스페이스 프로세스나 비신뢰 가상 머신(KVM 게스트)이 루프를 돌며 비정렬 스플릿 락을 고의로 실행하면 물리 서버 전체의 메모리 대역폭이 고갈되는 서비스 거부 공격(DoS)이 발생합니다.

### 2.1 하드웨어 MSR과 `#AC` 정렬 검사 예외
Intel Tremont/Ice Lake 및 최신 아키텍처는 `MSR_TEST_CTRL` (0x33) 레지스터의 비트 29(`TEST_CTRL_SPLIT_LOCK_DETECT`)를 제공합니다:
- 이 비트가 1로 설정되면, CPU는 스플릿 락이 발생할 때 버스 락을 걸기 전에 Ring 0에서 **정렬 검사(#AC, Alignment Check)** 예외를 즉각 유발합니다.
- 리눅스 커널(`arch/x86/kernel/cpu/intel.c`)은 `split_lock_detect` 부트 파라미터를 통해 4가지 정책을 제공합니다:
  1. `off`: 하드웨어 탐지 비활성화 (레거시 동작).
  2. `warn`: 최초 1회 dmesg 경고 출력 후 허용.
  3. `fatal`: 트랩 발생 시 프로세스에 `SIGBUS`를 발송하여 즉시 프로세스를 사살.
  4. `ratelimit`: 초당 허용 횟수를 제한하고 초과 시 프로세스를 수십 ms 동안 슬립(`msleep`)시켜 DoS 공격을 무력화.
