# 126. CPU 5%인데 왜 서버가 뻗고 로드 애버리지(Load Average)가 100을 찍어요?!: 리눅스 커널 프로세스 D 상태(TASK_UNINTERRUPTIBLE)와 지수 감쇠 이동 평균(EMA)

## 문제 설명

스타트업의 주니어 데브옵스 엔지니어 젤리(Zeli)는 운영 중인 리눅스 API 서버가 갑자기 아무런 응답을 주지 않고 타임아웃을 뿜어낸다는 긴급 장애 호출을 받았습니다. 🚨  
황급히 SSH로 접속하여 `top`과 `uptime` 명령어를 실행한 젤리는 자신의 눈을 의심했습니다:

```
top - 14:30:00 up 10 days,  load average: 85.32, 70.15, 45.10
Tasks: 210 total,   2 running, 150 sleeping,   0 stopped,   0 zombie
%Cpu(s):  3.2 us,  1.5 sy,  0.0 ni,  1.1 id, 94.2 wa,  0.0 hi,  0.0 si
```

- **CPU 사용률(`%Cpu us+sy`)**: 겨우 4.7%! (CPU 코어 4개는 거의 놀고 있음)
- **그런데 로드 애버리지(Load Average)**: 1분 평균이 무려 **85.32**! (4코어 머신에서 85는 정상 수용량의 2000% 초과!)
- **더 기괴한 현상**: `ps aux`로 확인해 보니 80여 개의 백엔드 워커 프로세스가 상태 열에 **`D`**를 띄우고 있었고, 젤리가 터미널에서 `kill -9 <PID>` (`SIGKILL`)를 아무리 날려도 **프로세스가 전혀 죽지 않고 계속 살아남아** 있었습니다! 😱

*"CPU는 5%밖에 안 쓰는데 왜 서버는 마비되고 Load Average는 85를 찍죠?! 그리고 왜 절대무적의 명령어인 `kill -9`로도 프로세스가 안 죽나요?!"*

---

### 왜 이런 일이 발생할까? (D 상태와 1993년 리눅스 토발즈의 역사적 결정)

많은 개발자들이 **"Load Average = CPU 사용률"**이라고 오해하지만, 이 둘은 본질적으로 다릅니다:
- **CPU 사용률(%)**: CPU 연산 장치가 코드를 실행하느라 얼마나 바쁜지 나타내는 순간 비율.
- **로드 애버리지(Load Average)**: CPU에서 실행 중인 태스크뿐만 아니라, **하드웨어 디스크/스토리지 I/O를 기다리며 멈춰 있는 활성 태스크들의 총 수요(Demand)**를 지수 이동 평균으로 측정한 값.

#### 1. 리눅스 프로세스 상태와 D 상태(`TASK_UNINTERRUPTIBLE`)
리눅스 커널에서 프로세스는 다음 상태를 갖습니다:
- **`R` (`TASK_RUNNING`)**: CPU에서 코드를 실행 중이거나 CPU 런큐(Runqueue)에서 대기 중.
- **`S` (`TASK_INTERRUPTIBLE`)**: 소켓 수신이나 타이머를 기다리며 수면 중. 시그널을 받으면 즉시 깨어남.
- **`D` (`TASK_UNINTERRUPTIBLE`)**: **디스크 블록 읽기/쓰기, 원격 NFS RPC 응답, 파일시스템 메타데이터 저널링 락을 기다리며 대기 중**.

#### 2. D 상태 프로세스는 왜 `kill -9`로도 안 죽을까?
D 상태인 프로세스는 커널의 파일시스템이나 디바이스 드라이버 내부에서 하드웨어 DMA 전송 완료나 원격 스토리지 응답을 기다리고 있습니다.  
만약 이 순간 프로세스를 강제 종료(`SIGKILL`)해 버리면:
- 하드웨어가 방금 해제된 쓰레기 메모리 주소에 데이터를 덮어쓰거나,
- 파일시스템 저널링 락이 풀리지 않아 디스크 전체가 깨지거나(`Filesystem Corrupted`),
- **커널 패닉(Kernel Panic)**으로 서버가 즉사할 위험이 있습니다.  
따라서 리눅스 커널은 **"하드웨어 I/O가 끝날 때까지 신(God)이 와도 이 프로세스를 강제 종료하지 못하게 보호"**합니다!

#### 3. 리눅스 토발즈의 1993년 커널 패치
1993년 오리지널 UNIX는 오직 `R` 상태만 로드에 포함했습니다.  
하지만 리눅스 토발즈(Linus Torvalds)는 **"디스크나 스토리지가 느려서 멈춰 있는 작업(`D` 상태)도 명백히 시스템 자원을 요구하는 부하이므로 로드에 포함해야 한다"**며 공식을 바꿨습니다:

