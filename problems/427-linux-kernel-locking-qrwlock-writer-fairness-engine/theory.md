# 문제 427 심층 이론: 리눅스 커널 qrwlock(Queued Read-Write Lock)과 멀티코어 동시성 확장성

---

## 1. 레거시 rwlock의 한계: Reader Preference와 Writer Starvation

컴퓨터 과학의 고전적인 독자-저술가 문제(Readers-Writers Problem)에서 가장 단순한 구현은 **독자 우선(Reader-Preference)** 방식입니다.
표준 C/POSIX 및 초기 리눅스 커널의 `rwlock_t`는 다음과 같이 동작했습니다:
```c
/* Legacy reader lock */
void read_lock(rwlock_t *lock) {
    while (atomic_dec_return(&lock->cnts) < 0) {
        atomic_inc(&lock->cnts);
        cpu_relax();
    }
}
```
이 방식의 치명적인 결함은 다음과 같습니다:
1. **무한 대기(Unbounded Wait Time)**: 읽기 스레드가 이미 임계 영역에 있는 동안 또 다른 읽기 스레드가 들어오면 락 획득이 즉시 허용됩니다. 따라서 웹 서버, 데이터베이스, VFS 경로 탐색 등 읽기 트래픽이 끊이지 않는 워크로드에서 쓰기 스레드는 **기아(Starvation)**에 빠져 영원히 실행되지 못합니다 ($T_{\text{wait}} \to \infty$).
2. **MESI 캐시 일관성 폭풍**: 읽기 스레드가 진입/탈출할 때마다 공용 캐시라인을 무조건 원자적으로 수정(`atomic_inc/dec`)하므로, 수백 개의 코어가 동일 캐시라인의 소유권을 뺏고 뺏기는 **캐시라인 바운싱(Cacheline Bouncing)**이 발생하여 병렬 읽기 성능이 급격히 저하됩니다.

---

## 2. qrwlock 아키텍처와 32비트 비트필드 분할

피터 제일스트라와 와이먼 롱이 고안한 `qrwlock`은 **쓰기 스레드의 대기 시간을 유한하게 제한(Bounded Waiting Time)**하면서도 읽기 스레드의 병렬성을 극대화합니다.

### 2.1 32비트 정수 원자적 레이아웃
```
union arch_rwlock {
    atomic_t cnts;
    struct {
        u8 wlocked;    /* 0x01: Write locked */
        u8 byte_1;     /* 0x0100: Write waiting */
        u16 readers;   /* Reader count */
    };
};
```
- `_QW_LOCKED = 0x00000001`
- `_QW_WAITING = 0x00000100`
- `_QR_BIAS = 0x00000200`

---

## 3. 쓰기 배리어(Writer Barrier)와 쓰기 기아 박멸

`qrwlock`이 쓰기 기아를 원천 차단하는 핵심 수학적 원리는 **쓰기 배리어 비트(`_QW_WAITING`)**에 있습니다.

### 3.1 상한 보장 수학적 분석
활성 읽기 스레드 집합을 $R_{\text{active}} = \{r_1, r_2, \dots, r_k\}$라 하고, 각 읽기 스레드의 남은 임계 영역 실행 시간을 $t_{\text{rem}}(r_i)$라 할 때:
1. 쓰기 스레드 $W$가 도착하면 원자적 CAS를 통해 `_QW_WAITING` 비트를 1로 설정합니다.
2. 이 순간부터 이후에 도착하는 모든 신규 읽기 스레드는 `cnts & (_QW_LOCKED | _QW_WAITING) != 0` 검사에서 탈락하여 즉시 대기 큐로 우회됩니다.
3. 따라서 쓰기 스레드 $W$의 대기 시간 $T_{\text{wait}}(W)$는 다음과 같이 엄격히 상한이 정해집니다:
   $$T_{\text{wait}}(W) \le \max_{r_i \in R_{\text{active}}} t_{\text{rem}}(r_i) + \tau_{\text{handoff}} < \infty$$
   아무리 많은 읽기 트래픽이 밀려와도, 쓰기 스레드는 이미 들어와 있던 기존 읽기 스레드들만 끝나면 즉각 락을 획득합니다.

---

## 4. MCS Lock 기반 다중 쓰기 스레드 큐잉

둘 이상의 쓰기 스레드가 동시에 도착하면 어떻게 될까요?
만약 모든 대기 쓰기 스레드가 단일 글로벌 락 워드를 폴링(Spinning)한다면 다시 캐시라인 바운싱이 발생합니다.

`qrwlock`은 이를 방지하기 위해 **MCS(Mellor-Crummey and Scott) 잠금 큐**를 결합합니다:
- 첫 번째 쓰기 스레드만이 `_QW_WAITING`을 세팅하고 글로벌 워드를 감시합니다.
- 두 번째 이후의 쓰기 스레드들은 Per-CPU MCS 노드 큐(`qnode`)의 로컬 변수를 폴링합니다.
- 앞선 쓰기 스레드가 임계 영역을 마치면, 다음 MCS 노드의 포인터를 원자적으로 갱신하여 락을 직접 인계(Direct Handoff)합니다.
이를 통해 수백 코어 서버에서도 버스 인터커넥트 경합을 $O(1)$로 제한합니다.

---

## 5. 결론

리눅스 커널의 `qrwlock`은 현대 고성능 시스템 소프트웨어에서 동시성 제어의 이상적인 균형점입니다:
- **읽기 스레드**: 쓰기가 없을 때 1개의 원자적 명령어(`atomic_add`)만으로 0-지연 패스트패스 획득.
- **쓰기 스레드**: `_QW_WAITING` 배리어를 통해 읽기 폭풍 속에서도 기아 없이 결정론적 상한 시간 내 임계 영역 진입 보장.
- 대규모 클라우드 서버와 데이터베이스 커널의 확장성을 보장하는 가장 정교하고 우아한 락 기법입니다.
