# 심층 이론: Linux 커널 FUSE(Filesystem in Userspace) 아키텍처와 큐잉 서브시스템

---

## 1. 마이크로커널 파일 시스템의 현대적 부활: FUSE

1980~1990년대 Mach, QNX 등 마이크로커널(Microkernel) 아키텍처는 운영체제의 핵심 기능을 유저 공간 서버 프로세스로 분리하려 시도했으나 극심한 IPC(Inter-Process Communication) 컨텍스트 스위칭 오버헤드로 인해 모놀리식 커널에 패배했습니다.

그러나 2000년대 중반, 클라우드 컴퓨팅과 분산 스토리지의 태동과 함께 리눅스 커널에 도입된 **FUSE (Filesystem in Userspace, `fs/fuse/`)**는 마이크로커널의 안전성과 모놀리식 커널의 실용성을 이상적으로 결합했습니다:
- 로컬 고속 I/O가 필요한 루트 파티션(ext4, XFS)은 커널에 유지합니다.
- 복잡한 REST API 통신(Amazon S3FS), 암호화(EncFS), 압축(Archivemount), 분산 오브젝트(CephFS) 파일 시스템은 FUSE로 유저 공간에 격리하여, 데몬이 크래시되더라도 커널 전체가 죽는 참사를 방지합니다.

---

## 2. FUSE 커널 드라이버 내부 구조와 4대 큐 메커니즘

FUSE는 `/dev/fuse`라는 특수 캐릭터 디바이스를 통해 사용자 공간 파일시스템 데몬과 통신합니다. 커널 구조체 `struct fuse_conn`과 `struct fuse_iqueue` 내부에는 목적이 서로 다른 4개의 요청 큐가 존재합니다.

```
                     [ FUSE 4-Queue State Transition Diagram ]

      VFS System Call (open, read, stat)
                     |
         +-----------+-----------+
         |                       |
    (Foreground)            (Background)
         |                       |
         |             [ num_bg < max_bg? ]
         |                 /          \
         |               YES           NO
         |               /              \
         v              v                v
      +--------------------+      +--------------------+
      |  fiq->pending      |      |  fc->bg_queue      |
      |  (Pending Queue)   |<-----+  (Background Q)    |
      +--------------------+   (Refill when slot opens)|
                |                                      |
         read(/dev/fuse)                               |
                |                                      v
                v                             [ BDI Congestion Check ]
      +--------------------+                  total_bg >= threshold?
      |  fc->processing    |                  -> Mark BDI CONGESTED!
      |  (Processing Queue)|
      +--------------------+
         /              \
    write(/dev/fuse)  SIGINT (Interrupt)
       /                  \
      v                    v
  [ COMPLETED ]       [ Enqueue FUSE_INTERRUPT to fiq->interrupts ]
                      -> Abort Daemon Worker -> [ INTERRUPTED ]
```

### 2.1 Pending Queue (`fiq->pending`)
사용자 스레드가 동기 I/O를 호출하면 슬립 상태(`wait_event_interruptible`)에 빠지며 `struct fuse_req`가 `fiq->pending`에 링크됩니다. 데몬이 `read(/dev/fuse)`를 실행하면 커널은 이 큐의 헤드에서 요청을 꺼내 유저 버퍼로 복사하고, 요청을 `fc->processing` 큐로 옮깁니다.

### 2.2 Processing Queue (`fc->processing`)
데몬 워커 스레드가 실제로 작업을 수행 중인 요청 목록입니다. 데몬이 I/O를 마치고 `write(/dev/fuse)`를 호출하면 요청은 완료 상태로 전환되고 대기 중이던 원래 애플리케이션 스레드가 깨어납니다(`wake_up`).

### 2.3 Background Queue (`fc->bg_queue`)와 BDI 혼잡 제어
비동기 쓰기나 리드어헤드가 폭주하여 수천 개의 요청이 데몬으로 쏟아지면 데몬의 메모리가 고갈되거나 스레드 풀이 고갈될 수 있습니다.
FUSE는 `max_background` (기본값 12) 파라미터를 통해 동시 활성 백그라운드 요청 수를 제한합니다.
- `num_background < max_background`이면 즉시 `pending`으로 보내 데몬이 읽어가게 합니다.
- 초과분은 `bg_queue`에 대기시킵니다.
- `num_background + len(bg_queue) >= congestion_threshold` (기본값 9)에 도달하면 백킹 디바이스(BDI)를 혼잡으로 설정하여 VFS 더티 페이지 생성자를 스톨(Stall)시킵니다.

### 2.4 Interrupt Queue (`fiq->interrupts`)
FUSE I/O를 기다리던 프로세스가 Ctrl+C를 누르면:
- 요청이 아직 `pending` 큐에 있다면 커널 내부에서 즉시 삭제하고 `-EINTR`을 반환합니다.
- 이미 `processing` 큐로 넘어가 유저 데몬이 로컬 디스크나 원격 네트워크에 쓰기를 수행하고 있다면, 커널은 `FUSE_INTERRUPT` 패킷을 `fiq->interrupts`에 삽입합니다.
- 데몬은 다음 `read()` 시 일반 요청보다 인터럽트 요청을 최우선으로 수신하여 하던 작업을 즉시 중단(Abort)하고 리소스를 정리합니다.

---

## 3. VFS 하이브리드 캐싱과 Splice 제로카피 최적화

FUSE의 가장 큰 병목은 유저-커널 컨텍스트 스위칭과 데이터 더블 카피(Double Copy)입니다. 리눅스 커널은 이를 해결하기 위해 정교한 최적화 계층을 제공합니다:

1. **Dentry / Attribute Timeout Cache**:
   `FUSE_LOOKUP`과 `FUSE_GETATTR` 응답에 `entry_valid`와 `attr_valid` 타임스탬프를 부여합니다. 지정된 시간 동안은 VFS 계층이 데몬을 호출하지 않고 커널 캐시에서 즉시 응답하여 `ls -l` 등의 메타데이터 조회를 수십 배 가속합니다.
2. **Writeback Cache (`FUSE_WRITEBACK_CACHE`)**:
   작은 `write()`들을 매번 유저 공간으로 보내지 않고 커널 페이지 캐시에 모아두었다가, 128KB 이상의 큰 청크로 묶어서 백그라운드 큐를 통해 데몬으로 전달합니다.
3. **Splice Zero-Copy (`FUSE_SPLICE_READ`, `FUSE_SPLICE_WRITE`)**:
   `/dev/fuse`와 파일 디스크립터 간의 데이터 전송 시 리눅스 파이프 버퍼(`struct pipe_buffer`)의 페이지 참조 카운트만 교환하여 CPU 메모리 복사 없이 10Gbps 이상의 순수 네트워크/스토리지 대역폭을 달성합니다.
