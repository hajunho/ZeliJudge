# 리눅스 커널 메모리 제어그룹(Cgroup v2) 및 OOM 킬러 메커니즘 이론 (Memcg & OOM Killer Theory)

## 1. Cgroup v1에서 Cgroup v2로의 진화

### 1.1 Cgroup v1의 설계적 결함
리눅스 Cgroup v1(2007년 도입)은 CPU, 메모리, 블록 I/O 등 각 리소스 컨트롤러가 서로 다른 계층 트리(Hierarchy Tree)를 가질 수 있도록 허용했습니다. 이로 인해 다음과 같은 심각한 문제가 발생했습니다:
1. **자원 간 직교성 충돌(Orthogonality Mismatch)**:
   - 메모리 제어그룹의 프로세스가 블록 I/O를 발생시킬 때, 메모리 컨트롤러와 블록 I/O 컨트롤러가 서로 다른 cgroup 경로에 매핑되어 있어 더티 페이지(Dirty Page)의 I/O 비용을 발생 프로세스에 귀속시키지 못하고 커널 플러셔 스레드(`kworker`)가 덤터기를 쓰는 **버퍼드 I/O 쓰기 과금 실패(Writeback Attribution Failure)**가 발생했습니다.
2. **계층적 회수 오버헤드**:
   - 부모-자식 노드 간의 락(Lock) 경합과 복수 트리의 동기화 오버헤드로 인해 고성능 NVMe 및 멀티코어 환경에서 병목이 발생했습니다.

### 1.2 Cgroup v2의 단일 통합 계층(Unified Hierarchy)
커널 4.5부터 메인라인에 안착된 Cgroup v2는 모든 자원 컨트롤러가 단일 공통 디렉터리 트리(`cgroup2` 가상 파일시스템)를 공유하도록 강제했습니다. 이를 통해:
- 파일 쓰기백(Writeback)이 해당 메모리를 점유한 cgroup에 정확히 과금됩니다.
- 프로세스는 트리 내부 노드(Intermediate Node)가 아닌 오직 리프 노드(Leaf Node)에만 존재할 수 있는 **"No Internal Process" 규칙**을 확립하여 제어 예측성을 극대화했습니다.

---

## 2. 4계층 워터마크 보호 및 메모리 회수(Reclaim) 파이프라인

Cgroup v2는 기존 v1의 단순 `limit_in_bytes`를 탈피하여 4단계의 정교한 워터마크를 제공합니다:

```
[ Memory Usage ]
      ^
      |   [ memory.max ]  -----> 하드 상한선 (초과 시 Direct Reclaim -> OOM Killer)
      |
      |   [ memory.high ] -----> 소프트 상한선 (초과 시 스로틀링/지연, OOM Kill 없음)
      |
      |   [ memory.low ]  -----> 소프트 보호 (시스템 압박 시 베스트 에포트 보호)
      |
      |   [ memory.min ]  -----> 하드 보호 (OOM 상황에서도 절대 회수 불가)
      +------------------------------------------------------------>
```

### 2.1 Direct Reclaim 메커니즘
할당 요청이 `memory.max`를 초과할 경우, 커널은 즉시 프로세스 콘텍스트에서 `try_to_free_mem_cgroup_pages()`를 실행합니다.
- **클린 페이지 캐시(`rss_file`)**: 디스크에 이미 동일한 내용이 저장되어 있으므로 즉시 폐기(Drop)할 수 있어 비용이 가장 저렴합니다.
- **더티 페이지 캐시**: 디스크에 플러시한 후 폐기해야 하므로 I/O 지연이 발생합니다.
- **익명 메모리(`rss_anon`)**: 힙/스택 메모리로, 스왑 디바이스가 없는 컨테이너 환경에서는 디스크로 내보낼 수 없어 회수가 불가능합니다.

---

## 3. OOM 킬러와 oom_badness() 휴리스틱 알고리즘

### 3.1 OOM Killer의 목표
OOM Killer(`mm/oom_kill.c`)의 궁극적인 목표는 **"최소한의 프로세스를 종료시켜 가능한 한 최대의 메모리를 즉시 회수하고, 시스템의 필수 서비스를 보존하는 것"**입니다.

### 3.2 Badness 계산 공식과 oom_score_adj의 역할
```c
// Linux kernel mm/oom_kill.c
unsigned long oom_badness(struct task_struct *p, unsigned long totalpages)
{
    if (oom_task_origin(p))
        return ULONG_MAX;

    // oom_score_adj == OOM_SCORE_ADJ_MIN (-1000)
    if (p->signal->oom_score_adj == OOM_SCORE_ADJ_MIN)
        return 0; // Immune from OOM

    // RSS (anon + file) + swap
    points = get_mm_rss(p->mm) + get_mm_counter(p->mm, MM_SWAPENTS);

    // Normalize oom_score_adj to points
    adj = (long)p->signal->oom_score_adj * (long)totalpages / 1000;
    points += adj;

    return points > 0 ? points : 1;
}
```

1. **`oom_score_adj = -1000` (면제)**:
   - `systemd`, `sshd`, 클러스터 오케스트레이터 에이전트(`kubelet`) 등에 설정되어 어떠한 극한의 OOM 상황에서도 생존을 보장받습니다.
2. **`oom_score_adj > 0` (희생양 가중치)**:
   - 비동기 배치 작업, 일회성 데이터 처리 파이프라인 등에 부여하여 메모리를 적게 쓰고 있더라도 우선적으로 희생되도록 유도합니다.
3. **`oom_score_adj < 0` (우선순위 보호)**:
   - 핵심 데이터베이스(PostgreSQL, Redis 등)에 설정하여 메모리 점유율이 높더라도 일반 웹 워커보다 나중에 종료되도록 보호합니다.

### 3.3 Memcg 수준의 격리(Isolation)
전역(Global) OOM 상황에서는 시스템 전체 프로세스 중 최고 배드니스 프로세스를 사살하지만, **Cgroup v2 Memcg OOM**에서는 오직 제한을 위반한 서브트리 내부의 태스크들만 검사하여 처형합니다. 이를 통해 **인접 컨테이너로의 노이지 네이버(Noisy Neighbor) 장애 전파를 완벽히 차단**합니다.
