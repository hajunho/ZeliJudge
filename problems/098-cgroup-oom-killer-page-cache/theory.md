# 098. 쿠버네티스 파드에 메모리 1GB 줬는데 왜 자바는 600MB만 쓰다 OOMKilled로 즉사당해요?!: Linux Cgroup v2와 커널 페이지 캐시(Page Cache) & JVM 메모리 오해

---

## 1. 비극의 시작: 10평 원룸과 택배 박스(페이지 캐시)의 비극

어느 날 깐깐한 집주인(리눅스 Cgroup)이 10평짜리 원룸(컨테이너, `memory.max = 1024MB`)을 세놓으며 엄격한 계약 조건을 걸었습니다:
> **"이 원룸 안의 모든 짐의 총합이 10평(1GB)을 1바이트라도 넘는 순간, 나는 묻지도 따지지도 않고 세입자를 쇠지렛대로 때려눕힌 뒤 창밖으로 던져버릴 겁니다(OOM-Killer SIGKILL 137)!"**

세입자 진우(자바 JVM 프로세스)는 계산기를 두드렸습니다:
> *"내 침대와 책상(JVM Heap, `-Xmx600m`)은 다 합쳐도 6평(600MB)밖에 안 되잖아? 10평 중에 4평이나 널널하게 남으니까 난 절대 쫓겨날 일 없어!"*

그런데 진우가 이사 온 뒤 인터넷 쇼핑(파일 다운로드 및 대용량 로그 쓰기)을 시작했습니다:
1. **택배 상자의 누적 (페이지 캐시, Page Cache)**:  
   택배가 올 때마다 물건을 꺼내고 남은 택배 상자와 뽁뽁이들이 방구석에 차곡차곡 쌓여 **3.5평(350MB)**을 차지했습니다.  
   커널은 "어차피 방에 여유 공간이 있으니, 나중에 다시 쓸 수도 있는 택배 상자(파일 캐시)를 굳이 지금 재활용장에 안 버리고 방 안에 놔두자!"라고 생각했습니다.
2. **총 짐의 면적 = 9.5평 (950MB)**:  
   침대(600MB) + 택배 상자(350MB) = 이미 방이 꽉 차기 일보 직전이었습니다.
3. **참사의 순간 (메모리 100MB 추가 할당)**:  
   진우가 친구를 재우기 위해 작은 간이 매트리스(Non-Heap 또는 순간 힙 할당 100MB)를 방에 들이려 했습니다.
   총 짐이 **10.5평(1050MB)**이 되면서 10평 한도를 뚫어버렸습니다!
4. **OOM-Killer의 처단**:  
   커널이 택배 상자를 후다닥 내다 버릴(Page Reclaim) 틈도 없이, 한도를 넘은 것을 본 집주인(Cgroup OOM-Killer)이 몽둥이를 들고 들어와 **진우의 뒤통수를 가격하여 즉사(SIGKILL / Exit Code 137)**시켜 버렸습니다!

진우는 "난 600MB밖에 안 썼는데 왜 죽여요?!"라고 외칠 기회(OutOfMemoryError 스택트레이스)조차 얻지 못하고 싸늘한 주검(`OOMKilled`)이 되어 쫓겨난 것입니다.

---

## 2. 컴퓨터 과학 / 커널 엔지니어링 이론

### 1) Linux Cgroup v2 메모리 회계 (Memory Accounting)
리눅스 커널의 Cgroup은 프로세스가 스스로 선언한 `-Xmx` 따위는 쳐다보지도 않습니다.  
컨테이너의 실제 물리 메모리 점유(`memory.current`)는 다음과 같은 구성 요소의 **총합**입니다:

$$	ext{memory.current} = 	ext{anon} + 	ext{file} + 	ext{kernel}$$

| 구성 요소 | 세부 항목 | 설명 |
| :--- | :--- | :--- |
| **`anon` (Anonymous)** | Process RSS (Heap, Stack) | 파일과 연결되지 않은 순수 프로세스 메모리. JVM Heap, Native 힙, 스레드 스택 |
| **`file` (Page Cache)** | Active File / Inactive File | 디스크 파일 I/O 시 커널이 RAM에 올려둔 캐시. 로그 파일, jar 파일, mmap 등 |
| **`kernel` (Kernel Memory)**| Slab, Dentry, Socket Buffer | 커널이 프로세스를 위해 관리하는 내부 자료구조, TCP 소켓 수신/송신 버퍼 |

