# 121. 42KB짜리 압축 파일 하나 풀었을 뿐인데 왜 디스크 1TB가 꽉 차서 서버가 뻗어요?!: 압축 폭탄(Zip Bomb / 42.zip)과 Zip Slip(경로 순회) 방어

## 문제 설명

웹 서비스에 사용자가 엑셀 파일이나 영수증 증빙 서류를 업로드할 수 있도록 압축 파일(`.zip`) 업로드 및 압축 해제 기능을 구현했습니다.  
처음에는 `zipfile.extractall()` 함수를 사용하여 간편하게 구현했으나, 어느 날 악의적인 공격자가 올린 파일 때문에 **두 가지 치명적인 보안 재앙**이 발생했습니다:

1. **압축 폭탄 (Zip Bomb / Decompression Bomb)**:  
   업로드된 파일 크기는 고작 **42KB**에 불과했습니다. 그러나 압축을 풀기 시작하자마자 파일 크기가 수백 기가바이트(GB)에서 수 페타바이트(PB)로 폭발적으로 팽창하여, 서버의 전체 디스크 저장 공간이 100% 포화(`No space left on device`)되고 운영체제(OS)가 패닉에 빠져 서버가 다운되었습니다!
2. **Zip Slip (경로 순회 덮어쓰기 공격)**:  
   압축 파일 내부의 파일명이 `../../../../etc/passwd`나 `../../app/server.py`로 조작되어 있어, 압축을 푸는 순간 상위 디렉터리로 탈출하여 서버의 핵심 실행 코드와 설정 파일을 덮어써 버리고 원격 코드 실행(RCE) 백도어가 열렸습니다!

---

### 왜 이런 일이 가능할까? (DEFLATE 알고리즘의 맹점)

ZIP의 표준 압축 알고리즘인 **DEFLATE(LZ77 + 허프만 코딩)**는 반복되는 데이터를 압축하는 데 극단적으로 특화되어 있습니다.  
예를 들어 `0`이 10억 개 연속으로 적힌 1GB 파일은 "0이 10억 번 반복됨"이라는 메타데이터 단 몇 바이트로 압축되어 수 KB짜리 파일이 됩니다. (압축 비율 1,000,000 : 1 달성)  
따라서 단순한 파일 업로드 크기 검사(`len(file) < 10MB`)로는 압축 폭탄을 **절대 감지하거나 막을 수 없습니다!**

---

### 안전한 압축 해제기 (Secure Decompressor)의 5대 방어선

1. **최대 누적 해제 용량 제한 (`max_uncompressed_mb`)**:  
   압축을 푸는 도중 총 풀린 바이트 수가 한도를 넘어서면 즉시 작업을 중단하고 프로세스를 보호합니다.
2. **비정상 압축 비율 차단 (`max_ratio = uncompressed_size / compressed_size`)**:  
   개별 파일의 압축 해제 비율이 비정상적으로 높으면(예: 100:1 초과) 압축 폭탄으로 간주하고 즉각 거부합니다.
3. **최대 파일 개수 제한 (`max_file_count`)**:  
   아카이브 내 파일 개수가 한도를 초과하면 inode 고갈 공격을 방지하기 위해 차단합니다.
4. **재귀 중첩 깊이 제한 (`max_depth`)**:  
   `42.zip`처럼 ZIP 안에 ZIP이 5~6단계로 중첩되어 기하급수적으로 폭발하는 재귀 구조를 최대 깊이(기본 2단계)에서 차단합니다.
