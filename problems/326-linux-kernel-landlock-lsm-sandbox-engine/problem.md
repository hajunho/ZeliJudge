# Linux Kernel Landlock LSM: 비특권 프로세스 샌드박싱, 계층적 룰셋 상속 및 VFS 경로 순회 검증 엔진

## 문제 설명

리눅스 커널 5.13에 머지된 **Landlock LSM(Linux Security Module, `security/landlock/`)**은 현대 리눅스 보안 아키텍처의 기념비적인 진보입니다.

기존의 전통적인 강제 접근 통제(MAC) 시스템인 SELinux나 AppArmor는 시스템 관리자(root)만이 보안 정책을 작성하고 배포할 수 있었습니다. 따라서 웹 브라우저 탭, 렌더러 프로세스, 샌드박스 파서와 같은 일반 애플리케이션 프로세스는 루트 권한 없이 스스로의 권한을 축소(Principle of Least Privilege)할 수 있는 표준적이고 안전한 수단이 부재했습니다.

Landlock은 일반 비특권 프로세스가 직접 커널 시스콜(`landlock_create_ruleset`, `landlock_add_rule`, `landlock_restrict_self`)을 호출하여 자신과 자식 프로세스들을 가두는 경량 격리 샌드박스(Sandbox Domain)를 구축할 수 있게 합니다.

Landlock의 핵심 아키텍처 원칙은 다음과 같습니다:
1. **계층적 룰셋 스택(Stacked Ruleset Hierarchy)**:
   - 프로세스가 `landlock_restrict_self()`를 호출할 때마다 새로운 룰셋 계층이 도메인 스택에 누적(Stack)됩니다.
   - 프로세스가 `fork()`를 수행하면 자식 프로세스는 부모의 모든 룰셋 계층을 그대로 상속받으며, 자식 프로세스는 추가적인 룰셋을 스택에 더 얹어 자신의 권한을 더욱 엄격하게 제한할 수 있습니다. (권한 확대는 불가능하며 오직 교집합으로 축소만 가능)
2. **VFS 경로 순회 및 가장 가까운 조상 탐색(Closest Ancestor Inode Resolution)**:
   - 특정 파일(예: `/var/log/nginx/access.log`)에 대한 접근 요청 시, 커널은 해당 파일부터 부모 디렉터리 경로를 역순으로 순회(`/var/log/nginx` -> `/var/log` -> `/var` -> `/`)하면서 해당 룰셋에 등록된 **가장 가까운 조상 경로(Closest Ancestor)**의 허용 권한 마스크를 적용합니다.
3. **다중 계층 교집합 검증(Cross-Layer Intersection Enforcement)**:
   - 프로세스가 여러 개의 룰셋 계층을 중첩하여 가지고 있는 경우, **모든 계층(All Layers)**에서 요청된 권한이 각각 독립적으로 허용되어야만 최종적으로 파일 접근이 승인(`allowed = True`)됩니다. 어느 한 계층이라도 거부하면 `-EACCES` 에러를 반환합니다.
4. **핸들링 권한 마스크(Handled Access Mask)**:
   - 각 룰셋은 자신이 통제하고자 지정한 권한들(`handled_access_fs`)만을 감시합니다. 룰셋이 핸들링 대상으로 지정하지 않은 권한은 해당 룰셋에서 제약 없이 통과됩니다.

본 문제에서는 리눅스 커널 `security/landlock/ruleset.c` 및 `security/landlock/fs.c`에 구현된 Landlock LSM의 룰셋 생성, 룰 추가, 자가 격리(`RESTRICT_SELF`), 프로세스 복제(`FORK`), 그리고 VFS 경로 역순회 조상 탐색 및 다중 계층 교집합 접근 통제 검증 엔진을 구현합니다.

---

## 아키텍처 및 내부 메커니즘

```
                     [ 프로세스 태스크 구조체: task_struct ]
                                       │
                      Landlock 보안 컨텍스트 (Domain Stack)
                                       │
                ┌──────────────────────┴──────────────────────┐
                │                                             │
      [ 계층 1: Layer 0 (부모) ]                    [ 계층 2: Layer 1 (자식) ]
      - handled: READ_FILE, WRITE_FILE              - handled: WRITE_FILE
      - rules:                                      - rules:
        /var     -> READ_FILE                         /var/tmp -> WRITE_FILE
        /var/tmp -> READ_FILE, WRITE_FILE
                │                                             │
                └──────────────────────┬──────────────────────┘
                                       │
                   파일 접근 요청: open("/var/tmp/data.log", O_RDWR)
                                       ▼
    ┌────────────────────────────────────────────────────────────────────────┐
    │                      Landlock VFS 경로 검증 루프                       │
    │                                                                        │
    │  1. 대상 파일부터 루트까지 부모 경로 역순회 (Closest Ancestor Match):   │
    │     /var/tmp/data.log -> /var/tmp (Match!)                             │
    │                                                                        │
    │  2. 계층 1 검증:                                                       │
    │     /var/tmp 룰: READ_FILE | WRITE_FILE -> 둘 다 허용 (Pass ✅)         │
    │                                                                        │
    │  3. 계층 2 검증:                                                       │
    │     handled: WRITE_FILE만 통제 (READ_FILE은 미통제 패스)                 │
    │     /var/tmp 룰: WRITE_FILE 허용 (Pass ✅)                             │
    │                                                                        │
    │  4. 최종 판정: 모든 계층 Pass -> 접근 허용 (allowed: true, errno: 0)  │
    └────────────────────────────────────────────────────────────────────────┘
```