### 2) 페이지 캐시(Page Cache)와 회수(Reclaim) 메커니즘
- 리눅스는 RAM 여유 공간이 있으면 디스크 I/O 속도를 극대화하기 위해 읽고 쓴 모든 파일 데이터를 **페이지 캐시(Page Cache)**에 보관합니다.
- **회수 가능한 메모리 vs 불가능한 메모리**:
  - `Inactive File`: 아직 디스크와 동일한 깨끗한(clean) 페이지. 메모리가 부족하면 커널이 디스크에 쓸 필요 없이 **즉시 파기(Eviction)** 가능.
  - `Dirty Page`: 아직 디스크에 플러시되지 않고 수정된 페이지. 디스크에 동기화(flush)하기 전까지는 즉시 파기 불가!
  - `Active File`: 최근에 빈번하게 접근된 파일 캐시.
- **다이렉트 회수(Direct Reclaim)와 스파이크**:
  - 메모리 사용량이 `memory.max`에 근접했을 때 새로운 할당 요청이 들어오면, 커널은 할당 요청을 멈추고(스톨, Stall) 급하게 페이지 캐시를 회수하는 **Direct Reclaim**을 시도합니다.
  - 하지만 회수 가능한 Inactive File을 다 털어내도 부족하거나, Dirty Page 플러시가 디스크 병목으로 지연되면 커널은 더 이상 버티지 못하고 OOM-Killer를 호출합니다.

### 3) Cgroup v2 워터마크: `memory.high` vs `memory.max`
Cgroup v2에서는 급작스러운 OOMKilled를 방지하기 위해 2단계 보호막을 제공합니다:
- **`memory.high` (Throttle Limit / Soft Watermark)**:
  - 메모리가 이 선을 넘으면 OOM-Killer가 죽이지 않고, 대신 메모리를 요청한 프로세스의 CPU 속도를 늦추며(Throttling) 백그라운드에서 적극적으로 페이지 캐시를 회수합니다.
  - 모니터링 시스템은 이 시점에 알람을 울려 쿠버네티스 HPA(오토스케일러)를 작동시켜야 합니다.
- **`memory.max` (Hard Limit)**:
  - Reclaim을 시도해도 이 선을 넘으면 **즉시 OOM-Killer가 가장 메모리를 많이 먹는 프로세스를 SIGKILL로 사살**합니다.

### 4) 자바 프로세스의 숨겨진 Non-Heap 메모리
자바 개발자가 가장 자주 저지르는 착각은 "JVM 메모리 = `-Xmx`"라고 생각하는 것입니다:
- **JVM Total Memory** =
  - **Heap Memory** (`-Xmx`)
  - **+ Metaspace** (클래스 메타데이터, 기본 무제한)
  - **+ Code Cache** (JIT 컴파일된 네이티브 머신 코드, 240MB+)
  - **+ Thread Stacks** (스레드당 1MB! 스레드 500개면 500MB!)
  - **+ Direct ByteBuffer / Off-Heap** (Netty, gRPC 등 고성능 네트워크 버퍼)
  - **+ JVM C/C++ 내부 메모리** (GC 테이블, 심볼 테이블)
- 따라서 `-Xmx600m`으로 설정했더라도 실제 프로세스의 Resident Set Size(RSS)는 800~900MB에 육박할 수 있습니다!

---

## 3. 실무 쿠버네티스 튜닝 모범 사례

1. **`-XX:+UseContainerSupport`와 `MaxRAMPercentage` 사용**:
   - 고정된 `-Xmx` 대신 JVM이 Cgroup 한도를 자동으로 인식하도록 설정합니다:
     ```bash
     java -XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0 -jar app.jar
     ```
   - 컨테이너 메모리가 1GB라면 75%인 750MB만 힙으로 쓰고, 나머지 250MB를 Non-Heap 및 OS 커널/페이지 캐시 영역으로 안전하게 남겨둡니다.
2. **쿠버네티스 리밋과 리퀘스트의 전략적 구성**:
   - `limits.memory: 1Gi`를 주었다면 JVM 힙은 최대 600~700MB를 넘지 않도록 안전 마진(Safety Margin 30%)을 확보합니다.
3. **대용량 파일 스트리밍 최적화**:
   - 대용량 엑셀 다운로드나 파일 업로드 시 메모리에 통째로 올리지 않고 스트리밍(`InputStream` / 청크 단위)으로 처리하여 Anon 메모리 및 Dirty Page 급증을 억제합니다.
