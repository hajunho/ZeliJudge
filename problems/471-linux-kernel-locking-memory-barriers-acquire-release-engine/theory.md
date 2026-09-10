# 리눅스 커널 메모리 모델(LKMM) 및 획득-해제(Acquire-Release) 아키텍처 이론

## 1. 하드웨어 메모리 모델: TSO vs Weak Ordering

모든 멀티코어 하드웨어는 성능을 위해 캐시 일관성(Cache Coherence) 프로토콜(MESI/MOESI)과 별도로 쓰기 버퍼(Store Buffer)를 둡니다:
- CPU 코어가 메모리에 쓸 때, L1 캐시 라인을 독점(Exclusive)하기 위해 버스 조회가 끝날 때까지 기다리지 않고, 즉시 로컬 쓰기 버퍼에 집어넣고 다음 명령어로 넘어갑니다.
- **x86 TSO (Total Store Order)**:
  - Store-Store 순서는 하드웨어가 FIFO로 엄격히 유지합니다.
  - Load-Load 순서도 유지됩니다.
  - 유일한 재정렬: **Store-Load Reordering**. 내가 쓴 쓰기가 아직 버퍼에 머물러 있는 동안 다른 변수의 읽기를 먼저 실행할 수 있습니다.
- **ARM64 / RISC-V (Weak Ordering)**:
  - 쓰기 버퍼뿐만 아니라 비순차적 메모리 컨트롤러 파이프라인으로 인해 모든 방향의 재정렬(Load-Load, Store-Store, Load-Store, Store-Load)이 자유롭게 발생합니다.

---

## 2. 획득-해제 시맨틱 (Acquire-Release Semantics)

전역 `smp_mb()`(DMB ISH on ARM, MFENCE on x86)는 파이프라인 전체를 멈추므로 오버헤드가 큽니다.
대부분의 동시성 패턴(락, 큐, 플래그 통지)은 **단방향 배리어(One-way Barrier)**인 획득-해제 쌍만으로 100% 안전성을 달성할 수 있습니다:

### 2.1 `smp_store_release()` (Release Barrier)
- 수식: $\forall \text{op} < \text{store\_release} \implies \text{op} \xrightarrow{\text{coherence}} \text{store\_release}$
- 이 릴리즈 쓰기보다 프로그램 순서상 앞선 모든 읽기/쓰기는, 이 릴리즈 쓰기보다 뒤로 밀려날 수 없습니다.
- ARM64에서는 `STLR` (Store-Release Register) 단일 명령어로 하드웨어 가속됩니다.

### 2.2 `smp_load_acquire()` (Acquire Barrier)
- 수식: $\forall \text{op} > \text{load\_acquire} \implies \text{load\_acquire} \xrightarrow{\text{coherence}} \text{op}$
- 이 획득 읽기보다 프로그램 순서상 뒤에 위치한 모든 읽기/쓰기는, 이 획득 읽기보다 앞으로 당겨져 투기적으로 실행될 수 없습니다.
- ARM64에서는 `LDAR` (Load-Acquire Register) 단일 명령어로 실행됩니다.

---

## 3. 리눅스 커널 락리스 동기화 불변식

생산자-소비자(Producer-Consumer) 패턴에서:
```c
// CPU 0 (Producer)
payload->size = 1024;
payload->data = buffer;
smp_store_release(&ring->head, new_head);

// CPU 1 (Consumer)
head = smp_load_acquire(&ring->head);
if (head != last_head) {
    /* smp_load_acquire 덕분에 payload->data와 size가 
       반드시 올바르게 관측됨이 수학적으로 증명됨! */
    process(payload->data);
}
```

만약 `smp_store_release` 대신 일반 대입을 사용하면, ARM 코어는 `ring->head` 쓰기를 `payload->data` 쓰기보다 먼저 버스에 노출시킬 수 있어 소비자가 쓰레기 데이터(Uninitialized Garbage)를 읽는 파멸적인 데이터 레이스가 발생합니다.

LKMM(Linux Kernel Memory Model)은 커널 내부의 RCU, 슬랩 할당자, io_uring, eBPF 링버퍼, 네트워크 스택 전체의 락리스 무결성을 지탱하는 근본 이론입니다.
