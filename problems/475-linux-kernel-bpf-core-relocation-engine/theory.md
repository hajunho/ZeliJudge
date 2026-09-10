# 리눅스 커널 eBPF CO-RE(Compile Once – Run Everywhere) 아키텍처 이론

## 1. 커널 내부 구조체 다형성과 컴파일 의존성 문제

리눅스 커널은 안정적인 C 라이브러리 ABI와 달리 **내부 구조체 레이아웃에 대한 안정성을 보장하지 않습니다**:
- `task_struct`, `sk_buff`, `struct page` 등 핵심 구조체는 커널 버전뿐만 아니라 컴파일 시점의 `.config` 옵션(`CONFIG_SMP`, `CONFIG_AUDIT`, `CONFIG_MEMCG` 등)에 따라 필드 오프셋, 패딩, 심지어 멤버 존재 여부가 완전히 달라집니다.
- 과거 eBPF 도구(BCC)는 이를 극복하기 위해 타깃 호스트에서 Clang JIT 컴파일을 강제했으나, 100MB+ 툴체인 용량 및 수 초의 빌드 지연으로 인해 대규모 클러스터 배포가 불가능했습니다.

---

## 2. BTF(BPF Type Format)와 CO-RE 재배치 메커니즘

Linux 5.2에서 도입된 **CO-RE(Compile Once – Run Everywhere)**는 다음과 같은 3대 기술적 축으로 완성됩니다:
1. **vmlinux.h**:
   - `bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h`를 통해 단일 헤더에 모든 커널 타입을 생성.
2. **Clang 컴파일러 내장 함수 (`__builtin_preserve_access_index`)**:
   - 코드 작성 시 `BPF_CORE_READ(task, pid)` 매크로를 사용하면, Clang은 하드코딩된 오프셋 대신 `.BTF.ext` ELF 섹션에 '접근 경로(Access String, 예: `0:2:1`)'와 재배치 레코드를 기록합니다.
3. **libbpf 재배치 엔진 (`tools/lib/bpf/relo_core.c`)**:
   - 타깃 커널의 `/sys/kernel/btf/vmlinux`와 로컬 `.BTF.ext`를 비교.
   - 접근 경로의 필드 이름을 타깃 BTF에서 조회하여 새로운 오프셋 $\Delta$를 계산하고, 로드 전 eBPF 바이트코드 명령어를 인플레이스(In-Place)로 직접 수정(Patch)합니다.

---

## 3. 필드 존재성 검사와 Dead Code 제거

커널 버전 간 호환성을 유지하기 위해 eBPF 프로그램은 다음과 같이 작성됩니다:
```c
if (bpf_core_field_exists(task->flags)) {
    val = BPF_CORE_READ(task, flags);
} else {
    val = BPF_CORE_READ(task, old_flags);
}
```
CO-RE 엔진은 타깃 커널에 `flags`가 없으면 해당 `MOV` 명령어를 `0`으로 패칭하고, 커널 eBPF 검증기(Verifier)는 죽은 코드(Dead Code) 분기를 자동으로 가지치기(Prune)하여 어떤 커널 버전에서도 안전하고 크래시 없는 실행을 보장합니다.
이 기술은 Datadog, Cilium, Katran, Sysdig 등 전 세계 최첨단 클라우드 네이티브 관측성/보안 플랫폼의 핵심 기반 기술입니다.
