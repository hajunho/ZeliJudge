# 리눅스 커널 BPF LSM 보안 아키텍처와 런타임 침해 방어 (Linux Kernel BPF LSM Security Architecture & Runtime Defense)

## 1. LSM(Linux Security Module)과 eBPF의 융합 (Linux 5.7+)

리눅스 커널의 보안 모듈 프레임워크(LSM)는 2000년대 초반 NSA의 SELinux, Canonical의 AppArmor, 그리고 Smack 등을 지원하기 위해 설계된 커널 내부 인터페이스입니다. 전통적인 LSM 모듈은 커널 모듈 형태로 빌드되어 정책 수정 시 커널 재컴파일이나 복잡한 정책 언어 컴파일이 필요했습니다.

2020년 리눅스 5.7에서 머지된 **BPF LSM**은 `CONFIG_BPF_LSM=y` 커널 설정을 통해 eBPF 프로그램을 모든 주요 LSM 훅 포인트에 직접 연결할 수 있도록 지원합니다:
- **Zero-Copy In-Kernel Evaluation**: 시스템 콜이 하드웨어 I/O나 VFS 레이어에 도달하기 전 커널 메모리 상에서 직접 BTF 기반 구조체 인스펙션 수행.
- **Atomic Enforcement**: 음수 errno(`-EPERM`, `-EACCES`) 반환 시 커널이 즉시 호출을 중단시키고 유저스페이스에 에러를 반환.
- **Programmable Flexibility**: 런타임에 커널 재부팅 없이 BPF 맵(`BPF_MAP_TYPE_HASH`, `BPF_MAP_TYPE_LPM_TRIE`)을 통해 동적 정책 갱신 가능.

---

## 2. 3대 핵심 LSM 훅 포인트와 보안 위협 매핑

| LSM 훅 | 커널 시스콜 계층 | 주요 방어 대상 위협 |
|---|---|---|
| `bpf_lsm_file_open` | `sys_open`, `sys_openat`, `sys_openat2` | 인가되지 않은 비밀번호 파일(`/etc/shadow`), SSL 개인키, 클라우드 자격증명 열람 차단 |
| `bpf_lsm_bprm_check_security` | `sys_execve`, `sys_execveat` | 취약점(RCE) 악용을 통한 웹 서버 하위 쉘(`/bin/sh`, `/bin/bash`), `nc`, `nmap` 등 공격 도구 실행 차단 |
| `bpf_lsm_socket_connect` | `sys_connect` | 인스턴스 메타데이터(IMDS `169.254.169.254`) SSRF 탈취 및 C2 서버 비콘 아웃바운드 차단 |

---

## 3. 프로세스 계통도(Lineage Tracking)와 컨테이너 탈출 메커니즘

공격자는 종종 직접 악성 명령을 내리지 않고 간접 자식 프로세스를 여러 번 분기(`fork` $\to$ `exec`)하여 추적을 회피합니다:
- BPF LSM 엔진은 `task_struct`의 `real_parent` 포인터를 재귀 순회하여 최상위 조상까지의 계통도를 검사합니다.
- `ancestor_binary_pattern`을 통해 특정 워크로드(예: Java 스프링 서버, Nginx)에서 파생된 모든 하위 프로세스의 행위를 격리 감시합니다.
- 컨테이너 내부 프로세스가 호스트의 `/proc/1/ns/*` 네임스페이스 핸들을 열어 호스트 마운트 네임스페이스로 탈출하려는 행위를 탐지하는 즉시 `KILL_PROCESS`를 발동하여 노드 전체 감염을 원천 차단합니다.
