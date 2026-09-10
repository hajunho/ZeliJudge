# Theory: Linux Kernel Block Layer blk-throttle & Cgroup I/O Quality of Service (`block/blk-throttle.c`)

## 1. 블록 레이어 I/O 스로틀링과 Cgroup v2 `io.max`

리눅스 블록 레이어(`block/`)는 파일시스템(VFS/ext4/btrfs/xfs)과 블록 디바이스 드라이버(NVMe, virtio-blk, SCSI) 사이에 위치하여 모든 물리적 저장장치 접근(`struct bio`)을 중재합니다.
- Cgroup v2에서는 `/sys/fs/cgroup/<group>/io.max` 파일을 통해 특정 메이저:마이너 번호의 블록 디바이스에 대해 BPS(초당 바이트 수) 및 IOPS(초당 입출력 횟수)의 절대 상한을 설정할 수 있습니다.
- 커널 내부에서는 `block/blk-throttle.c`의 **blk-throttle** 계층이 `submit_bio()` 진입 시점에 개입하여 요청 속도를 조절합니다.

---

## 2. 슬라이스 기반 리키 버킷 (Sliced Leaky Bucket) 알고리즘

전통적인 토큰 버킷은 나노초 단위로 토큰을 미세 누적하므로 타이머 인터럽트 오버헤드가 극심합니다. 리눅스 커널은 이를 최적화하여 **시간 슬라이스 윈도우(Time Slice Window / 100ms)** 방식을 사용합니다:

### 2.1 슬라이스 예산 할당
$$\text{slice\_window} = 100\text{ms}$$
$$\text{budget\_bytes} = \lceil \text{bps} \times 0.1 \rceil$$
$$\text{budget\_iops} = \lceil \text{iops} \times 0.1 \rceil$$

- 슬라이스 시작 시점(`slice_start`)부터 $100\text{ms}$ 동안 요청된 바이트 누적치(`bytes_disp`)와 요청 횟수(`io_disp`)를 추적합니다.
- 슬라이스 내에서 가용 예산이 남아있으면 즉각 하위 드라이버 디스패치 큐로 바이패스합니다.

### 2.2 스로틀링 큐잉 및 지연 디스패치 (`throtl_service_queue`)
- 예산이 고갈된 bio는 즉시 실행되지 못하고 Cgroup의 서비스 큐(`sq->queued[rw]`)에 삽입됩니다.
- 커널은 다음 슬라이스 시작 시점(`slice_end`)에 맞춰 고해상도 타이머(`hrtimer`) 또는 지연 워크큐(`delayed_work`)를 가동합니다.
- 타이머 만료 시 `throtl_dispatch_work`가 깨어나 슬라이스 윈도우를 갱신하고 대기 중인 bio를 하위 디바이스 큐로 방출합니다.

---

## 3. 방향 분리 (Read/Write Separation)와 공정성

- **비동기 쓰기 대 동기 읽기**: 읽기는 프로세스가 블로킹되어 대기하는 동기식 I/O인 반면, 쓰기는 페이지 캐시 플러시 스레드(`kworker/flush`)에 의해 백그라운드로 처리되는 경우가 많습니다.
- blk-throttle은 읽기와 쓰기의 BPS/IOPS 제한을 완벽히 분리(`rbps`, `wbps`, `riops`, `wiops`)하여 대규모 쓰기 플러시가 진행 중일 때도 대화형 읽기 요청이 부당하게 지연되는 현상을 원천 방어합니다.