5. **Zip Slip 경로 검증**:  
   파일명에 `..`이나 절대 경로(`/`, `\`)가 포함되어 지정된 대상 디렉터리를 벗어나는 경로 탈출을 원천 차단합니다.

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG max_uncompressed_mb=<int> max_ratio=<int> max_file_count=<int> max_depth=<int>`
   - 안전 검사 임계값을 설정합니다.
   - 출력: `OK max_uncompressed_mb=<mb> max_ratio=<ratio> max_file_count=<count> max_depth=<depth>`

2. `DECOMPRESS archive=<name> compressed_bytes=<int> depth=<int> entries=<json_list>`
   - `entries`는 아카이브 내부 파일들의 메타데이터 JSON 목록입니다:  
     `[{"name": "file.txt", "size": 1000, "csize": 500, "is_zip": false}, ...]`
   - 중첩 ZIP의 경우 `is_zip=true` 및 `sub_entries=[...]`를 포함할 수 있습니다.
   - **검사 실패 시 출력 형식**:
     - 재귀 깊이 초과: `ERROR archive=<name> status=REJECTED error=ZIP_BOMB_DETECTED reason=MAX_DEPTH_EXCEEDED depth=<depth>`
     - 파일 개수 초과: `ERROR archive=<name> status=REJECTED error=ZIP_BOMB_DETECTED reason=MAX_FILE_COUNT_EXCEEDED count=<count>`
     - Zip Slip 탐지: `ERROR archive=<name> status=REJECTED error=ZIP_SLIP_DETECTED filename=<filename>`
     - 비정상 압축 비율: `ERROR archive=<name> status=REJECTED error=ZIP_BOMB_DETECTED reason=EXCESSIVE_RATIO ratio=<ratio:.1f> limit=<limit>`
     - 최대 누적 용량 초과: `ERROR archive=<name> status=REJECTED error=ZIP_BOMB_DETECTED reason=MAX_SIZE_EXCEEDED total_mb=<mb:.1f> limit_mb=<limit>`
   - **모든 검사 통과 시 출력 형식**:  
     `SUCCESS archive=<name> status=EXTRACTED files=<count> total_bytes=<bytes> compression_ratio=<ratio:.1f>`

3. `STATS`
   - 통계 출력:  
     `STATS processed=<P> extracted=<E> rejected_zip_bomb=<B> rejected_zip_slip=<S>`

4. `RESET`
   - 모든 설정을 초기 기본값으로 복귀합니다:  
     `OK max_uncompressed_mb=100 max_ratio=100 max_file_count=1000 max_depth=2`

---

## 예제 입력 1 (정상 아카이브 & 비정상 압축 비율 폭탄)

```text
CONFIG max_uncompressed_mb=100 max_ratio=100 max_file_count=1000 max_depth=2
DECOMPRESS archive=clean_docs.zip compressed_bytes=10000 depth=1 entries=[{"name": "doc1.txt", "size": 8000, "csize": 3000, "is_zip": false}, {"name": "doc2.txt", "size": 12000, "csize": 5000, "is_zip": false}]
DECOMPRESS archive=bomb_ratio.zip compressed_bytes=200 depth=1 entries=[{"name": "zeros.bin", "size": 1000000, "csize": 100, "is_zip": false}]
STATS
```

## 예제 출력 1

```text
OK max_uncompressed_mb=100 max_ratio=100 max_file_count=1000 max_depth=2
SUCCESS archive=clean_docs.zip status=EXTRACTED files=2 total_bytes=20000 compression_ratio=2.0
ERROR archive=bomb_ratio.zip status=REJECTED error=ZIP_BOMB_DETECTED reason=EXCESSIVE_RATIO ratio=10000.0 limit=100
STATS processed=2 extracted=1 rejected_zip_bomb=1 rejected_zip_slip=0
```

---

## 예제 입력 2 (Zip Slip 경로 탈출 공격 탐지)

```text
CONFIG max_uncompressed_mb=100 max_ratio=100 max_file_count=1000 max_depth=2
DECOMPRESS archive=evil_traversal.zip compressed_bytes=500 depth=1 entries=[{"name": "safe.txt", "size": 100, "csize": 50, "is_zip": false}, {"name": "../../../../etc/shadow", "size": 500, "csize": 200, "is_zip": false}]
STATS
```

## 예제 출력 2

```text
OK max_uncompressed_mb=100 max_ratio=100 max_file_count=1000 max_depth=2
ERROR archive=evil_traversal.zip status=REJECTED error=ZIP_SLIP_DETECTED filename=../../../../etc/shadow
STATS processed=1 extracted=0 rejected_zip_bomb=0 rejected_zip_slip=1
```\n