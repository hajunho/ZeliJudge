# 098. 쿠버네티스 파드에 메모리 1GB 줬는데 왜 자바는 600MB만 쓰다 OOMKilled로 즉사당해요?!: Linux Cgroup v2와 커널 페이지 캐시(Page Cache) & JVM 메모리 오해

---

## 1. 비극의 시작 (Real-World Disaster)

스타트업 클라우드 인프라팀의 은지는 Kubernetes 클러스터에 Spring Boot 결제 및 정산 API 서버를 배포했습니다.  
포드(Pod)의 메모리 리밋은 넉넉하게 1GB(`1Gi = 1024MB`)로 설정했고, 개발팀은 JVM 힙 메모리를 `-Xmx600m`(600MB)으로 지정했습니다:

```yaml
resources:
  requests:
    memory: "512Mi"
  limits:
    memory: "1024Mi"
```
```bash
java -Xmx600m -jar payment-service.jar
```

개발팀은 호언장담했습니다:  
*"우리가 쓸 힙 메모리는 기껏해야 600MB입니다. 1GB 한도에서 무려 424MB나 남아도는데 OOM(Out of Memory)이 날 리가 없죠!"*

하지만 월말 결제 정산일, 수백 MB 규모의 엑셀 거래명세서 파일 다운로드와 대용량 파일 로깅 트래픽이 몰려들자마자 믿을 수 없는 일이 벌어졌습니다.  
서버가 자바 `OutOfMemoryError` 스택트레이스는커녕 **단 한 줄의 에러 로그도 남기지 못한 채 프로세스가 흔적도 없이 증발**해 버린 것입니다!

```bash
$ kubectl describe pod payment-service-7f89d
State:          Terminated
  Reason:       OOMKilled
  Exit Code:    137
```

**"자바 힙 덤프도 없고 에러 로그도 없는데 왜 Exit Code 137로 죽은 거지?! 힙은 600MB도 다 안 썼는데 도대체 누가 죽인 거야?!"**

---

## 2. 10평 원룸과 택배 박스(페이지 캐시)의 비극

이 불가사의한 사망 사건을 1인 가구 원룸에 비유해 봅시다:
- 집주인(리눅스 Cgroup)이 10평 원룸(컨테이너, `memory.max = 1024MB`)을 임대하며 못을 박았습니다:  
  > **"이 방 안의 모든 짐의 총합이 10평을 넘는 순간, 나는 세입자를 쇠지렛대로 기절시킨 뒤 창밖으로 던져버릴 거요(OOM-Killer SIGKILL 137)!"**
- 세입자(JVM 프로세스)는 "내 침대와 책상(JVM Heap, `-Xmx600m`)은 6평밖에 안 되니 4평이나 널널하네!" 하고 입주했습니다.
- 그런데 세입자가 매일 인터넷 쇼핑(파일 다운로드 및 디스크 로그 쓰기)을 즐겼습니다:
  1. 물건을 꺼내고 남은 택배 상자와 뽁뽁이(**페이지 캐시, Page Cache**)가 방구석에 차곡차곡 쌓여 **3.5평(350MB)**을 차지했습니다.
  2. 커널은 "어차피 방에 여유가 있으니 굳이 지금 분리수거장에 안 버려도 되겠지?" 하고 그대로 두었습니다.
  3. 현재 방의 총 짐: 침대(600MB) + 택배 상자(350MB) = **9.5평 (950MB)**!
- **참사의 순간**:
  - 세입자가 작은 간이 매트리스(Non-Heap 또는 순간 추가 할당 100MB)를 들이려 하자, 총 짐이 **10.5평**이 되면서 10평 한도를 뚫어버렸습니다!
  - 커널이 택배 상자를 후다닥 내다 버릴(Page Reclaim) 시간도 없이, 한도를 넘은 것을 본 집주인(Cgroup OOM-Killer)이 몽둥이를 들고 들어와 **세입자의 뒤통수를 가격하여 즉사(SIGKILL / Exit Code 137)**시켜 버린 것입니다!
- 세입자는 "난 600MB밖에 안 썼는데요?!"라고 유언 한마디 남기지 못하고 즉사당했습니다.

---

## 3. 핵심 아키텍처 및 요구사항

당신은 Linux Cgroup v2 메모리 서브시스템, 프로세스 메모리 회계(Anon, File Clean, File Dirty), Direct Page Reclaim, `memory.high` 스로틀링 워터마크, 그리고 한도 초과 시 OOM-Killer(Exit Code 137) 처단 엔진을 시뮬레이션해야 합니다.

### 1) Cgroup 생성 및 한도 설정 (`CONFIG_CGROUP`)
- `CONFIG_CGROUP <cgroup_name> <memory_high_mb> <memory_max_mb>`
  - `<memory_high_mb>`: Cgroup v2 소프트 워터마크. 초과 시 스로틀링 경고.
  - `<memory_max_mb>`: Cgroup v2 하드 리밋. 초과 시 Reclaim 시도 후 OOM-Killer 발동.
  - 출력: `CGROUP_CONFIG_OK name=<cgroup_name> memory_high=<memory_high_mb>MB memory_max=<memory_max_mb>MB`

### 2) 프로세스 생성 (`SPAWN_PROCESS`)
- `SPAWN_PROCESS <cgroup_name> <pid> <name> <heap_limit_mb>`
  - 지정된 Cgroup에 프로세스를 등록합니다.
  - `<heap_limit_mb>`: 프로세스 자체의 힙 한도(JVM `-Xmx`).
  - 초기 메모리: `anon=0, file_clean=0, file_dirty=0, kernel=0`. 상태: `RUNNING`.
  - 출력: `SPAWN_OK pid=<pid> name=<name> cgroup=<cgroup_name>`

