# 리눅스 커널 eBPF CO-RE(Compile Once – Run Everywhere) 및 BTF 릴로케이션 심층 이론

## 1. 레거시 BCC의 한계와 CO-RE의 탄생

전통적인 eBPF 개발 방식(BCC)은 대상 호스트 서버에 거대한 툴체인(Clang, LLVM, gcc, 커널 헤더 소스코드)을 직접 설치하고 런타임에 C 소스코드를 컴파일하여 바이트코드를 생성했습니다.

### BCC의 3대 치명적 문제:
1. **과도한 리소스 소모**: eBPF 데몬 하나를 기동하기 위해 기가바이트 단위의 디스크 공간과 컴파일 시점의 수백 MB 메모리, 수 초 이상의 CPU 스파이크가 발생.
2. **보안 취약성**: 프로덕션 운영 서버에 실시간 C 컴파일러와 빌드 툴체인이 상주하는 것은 심각한 보안 공격 벡터(Attack Surface) 형성.
3. **커널 헤더 의존성**: 리눅스 배포판 커널이 업데이트되거나 패키지 헤더가 누락되면 eBPF 프로그램 실행이 즉시 불가능.

---

## 2. eBPF CO-RE 아키텍처

리눅스 커널 5.2+에서 구글, 페이스북, 레드햇 엔지니어들에 의해 고안된 **CO-RE**는 커널 컴파일 시점에 생성되는 압축된 타입 메타데이터인 **BTF (BPF Type Format)**를 기반으로 동작합니다:

```
[개발자 워크스테이션]
 vmlinux.h (전체 커널 선언) + eBPF C 코드
       |
       v (Clang 컴파일 with -g -O2)
 my_bpf.o (ELF: 바이트코드 + .BTF + .BTF.ext CO-RE 릴로케이션 정보)
       |
       | (네트워크 배포: 단 50KB 바이너리)
       v
[프로덕션 타겟 서버 (커널 버전 무관)]
 /sys/kernel/btf/vmlinux (타겟 시스템 커널 BTF)
       +
 my_bpf.o
       |
       v (libbpf 로더: CO-RE 릴로케이션 엔진)
 [바이트코드 오프셋 실시간 패치: LDX [r2 + 4] -> LDX [r2 + 12]]
       |
       v (bpf() 시스템 콜)
 BPF Verifier 통과 및 JIT 엔진 가동 (0.01초 만에 실행 완료!)
```

---

## 3. BTF 타입 그래프 순회 및 오프셋 계산 원리

BTF는 커널에 존재하는 모든 구조체, 공용체(Union), 포인터, 기본 자료형, 함수 프로토타입을 인덱스화된 그래프 형태로 표현합니다:

```
Type 3 [STRUCT: task_struct]
   |--> Member "parent" (Type 2: PTR) ---> Type 3 [STRUCT: task_struct]
   |--> Member "__sk_common" (Type 5: STRUCT: sock_common)
           |--> Member "skc_dport" (Type 1: INT, Offset: 16)
```

### 오프셋 누적 수식
경로 $P = [m_1, m_2, \dots, m_k]$에 대해:
$$\text{Total\_Offset} = \sum_{j=1}^{k} \text{offset}(m_j)$$
여기서 각 단계 $m_j$가 포인터(`PTR`)인 경우 포인터가 가리키는 타겟 구조체 타입으로 전이하고, 임베디드 구조체인 경우 부모 구조체 기준 오프셋을 직접 합산합니다.

### 비트필드(Bitfield) 처리 메커니즘
C 언어 비트필드는 단일 바이트 또는 4바이트 정수 내부에 여러 플래그가 비트 단위로 쪼개져 저장됩니다:
- `unsigned int ecn_ok:1, cwr_aligned:1, is_mptcp:1;`
- eBPF 로더는 `FIELD_BYTE_OFFSET`으로 저장 컨테이너의 바이트 위치를 찾고, `FIELD_BIT_OFFSET`과 `FIELD_BIT_SIZE`를 추출하여 다음과 같은 마스킹 연산 코드로 변환합니다:
  $$\text{value} = (\text{container} \gg \text{bit\_offset}) \ \& \ ((1 \ll \text{bit\_size}) - 1)$$

CO-RE는 임의의 리눅스 커널 버전 간 ABI(Application Binary Interface) 차이를 런타임에 투명하게 연결해 주는 현대 클라우드 네이티브 관측성(Observability)과 보안 기술의 핵심 심장입니다.
