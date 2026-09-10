# 리눅스 커널 BPF LSM(Linux Security Module): bpf_lsm_file_open / bprm_check_security / socket_connect 훅 기반 런타임 보안 정책 엔진 및 프로세스 계통도(Lineage) 컨테이너 탈출 방어

## 문제 설명

전통적인 클라우드 네이티브 컨테이너 보안 도구(seccomp, ptrace, 사용자 공간 감사 데몬)는 시스템 콜(Syscall) 진입 시점에 개입하거나 지연 감사(Post-incident Audit) 방식으로 동작하여 다음과 같은 치명적인 한계를 가졌습니다:
1. **TOCTOU(Time-of-Check to Time-of-Use) 레이스 컨디션**: 사용자가 포인터 인자(경로명 등)를 시스템 콜 인스펙션 직후 교체하여 감사망을 우회하는 취약점.
2. **높은 오버헤드**: `ptrace` 기반 디버깅 후킹은 컨텍스트 스위칭 비용으로 인해 프로덕션 성능을 최대 30~50% 저하시킴.
3. **사후 약방문식 차단 실패**: 시스템 콜을 이미 실행한 뒤 감사 로그만 남겨, 비밀 키 파일이 이미 유출되거나 리버스 쉘(Reverse Shell)이 생성된 뒤에야 경보가 울리는 문제.

리눅스 커널 5.7+에 도입된 **BPF LSM(Linux Security Module, `BPF_PROG_TYPE_LSM`)**은 커널 내부의 보안 훅(Security Hooks)에 eBPF 프로그램을 직접 부착하여, 시스템 콜이 실제 파일 시스템이나 네트워크 하드웨어에 도달하기 전 **커널 레벨에서 즉각적이고 원자적으로 차단(`-EPERM`, `-EACCES`, `KILL_PROCESS`)**할 수 있는 차세대 런타임 보안 아키텍처(Tetragon, Falco, Datadog CWS의 표준 기반)입니다.

본 문제에서는 컨테이너 런타임 환경에서 BPF LSM의 핵심 3대 보안 훅을 정밀하게 모사하는 **BPF LSM 런타임 보안 정책 엔진**을 구현해야 합니다:

1. **핵심 LSM 훅(LSM Hooks)**:
   - `bpf_lsm_file_open`: 프로세스가 파일 오픈(`open`, `openat`)을 시도할 때 파일 경로(`path`), 접근 플래그(`flags`)를 검사합니다.
     - 주요 방어: `/etc/shadow`, AWS IAM 자격증명(`~/.aws/*`), 쿠버네티스 서비스 어카운트 토큰 및 인증서(`/etc/kubernetes/pki/*`) 비인가 열람 차단.
   - `bpf_lsm_bprm_check_security`: 새로운 바이너리 실행(`execve`, `execveat`) 직전 검사합니다.
     - 주요 방어: Nginx, Python, Java 웹 워커 프로세스 하위에서 `/bin/sh`, `/bin/bash`, `nc`를 띄우는 웹쉘 및 RCE 리버스 쉘 실행 차단.
   - `bpf_lsm_socket_connect`: 네트워크 소켓 연결(`connect`) 시 목적지 IP(`dest_ip`)와 포트(`dest_port`)를 검사합니다.
     - 주요 방어: 클라우드 인스턴스 메타데이터 서비스(IMDS, `169.254.169.254/32:80`) 무단 접근(SSRF) 및 C2 서버 비콘 통신 차단.

2. **프로세스 계통도(Lineage Tracking)와 컨테이너 탈출 방어**:
   - 프로세스의 부모(`ppid`)를 루트(PID 1)까지 역추적하여 조상 프로세스 목록(`ancestor_binaries`)을 구성합니다.
   - 자식 프로세스가 아무리 심층 트리(Deep Lineage, e.g. `java -> bash -> python -> xmrig`)에서 실행되더라도 조상 체인에 금지된 바이너리가 존재하면 즉시 차단합니다.
   - 컨테이너 격리 프로세스가 호스트 마운트 네임스페이스(`/proc/*/ns/mnt`, `/proc/*/ns/*`) 접근을 시도할 경우 프로세스를 강제 사살(`KILL_PROCESS`)하여 컨테이너 탈출을 차단합니다.

3. **정책 액션 및 프로세스 수명 주기 제어**:
   - `ALLOW`: 작업 승인 (반환 코드 `0`).
   - `AUDIT`: 작업 승인 및 감사 로그 기록 (반환 코드 `0`).
   - `BLOCK_EPERM`: 작업 거부 (반환 코드 `-1`, `-EPERM`).
   - `BLOCK_EACCES`: 접근 권한 거부 (반환 코드 `-13`, `-EACCES`).
   - `KILL_PROCESS`: 작업 거부 및 프로세스 즉시 사살 (반환 코드 `-1`). 사살된 PID가 이후 시도하는 모든 이벤트는 커널에서 프로세스 부재(`DROPPED_PROCESS_TERMINATED`, 반환 코드 `-3`, `-ESRCH`)로 즉각 드롭됩니다.
   - `bprm_check_security` 성공 시 프로세스의 바이너리 경로(`binary_path`) 및 실행명(`comm`)이 새 실행 파일로 갱신됩니다.

---

## 입력 형식

표준 입력(`sys.stdin`)을 통해 단일 JSON 객체가 전달됩니다:

```json
{
  "policies": [
    {
      "policy_id": "block_shadow_access",
      "hook": "bpf_lsm_file_open",
      "match": {
        "cgroup_pattern": "k8s-pod-*",
        "target_path_pattern": "/etc/shadow*",
        "flags": ["O_RDONLY", "O_RDWR"]
      },
      "action": "BLOCK_EACCES",
      "severity": "CRITICAL"
    }
  ],
  "processes": {
    "100": {
      "comm": "web",
      "binary_path": "/app/web",
      "ppid": 1,
      "cgroup": "k8s-pod-frontend",
      "uid": 1000,
      "gid": 1000
    }
  },
  "events": [
    {
      "event_id": "ev1",
      "pid": 100,
      "hook": "bpf_lsm_file_open",
      "details": {
        "path": "/etc/shadow",
        "flags": ["O_RDONLY"]
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 compact한 단일 행 JSON 문자열을 출력합니다:

```json
{
  "total_events_evaluated": 1,
  "statistics": {
    "allowed": 0,
    "audited": 0,
    "blocked": 1,
    "killed": 0,
    "terminated_pids": []
  },
  "evaluated_events": [
    {
      "event_id": "ev1",
      "pid": 100,
      "hook": "bpf_lsm_file_open",
      "verdict": "BLOCKED",
      "ret_code": -13,
      "matched_policy_id": "block_shadow_access",
      "action": "BLOCK_EACCES",
      "severity": "CRITICAL"
    }
  ]
}
```
