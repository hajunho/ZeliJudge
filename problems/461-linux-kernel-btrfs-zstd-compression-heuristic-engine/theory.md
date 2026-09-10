# 이론: Linux Kernel Btrfs ZSTD 투명 익스텐트 압축 및 섀넌 엔트로피 휴리스틱 아키텍처

## 1. 파일시스템 투명 압축의 목적과 오버헤드 딜레마

전통적인 파일시스템에서 압축은 사용자가 `tar`나 `gzip`을 통해 파일을 수동으로 아카이빙해야 가능했습니다. 반면 **Btrfs**는 VFS 쓰기 경로(`btrfs_writepage` / `btrfs_run_delalloc_range`)에서 투명하게 블록을 압축하여 디스크에 저장합니다.

이로 인해 두 가지 상충되는 목표(Trade-off)가 발생합니다:
1. **I/O 대역폭 증대**: 텍스트, 데이터베이스 로그, 소스 코드 등의 데이터를 3:1 비율로 압축하면 디스크 쓰기 I/O 양이 66% 감소하여 NVMe/SSD의 쓰기 수명(TBW)과 쓰기 속도가 향상됩니다.
2. **CPU 병목 현상**: ZSTD 압축 레벨을 높일수록 I/O 절감 효과는 커지지만 CPU 코어가 압축 연산에 과도하게 소모되어 시스템 처리량이 급감합니다.

특히 비압축 데이터(동영상, MP3, 압축 아카이브, 암호화 볼륨)에 압축을 시도하는 것은 순수한 CPU 낭비입니다.

---

## 2. 섀넌 엔트로피 기반 비압축 휴리스틱 (`btrfs_compress_heuristic`)

Btrfs는 128KB 익스텐트 청크를 압축 파이프라인으로 넘기기 전에 초경량 샘플링 함수인 `btrfs_compress_heuristic()`(`fs/btrfs/compression.c`)을 실행합니다:

```c
/* Btrfs 휴리스틱 샘플링: 데이터의 정보 엔트로피를 추정 */
int btrfs_compress_heuristic(struct inode *inode, u64 start, u64 end)
{
    /* 샘플 바이트들의 빈도수 버킷 카운팅 */
    /* 반복 패턴이 적고 고유 바이트 분포가 고르면 엔트로피가 8에 가까움 */
    if (entropy > BTRFS_MAX_ENTROPY)
        return 0; /* 압축 불가 판정: 즉시 Raw Extent 기록 */
    return 1; /* 압축 유망 판정: ZSTD 작업 큐로 전달 */
}
```

정보이론(Information Theory)에서 섀넌 엔트로피 $H$는 8비트 바이트 기준으로 $0 \le H \le 8$ 범위를 가집니다:
$$H = -\sum_{i=0}^{255} P(b_i) \log_2 P(b_i)$$
- 완전히 균일한 무작위 난수나 암호화 데이터: $H \approx 8.0$.
- 일반 텍스트나 소스 코드: $H \approx 3.5 \sim 5.0$.
- Btrfs는 휴리스틱 검사를 통해 고비용 압축기(ZSTD 작업 큐)를 거치지 않고도 압축 불가 파일을 나노초 단위로 걸러냅니다.

---

## 3. 최소 1섹터(4KB) 공간 절약 규칙

Btrfs의 온-디스크 블록 할당 단위는 기본 4KB(Sector Size)입니다:
- 128KB(32섹터)의 데이터를 압축한 결과가 126KB라면, 디스크 할당을 위해 4KB로 올림(Round up)해야 하므로 여전히 32섹터(128KB)를 차지합니다.
- 이 경우 디스크 공간 절약은 0바이트인데 반해, 향후 파일을 읽을 때마다 매번 CPU 압축 해제 오버헤드가 발생합니다.
- 따라서 커널은 압축 결과가 최소 1섹터(4KB) 이상 감소하지 않으면(`compressed_sectors >= uncompressed_sectors`), 압축 결과를 즉시 폐기하고 원본 데이터를 기록하는 방어 로직을 수행합니다.

---

## 4. 익스텐트 트리 B-Tree 레이아웃 (`btrfs_file_extent_item`)

Btrfs 서브볼륨 트리(`FS_TREE`)의 익스텐트 레코드는 다음과 같이 압축 메타데이터를 보관합니다:
```c
struct btrfs_file_extent_item {
    __le64 generation;
    __le64 ram_bytes;         /* 원본 비압축 크기 (예: 128KB) */
    __u8 compression;         /* BTRFS_COMPRESS_ZSTD (3) */
    __u8 encryption;
    __le16 other_encoding;
    __u8 type;                /* BTRFS_FILE_EXTENT_REG */
    __le64 disk_bytenr;       /* 디스크 물리 시작 바이트 주소 */
    __le64 disk_num_bytes;    /* 디스크에 할당된 실제 압축 크기 (예: 32KB) */
    __le64 offset;
    __le64 num_bytes;
} __attribute__((packed));
```

읽기 I/O 요청이 들어오면 커널은 `disk_num_bytes`만큼 디스크에서 읽어 ZSTD 작업 메모리(`btrfs_zstd_workspace`)에서 128KB로 복원한 후 페이지 캐시로 주입합니다. 이 정교한 아키텍처 덕분에 사용자는 파일시스템 설정 하나(`mount -o compress=zstd`)로 시스템 성능과 저장 공간을 동시에 극대화할 수 있습니다.