$$	ext{Active Tasks } (n) = 	ext{count}(R) + 	ext{count}(D)$$

결과적으로, 원격 NFS 스토리지에 네트워크 순단이 발생하거나 디스크에 배드섹터가 생겨 수십 개의 워커가 `D` 상태로 뻗으면, **CPU 사용률은 0%인데도 로드 애버리지가 100을 돌파하는 기현상**이 발생하게 됩니다!

---

### 로드 애버리지(Load Average) 수학적 계산 공식

리눅스 커널(`kernel/sched/loadavg.c`)은 **정확히 매 5초($\Delta t = 5$)마다** 활성 태스크 수($n = R + D$)를 샘플링하여 지수 감쇠 이동 평균(Exponentially Damped Moving Average, EMA)을 계산합니다:

$$	ext{load}_	au(t) = 	ext{load}_	au(t - \Delta t) 	imes e^{-\Delta t / 	au} + n 	imes (1 - e^{-\Delta t / 	au})$$

- $	au = 60$초 (1분 로드 평균): 감쇠 계수 $c_1 = e^{-5/60} pprox 0.920044$
- $	au = 300$초 (5분 로드 평균): 감쇠 계수 $c_5 = e^{-5/300} pprox 0.983471$
- $	au = 900$초 (15분 로드 평균): 감쇠 계수 $c_{15} = e^{-5/900} pprox 0.994460$

---

## 과제

당신은 리눅스 커널의 프로세스 상태 추적 및 로드 애버리지(Load Average) 산출 알고리즘을 구현하는 **"리눅스 로드 시뮬레이터"**를 작성해야 합니다.

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 JSON 객체가 주어집니다:
- `system_config`:
  - `cpu_cores`: 서버의 CPU 코어 수 (정수 $\ge 1$)
  - `sampling_interval_sec`: 로드 애버리지 샘플링 주기 (초, 정수 $\ge 1$, 기본 5)
- `initial_loadavg`: 시작 시점의 로드 애버리지 (`{"load1": float, "load5": float, "load15": float}`)
- `ticks`: 시간순 샘플링 틱 배열. 각 틱:
  - `time`: 샘플링 시점 (초)
  - `processes`: 현재 시스템의 프로세스 목록:
    - `pid`: 프로세스 ID (정수)
    - `state`: `"R"` (실행/준비) | `"D"` (무인터럽트 수면) | `"S"` (인터럽트 가능 수면) | `"Z"` (좀비)
    - `command`: 실행 명령어 (문자열)
    - `wchan`: (선택) 커널 대기 함수 (예: `"nfs_wait"`, `"io_schedule"`)
  - `signal_sent`: (선택) 특정 프로세스에 시그널 발송 시도:
    - `pid`: 대상 PID
    - `signal`: `"SIGKILL"` | `"SIGTERM"` 등

---

### 처리 규칙

1. **시그널 처리**:
   - `signal_sent`가 있을 경우:
     - 대상 프로세스가 존재하지 않으면: `result = "NOT_FOUND"`.
     - 대상 프로세스의 상태가 `"D"`이면:
       - **D 상태 프로세스는 시그널을 처리할 수 없으므로 무시됩니다.**
       - `result = "SIGNAL_IGNORED_D_STATE"`. 상태는 `"D"`로 유지됩니다.
     - 대상 프로세스의 상태가 `"R"` 또는 `"S"`이면:
       - 프로세스가 종료되어 좀비/종료 상태(`"Z"`)로 전이됩니다.
       - `result = "TERMINATED"`.
2. **활성 태스크 수($n$) 산출**:
   - 리눅스 규칙에 따라, **현재 상태가 `"R"`이거나 `"D"`인 프로세스의 합**을 구합니다:
     $$n = 	ext{count}(R) + 	ext{count}(D)$$
   - `"S"`와 `"Z"` 상태는 부하 계산에서 제외됩니다.
3. **지수 감쇠 이동 평균(EMA) 갱신**:
   - 감쇠 계수: $c_1 = e^{-\Delta t / 60}$, $c_5 = e^{-\Delta t / 300}$, $c_{15} = e^{-\Delta t / 900}$
   - $	ext{load}_	au = 	ext{load}_	au 	imes c_	au + n 	imes (1 - c_	au)$
4. **병목 진단 (Bottleneck Diagnosis)**:
   - 각 틱별:
     - $D > R$ 이고 $D > 0$ 이면: `"IO_STORAGE_BOTTLENECK"`
     - $R > 	ext{cpu\_cores}$ 이면: `"CPU_COMPUTE_BOTTLENECK"`
     - 그 외: `"HEALTHY_WITHIN_CAPACITY"`
   - 전체 요약 (`primary_bottleneck`):
     - 전체 누적 $D > 	ext{누적 } R$ 이고 누적 $D > 0$ 이면: `"IO_STORAGE_BOTTLENECK"`
     - 전체 누적 $R > (	ext{cpu\_cores} 	imes 	ext{틱 수})$ 이면: `"CPU_COMPUTE_BOTTLENECK"`
     - 그 외: `"HEALTHY_WITHIN_CAPACITY"`

