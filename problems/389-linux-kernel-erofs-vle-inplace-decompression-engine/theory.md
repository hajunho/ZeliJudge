# Theory: Linux Kernel EROFS Flash-Friendly Compressed Read-Only File System (`fs/erofs/`)

## 1. 읽기 전용 압축 파일시스템의 진화와 Fixed-Output 패러다임

전통적인 임베디드 및 라이브 시스템은 주로 **SquashFS**를 활용했습니다. 그러나 SquashFS는 다음과 같은 근본적 한계를 지녔습니다:

### 1.1 SquashFS (Fixed-Input)의 읽기 증폭과 메모리 낭비
- SquashFS는 고정 크기(예: 128KB)의 입력 데이터를 압축하여 가변 크기 블록으로 디스크에 저장합니다.
- 사용자가 4KB 페이지만 읽으려 해도 128KB 전체 블록을 디스크에서 읽어 메모리에 버퍼링한 뒤 압축을 풀어야 합니다 (**극심한 읽기 증폭 및 CPU/메모리 대역폭 낭비**).

### 1.2 EROFS의 Fixed-Output 혁신
Huawei의 Gao Xiang 등이 제안하고 리눅스 5.4에 도입된 EROFS는 정반대의 **고정 출력(Fixed-Output)** 접근법을 채택했습니다:
- 비압축 데이터의 크기를 정확히 4KB(또는 $N \times 4\text{KB}$) 단위로 고정하고, 이에 대응하는 압축된 물리 블록(가변 크기 $\le 4\text{KB}$)을 플래시 디바이스에 배치합니다.
- 4KB 페이지 단위 임의 읽기(Random Read) 시 오직 필요한 해당 물리 클러스터만 읽어와 즉각 디코딩하므로 읽기 증폭이 완벽히 $O(1)$로 제한됩니다.

---

## 2. 인플레이스 압축 해제 (In-Place Decompression / IPD)

EROFS 성능의 핵심은 메모리 복사 및 동적 할당을 제거하는 **IPD(In-Place Decompression)** 기술입니다:

```
[ Compressed Cluster on Disk (csize <= 4096 B) ]
                    |
      (DMA directly into Page Cache frame)
                    v
+---------------------------------------------------+
| [ Compressed Bytes (csize) ] |  [ Available Room ] |  Page Cache Frame (4096 B)
+---------------------------------------------------+
                    |
      (In-Place Decompression in backward order)
                    v
+---------------------------------------------------+
|       [ Fully Decompressed 4096 B Page Data ]      |  Same Page Frame!
+---------------------------------------------------+
```

- LZ4 등 고속 스트림 압축 알고리즘의 역방향 슬라이딩 윈도우 특성을 이용하여, 임시 바운스 버퍼(Bounce Buffer)를 할당하지 않고도 단일 4KB 페이지 캐시 프레임 내부에서 제자리 디코딩을 완료합니다.
- 시스템 메모리가 부족한 스마트폰이나 고밀도 서버리스 컨테이너 환경에서 메모리 압박(Direct Reclaim)을 0으로 억제합니다.

---

## 3. VLE 익스텐트와 초경량 아이노드 구조

- **Compact Inode (32 바이트)**:
  - 4GB 이하 파일의 메타데이터 크기를 32바이트로 압축하여, 파일 수만 개가 존재하는 Android `/system` 파티션의 메타데이터 메모리 점유율을 50% 이상 절감합니다.
- **Extended Inode (64 바이트)**:
  - 64비트 파일 크기, 나노초 정밀도 타임스탬프, SELinux/POSIX 확장 속성(xattr)을 지원합니다.
