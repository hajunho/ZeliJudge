# Linux Kernel Landlock LSM: 비특권 프로세스 샌드박싱과 VFS 보안 아키텍처 심층 분석

## 1. 리눅스 보안 모델의 한계와 Landlock의 탄생

전통적인 유닉스 보안 모델은 **재량적 접근 통제(DAC, Discretionary Access Control)**에 기초합니다.
파일 소유자(UID), 그룹(GID), 권한 비트(`rwxrwxrwx`)를 기반으로 권한을 검사하지만, 악성 코드나 취약점이 발생한 프로세스는 해당 유저가 접근할 수 있는 모든 파일(`~/.ssh`, `~/.bashrc`, `/tmp` 등)을 무제한으로 탈취하거나 조작할 수 있었습니다.

이를 극복하기 위해 등장한 **강제 접근 통제(MAC, Mandatory Access Control)** 시스템들:
- **SELinux(Security-Enhanced Linux)**: 극도로 정밀한 보안 컨텍스트 라벨링을 지원하지만, 수천 줄의 정책 언어를 작성해야 하며 root 권한이 필요합니다.
- **AppArmor**: 파일 경로 기반으로 관리가 비교적 단순하지만, 여전히 시스템 전역 정책으로 관리자만이 프로파일을 등록할 수 있습니다.
- **seccomp-bpf**: 시스템 콜 필터링을 제공하지만, 포인터 인자(파일 경로 문자열)를 역참조하여 검증하는 것은 ToCToU(Time-of-Check to Time-of-Use) 경쟁 상태 취약점 때문에 불가능합니다.

이러한 한계를 깨고 2021년 리눅스 5.13에 공식 통합된 것이 바로 **Mickaël Salaün**이 개발한 **Landlock LSM**입니다:
> *"애플리케이션 개발자가 root의 도움 없이, 자신의 프로세스에 필요한 최소한의 파일시스템 경로와 권한만을 스스로 잠글 수 있는 프로그래밍 가능한 인프로세스 샌드박스."*

---

## 2. Landlock의 핵심 3대 시스템 콜

Landlock은 단 3개의 가볍고 강력한 시스템 콜로 구동됩니다:

1. `landlock_create_ruleset(attr, size, flags)`:
   - 다루고자 하는 파일시스템 접근 권한의 집합(`handled_access_fs`)을 선언하고, 룰셋 파일 디스크립터(FD)를 생성합니다.
2. `landlock_add_rule(ruleset_fd, rule_type, rule_attr, flags)`:
   - 특정 디렉터리/파일의 파일 디스크립터(`LANDLOCK_RULE_PATH_BENEATH`)에 허용할 접근 권한 마스크(`allowed_access_fs`)를 추가합니다.
3. `landlock_restrict_self(ruleset_fd, flags)`:
   - 프로세스를 해당 룰셋의 도메인(Domain)으로 격리합니다.
   - 보안상 필수적으로 `prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)`이 먼저 활성화되어 있어야 합니다. (setuid 바이너리 실행을 통한 권한 상승 차단)

---

## 3. 계층적 스택 상속과 VFS 경로 순회 메커니즘

### 계층적 도메인 스택 (Domain Stacking)
Landlock은 일방향 권한 축소(Monotonic Privilege Reduction) 원칙을 고수합니다:
- 프로세스가 룰셋 A로 자신을 제한한 뒤, 추가로 룰셋 B를 적용하면 두 룰셋은 스택에 차례로 쌓입니다: `Domain = [Layer_A, Layer_B]`.
- 이후 발생하는 모든 파일 I/O는 **Layer A와 Layer B 모두에서 승인**되어야 합니다:
  $$	ext{EffectiveAccess} = 	ext{Access}(Layer_A) \cap 	ext{Access}(Layer_B)$$
- 한 번 제한된 권한은 프로세스가 종료될 때까지 결코 되돌리거나 완화할 수 없습니다.
- `fork()`로 생성된 자식 프로세스는 부모의 도메인 스택을 복제 상속받아 자동으로 샌드박스 안에 갇힙니다.

### VFS Closest Ancestor Resolution
파일 시스템 트리에서 특정 파일 `/a/b/c/file.txt`에 접근할 때:
1. Landlock은 dentry 트리를 타고 역순으로 올라갑니다:
   $$	ext{file.txt} 	o 	ext{c} 	o 	ext{b} 	o 	ext{a} 	o /$$
2. 해당 룰셋에 명시적으로 등록된 **가장 가까운 조상 디렉터리(Closest Ancestor Inode)**의 마스크가 그 하위 트리 전체의 접근 정책을 결정합니다.
3. 만약 `/a`에는 `READ_FILE`만 허용되고 `/a/b`에는 `READ_FILE | WRITE_FILE`이 허용되어 있다면, `/a/b/c/file.txt`는 가장 가까운 조상인 `/a/b`의 정책을 적용받아 쓰기가 허용됩니다.

---

## 4. 실무 적용 및 컨테이너 보안

Landlock은 오늘날 최신 리눅스 애플리케이션 보안의 핵심 기둥으로 자리잡았습니다:
- **웹 브라우저 (Chromium, Firefox)**: 렌더러 프로세스가 오직 폰트 파일과 캐시 디렉터리만 읽을 수 있도록 비특권 샌드박싱.
- **CLI 유틸리티 (Git, ImageMagick, PDF 파서)**: untrusted 입력을 처리하기 직전, 작업 디렉터리 외의 시스템 전역 쓰기 권한을 원천 차단하여 공급망 공격 및 RCE 무력화.
- **마이크로서비스 & 컨테이너**: 루트 권한 없이도 프로세스 단위의 미세 격리(Micro-Segmentation)를 구현.