### 1. Landlock 파일 시스템 접근 권한 비트마스크

| 권한 이름 | 비트 값 | 설명 |
|---|:---:|---|
| `EXECUTE` | `1 << 0` (1) | 파일 실행 권한 |
| `WRITE_FILE` | `1 << 1` (2) | 파일 내용 쓰기 권한 |
| `READ_FILE` | `1 << 2` (4) | 파일 내용 읽기 권한 |
| `READ_DIR` | `1 << 3` (8) | 디렉터리 목록 열람 권한 |
| `REMOVE_DIR` | `1 << 4` (16) | 디렉터리 삭제 권한 |
| `REMOVE_FILE` | `1 << 5` (32) | 파일 언링크(삭제) 권한 |
| `MAKE_CHAR` | `1 << 6` (64) | 문자 특수 디바이스 생성 |
| `MAKE_DIR` | `1 << 7` (128) | 새 디렉터리 생성 권한 |
| `MAKE_REG` | `1 << 8` (256) | 일반 파일 생성 권한 |
| `MAKE_SOCK` | `1 << 9` (512) | 유닉스 도메인 소켓 파일 생성 |
| `MAKE_FIFO` | `1 << 10` (1024) | FIFO 네임드 파이프 생성 |
| `MAKE_BLOCK` | `1 << 11` (2048) | 블록 디바이스 생성 |
| `MAKE_SYM` | `1 << 12` (4096) | 심볼릭 링크 생성 권한 |
| `REFER` | `1 << 13` (8192) | 다른 디렉터리로 파일 링크/이동 |
| `TRUNCATE` | `1 << 14` (16384) | 파일 크기 변경(ftruncate) 권한 |

### 2. 룰셋 평가 알고리즘

단일 계층 $L$에서 타깃 경로 $P$와 요청 마스크 $M_{req}$에 대한 검증:
1. 해당 계층이 핸들링하는 요청 마스크: $M_{act} = M_{req} \ \& \ L.handled\_access\_fs$
2. 만약 $M_{act} == 0$ 이면, 이 계층은 해당 권한을 통제하지 않으므로 즉시 `True`를 반환합니다.
3. 경로 $P$의 정규화(슬래시 중복 제거, 끝 슬래시 제거)를 수행합니다.
4. $P$에서 시작하여 부모 디렉터리로 한 단계씩 올라가며 $L.rules$에 등록된 경로인지 확인합니다:
   - 만약 일치하는 경로 $C$가 발견되면:
     - $(L.rules[C] \ \& \ M_{act}) == M_{act}$ 이면 `True`, 아니면 `False`를 반환합니다.
   - 루트(`/`)까지 도달했으나 어떤 부모 디렉터리도 $L.rules$에 없다면, 기본 거부 원칙에 의해 `False`를 반환합니다.

다중 계층 도메인 $[L_0, L_1, \dots, L_{k-1}]$을 가진 프로세스의 검증:
- 모든 $0 \le j < k$에 대해 $L_j.check\_access(P, M_{req}) == True$ 이어야만 최종 접근이 허용됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "rulesets": [
      {
        "ruleset_id": "r_base",
        "handled_access_fs": ["READ_FILE", "WRITE_FILE", "EXECUTE", "READ_DIR"],
        "rules": [
          {"path": "/usr/bin", "allowed_access_fs": ["READ_FILE", "EXECUTE"]},
          {"path": "/tmp", "allowed_access_fs": ["READ_FILE", "WRITE_FILE", "READ_DIR"]}
        ]
      }
    ],
    "processes": [
      {"pid": 101, "name": "app_worker", "domain_ruleset_ids": ["r_base"]}
    ]
  },
  "commands": [
    {"type": "CHECK_ACCESS", "pid": 101, "path": "/usr/bin/cat", "access_rights": ["READ_FILE", "EXECUTE"]},
    {"type": "CHECK_ACCESS", "pid": 101, "path": "/etc/passwd", "access_rights": ["READ_FILE"]},
    {"type": "STEP"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 한 줄로 출력합니다:
```json
{"total_steps":1,"stats":{"total_access_requests":2,"access_granted":1,"access_denied":1},"processes":{"101":{"pid":101,"name":"app_worker","domain_layers":["r_base"],"access_logs":[{"path":"/usr/bin/cat","requested_mask":5,"requested_rights":["EXECUTE","READ_FILE"],"allowed":true,"errno":0,"denied_layer_id":null,"layer_checks":[{"ruleset_id":"r_base","handled":["EXECUTE","WRITE_FILE","READ_FILE","READ_DIR"],"granted":true}]},{"path":"/etc/passwd","requested_mask":4,"requested_rights":["READ_FILE"],"allowed":false,"errno":"EACCES","denied_layer_id":"r_base","layer_checks":[{"ruleset_id":"r_base","handled":["EXECUTE","WRITE_FILE","READ_FILE","READ_DIR"],"granted":false}]}]}},"rulesets":{"r_base":{"ruleset_id":"r_base","handled_access":["EXECUTE","WRITE_FILE","READ_FILE","READ_DIR"],"rules":{"/tmp":["WRITE_FILE","READ_FILE","READ_DIR"],"/usr/bin":["EXECUTE","READ_FILE"]}}},"snapshots":[]}
```