---

### 출력 형식 (JSON)

표준 출력(stdout)으로 다음 JSON 객체(들여쓰기 2칸)를 출력합니다:
- `summary`:
  - `final_loadavg`: 소수점 2자리 반올림된 최종 로드 (`load1`, `load5`, `load15`)
  - `max_load1`: 관측된 최대 1분 로드 (소수점 2자리)
  - `primary_bottleneck`: 전체 기간의 주요 병목
  - `unkillable_d_processes`: D 상태로 관측된 고유 PID 목록 (오름차순 정렬)
  - `signal_events`: 시그널 처리 결과 목록
- `tick_history`: 각 틱별 세부 통계 (소수점 4자리 loadavg 및 상태 카운트)

```json
{
  "summary": {
    "final_loadavg": {
      "load1": 0.88,
      "load5": 0.58,
      "load15": 0.53
    },
    "max_load1": 0.88,
    "primary_bottleneck": "IO_STORAGE_BOTTLENECK",
    "unkillable_d_processes": [
      102,
      103
    ],
    "signal_events": [
      {
        "time": 5,
        "pid": 102,
        "signal": "SIGKILL",
        "state": "D",
        "result": "SIGNAL_IGNORED_D_STATE",
        "explanation": "Process in TASK_UNINTERRUPTIBLE ignores all signals including SIGKILL"
      }
    ]
  },
  "tick_history": [
    {
      "time": 5,
      "counts": {
        "R": 1,
        "D": 2,
        "S": 1,
        "Z": 0,
        "active": 3
      },
      "loadavg": {
        "load1": 0.6999,
        "load5": 0.5413,
        "load15": 0.5139
      },
      "diagnosis": "IO_STORAGE_BOTTLENECK"
    }
  ]
}
```

---

## 입출력 예시

### 예시 1
**입력**:
```json
{
  "system_config": {
    "cpu_cores": 4,
    "sampling_interval_sec": 5
  },
  "initial_loadavg": {
    "load1": 0.5,
    "load5": 0.5,
    "load15": 0.5
  },
  "ticks": [
    {
      "time": 5,
      "processes": [
        {"pid": 101, "state": "R", "command": "python_worker"},
        {"pid": 102, "state": "D", "command": "nfs_sync", "wchan": "nfs_wait"},
        {"pid": 103, "state": "D", "command": "disk_flush", "wchan": "io_schedule"},
        {"pid": 104, "state": "S", "command": "redis"}
      ],
      "signal_sent": {
        "pid": 102,
        "signal": "SIGKILL"
      }
    },
    {
      "time": 10,
      "processes": [
        {"pid": 101, "state": "R", "command": "python_worker"},
        {"pid": 102, "state": "D", "command": "nfs_sync", "wchan": "nfs_wait"},
        {"pid": 103, "state": "D", "command": "disk_flush", "wchan": "io_schedule"},
        {"pid": 104, "state": "S", "command": "redis"}
      ]
    }
  ]
}
```

**출력**:
```json
{
  "summary": {
    "final_loadavg": {
      "load1": 0.88,
      "load5": 0.58,
      "load15": 0.53
    },
    "max_load1": 0.88,
    "primary_bottleneck": "IO_STORAGE_BOTTLENECK",
    "unkillable_d_processes": [
      102,
      103
    ],
    "signal_events": [
      {
        "time": 5,
        "pid": 102,
        "signal": "SIGKILL",
        "state": "D",
        "result": "SIGNAL_IGNORED_D_STATE",
        "explanation": "Process in TASK_UNINTERRUPTIBLE ignores all signals including SIGKILL"
      }
    ]
  },
  "tick_history": [
    {
      "time": 5,
      "counts": {
        "R": 1,
        "D": 2,
        "S": 1,
        "Z": 0,
        "active": 3
      },
      "loadavg": {
        "load1": 0.6999,
        "load5": 0.5413,
        "load15": 0.5139
      },
      "diagnosis": "IO_STORAGE_BOTTLENECK"
    },
    {
      "time": 10,
      "counts": {
        "R": 1,
        "D": 2,
        "S": 1,
        "Z": 0,
        "active": 3
      },
      "loadavg": {
        "load1": 0.8838,
        "load5": 0.582,
        "load15": 0.5276
      },
      "diagnosis": "IO_STORAGE_BOTTLENECK"
    }
  ]
}
```