### 3) 익명 메모리 할당 (`ALLOC_ANON`)
- `ALLOC_ANON <pid> <amount_mb>`
  - 프로세스의 힙 또는 Non-Heap 메모리를 `<amount_mb>`만큼 할당합니다.
  - **JVM 내부 힙 검사**: `proc.anon_mb + amount > proc.heap_limit_mb`인 경우:
    - Cgroup과 무관하게 JVM 레벨 예외 발생: `ERROR:JAVA_OOM_EXCEPTION pid=<pid> heap_used=<proc.anon_mb>MB limit=<limit>MB`
    - (프로세스는 죽지 않고 메모리만 할당되지 않음)
  - **Cgroup 전체 메모리 검사 (`memory.max`)**:
    - 할당 후 총 메모리: `future_total = cg.memory_current + amount`.
    - 만약 `future_total > cg.memory_max`:
      - **Direct Reclaim 발동**: Cgroup 내 실행 중인 프로세스들의 `file_clean_mb`에서 부족한 양(`needed = future_total - cg.memory_max`)만큼 회수(차감)합니다. (Dirty 페이지는 디스크 동기화 전까지 회수 불가!)
      - Clean 캐시를 최대로 회수한 뒤에도 여전히 `memory_max`를 초과한다면:
        - **OOM-Killer 즉시 발동!**
        - 실행 중인 프로세스 중 `anon_mb`가 가장 큰 프로세스(동률 시 total_memory가 큰 프로세스)가 희생자(Victim)로 선정되어 즉시 사살(`KILLED`)됩니다.
        - 사살된 프로세스의 모든 메모리(`anon, file, kernel`)는 0으로 해제됩니다.
        - 출력: `OOM_KILLER_TRIGGERED cgroup=<cg> memory_current=<curr>MB memory_max=<max>MB victim_pid=<victim.pid> victim_name=<victim.name> exit_code=137`
  - Reclaim을 통해 정상 수용되었거나 애초에 초과하지 않은 경우:
    - 할당 성공: `proc.anon_mb += amount`.
    - 만약 현재 메모리가 `memory_high`를 초과했다면:  
      `ALLOC_ANON_OK pid=<pid> anon=<anon>MB memory_current=<curr>MB [THROTTLED_HIGH_WATERMARK limit=<high>MB]`
    - 초과하지 않았다면:  
      `ALLOC_ANON_OK pid=<pid> anon=<anon>MB memory_current=<curr>MB`

### 4) 파일 I/O 및 페이지 캐시 누적 (`FILE_IO`)
- `FILE_IO <pid> <clean_mb> <dirty_mb>`
  - 파일 읽기(`clean_mb`) 및 파일 쓰기(`dirty_mb`)로 인해 커널 페이지 캐시가 증가합니다.
  - `memory_max` 초과 시 동일하게 Direct Reclaim 및 OOM-Killer가 평가됩니다.
  - 성공 시 출력: `FILE_IO_OK pid=<pid> page_cache=<total_file>MB clean=<clean>MB dirty=<dirty>MB memory_current=<curr>MB`

### 5) 디스크 동기화 (`SYNC_DISK`)
- `SYNC_DISK <pid>`
  - 프로세스가 보유한 더티 페이지 캐시를 디스크에 플러시하여 클린 페이지 캐시로 전환합니다:  
    `file_clean_mb += file_dirty_mb; file_dirty_mb = 0`
  - 이제 이 캐시는 메모리 부족 시 언제든 커널에 의해 회수(Reclaim)될 수 있습니다!
  - 출력: `SYNC_OK pid=<pid> flushed=<dirty>MB clean_now=<clean>MB`

### 6) 페이지 캐시 강제 드롭 (`DROP_CACHES`)
- `DROP_CACHES <cgroup_name>`
  - Cgroup 내 모든 실행 중인 프로세스의 `file_clean_mb`를 0으로 강제 회수합니다 (`echo 3 > /proc/sys/vm/drop_caches`).
  - 출력: `DROP_CACHES_OK cgroup=<cg> reclaimed=<reclaimed>MB memory_current=<curr>MB`

### 7) 상태 요약 (`STATS`)
- `STATS <cgroup_name>`
  - Cgroup의 현재 메모리 총합, 세부 회계(anon, file, dirty), 한도 및 실행/사살된 프로세스 수를 출력합니다.
  - 출력: `STATS cgroup=<cg> memory_current=<curr>MB (anon=<anon>MB file=<file>MB dirty=<dirty>MB) max=<max>MB high=<high>MB running_procs=<count> killed_procs=<count>`

---

## 4. 실무 권장 아키텍처 및 교훈

1. **`-XX:+UseContainerSupport`와 `MaxRAMPercentage` 필수 적용**:
   - 컨테이너 환경에서는 고정 `-Xmx` 대신 JVM이 Cgroup `memory.max`를 자동 감지하도록 설정해야 합니다:
     ```bash
     java -XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0 -jar app.jar
     ```
   - 1GB 컨테이너라면 750MB만 힙으로 사용하고, 나머지 250MB를 커널 페이지 캐시와 Non-Heap 메모리를 위한 안전 마진으로 남겨둡니다.
2. **Cgroup v2 `memory.high` 워터마크 모니터링**:
   - 프로메테우스와 데이터독에서 `container_memory_high_events`를 모니터링하여, OOMKilled가 터지기 전 선제적으로 Pod을 오토스케일링(HPA)합니다.
3. **대용량 파일 I/O 스트리밍 처리**:
   - 엑셀 다운로드나 대용량 로그 생성 시 청크 단위 스트리밍을 사용하여 메모리 및 더티 페이지 캐시의 폭증을 사전에 차단해야 합니다.
