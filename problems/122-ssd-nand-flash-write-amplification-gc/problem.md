# 122. SSD 믿고 DB 돌렸더니 6개월 만에 SSD가 사망하고 속도가 100배 느려졌어요?!: SSD 낸드 플래시 블록 지우기(Erase-Before-Write)와 쓰기 증폭(Write Amplification Factor, WAF) & 가비지 컬렉션(GC)

## 문제 설명

고성능 데이터베이스 서버를 구축하면서 "SSD는 하드디스크(HDD)처럼 회전하는 모터 암(Arm)이 없으니, 무작위 쓰기(Random Write)를 마구 때려도 항상 초고속이겠지?"라고 안일하게 생각했습니다.  
하지만 무작위 UPDATE가 많은 데이터베이스를 운영한 지 불과 6개월 만에 **두 가지 치명적인 재앙**이 닥쳤습니다:

1. **쓰기 속도 급락**:  
   초당 수만 건을 처리하던 쓰기 속도가 어느 날 갑자기 100배 느려지며 디스크 I/O 대기율(iowait)이 100%로 치솟았습니다.
2. **SSD 조기 사망 (P/E Cycle 소모)**:  
   우리가 디스크에 쓴 실제 데이터양은 10TB에 불과했는데, SSD의 내부 누적 쓰기량(S.M.A.R.T 지표)을 확인해 보니 무려 **50TB**가 쓰여 있었고 플래시 메모리 소자가 수명 한계에 도달해 사망했습니다!

---

### 왜 이런 일이 발생할까? (Erase-Before-Write의 물리적 한계)

SSD에 사용되는 **NAND 플래시 메모리**에는 거스를 수 없는 물리적 비대칭성이 존재합니다:

- **읽기/쓰기(Program) 단위 = 페이지 (Page, 보통 4KB)**:  
  셀에 전자를 주입하여 1을 0으로 만드는 작업은 4KB 단위로 매우 빠르고 정밀하게 수행할 수 있습니다.
- **지우기(Erase) 단위 = 블록 (Block, 128~512개 페이지 = 512KB~4MB)**:  
  셀에서 전자를 빼내어 0을 다시 1로 되돌리려면 수만 볼트의 고전압을 가해야 하므로, 수백 개의 페이지가 묶인 블록 전체를 통째로 지워야만 합니다!
- **Erase-Before-Write (덮어쓰기 불가)**:  
  이미 데이터가 쓰여진 페이지에 덮어쓰기(In-place Overwrite)를 하려면 **반드시 블록 전체를 먼저 지워야만** 합니다.

---

### FTL (Flash Translation Layer)과 쓰기 증폭(WAF)의 메커니즘

SSD 컨트롤러의 임베디드 OS인 **FTL**은 다음과 같이 동작합니다:
1. 기존 페이지를 지우는 대신 **"무효(INVALID)"**로 마킹하고, 다른 빈 페이지에 새 데이터를 씁니다(Out-of-place Write).
2. 여유 빈 블록이 부족해지면 **가비지 컬렉션(GC)**을 트리거합니다:
   - INVALID 페이지가 많은 희생양 블록(Victim Block)을 선정합니다.
   - 희생양 블록 안에 남아있는 **살아있는 유효(VALID) 페이지들을 다른 빈 블록으로 복사**합니다. (추가 물리 쓰기 발생!)
   - 희생양 블록 전체를 소거(Erase)하여 빈 블록으로 재활용합니다.

이로 인해 **사용자가 요청한 쓰기 양보다 실제 플래시 메모리에 가해진 물리적 쓰기 양이 몇 배로 폭증**하게 되며, 이 비율을 **쓰기 증폭 계수 (Write Amplification Factor, WAF)**라고 부릅니다:

$$	ext{WAF} = rac{	ext{플래시 메모리에 실제로 쓰여진 총 페이지 수}}{	ext{유저가 요청한 논리적 쓰기 페이지 수}} = rac{	ext{user\_writes} + 	ext{gc\_writes}}{	ext{user\_writes}}$$

- **TRIM 명령어의 구원**:  
  OS가 파일을 삭제할 때 SSD에 `TRIM`을 통보해주면, 해당 페이지가 즉시 INVALID로 마킹되어 **GC 시 유효 페이지 복사 오버헤드가 0**으로 사라지고 WAF가 1.0으로 최적화됩니다!

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG pages_per_block=<int> total_blocks=<int> op_pct=<int> gc_threshold=<int>`
   - SSD 기하구조 및 GC 임계값을 설정합니다.
   - 출력: `OK pages_per_block=<p> total_blocks=<b> op_pct=<op> gc_threshold=<gc>`

2. `WRITE lpa=<int> data=<str>`
   - 논리 페이지 주소(`lpa`)에 데이터를 씁니다.
   - 이미 매핑된 `lpa`는 이전 물리 페이지가 `INVALID`로 전환됩니다.
   - 가용 빈 블록 수가 `gc_threshold` 이하이면 GC가 자동 트리거됩니다:
     `GC_TRIGGERED victim_block=<id> invalid_pages=<inv> valid_pages_copied=<val>`  
     `BLOCK_ERASED block=<id> erase_count=<cnt>`
   - 물리 페이지에 쓰기 완료:  
     `WRITE_OK lpa=<lpa> ppa=(block=<b>,page=<p>) data=<data>`

3. `TRIM lpa=<int>`
   - 해당 `lpa`의 물리 페이지를 즉시 `INVALID`로 전환하고 매핑을 삭제합니다.
   - 출력: `TRIM_OK lpa=<lpa> ppa=(block=<b>,page=<p>) status=INVALIDATED` (미매핑 시 `TRIM_SKIPPED`)

4. `DUMP`
   - 전체 블록의 상태를 출력합니다:  
     `BLOCK <id>: erase=<cnt> [V,V,I,F]` (V=Valid, I=Invalid, F=Free)

5. `STATS`
   - 쓰기 통계 및 WAF를 출력합니다:  
     `STATS user_writes=<u> gc_writes=<g> total_writes=<t> waf=<waf:.2f> total_erases=<e>`

6. `RESET`
   - 모든 상태를 초기화합니다: `OK pages_per_block=4 total_blocks=8 op_pct=25`

---

## 예제 입력 1 (순차 쓰기와 WAF 1.0)

```text
CONFIG pages_per_block=4 total_blocks=8 op_pct=25 gc_threshold=1
WRITE lpa=0 data=data_0
WRITE lpa=1 data=data_1
WRITE lpa=2 data=data_2
DUMP
STATS
```

## 예제 출력 1

```text
OK pages_per_block=4 total_blocks=8 op_pct=25 gc_threshold=1
WRITE_OK lpa=0 ppa=(block=0,page=0) data=data_0
WRITE_OK lpa=1 ppa=(block=0,page=1) data=data_1
WRITE_OK lpa=2 ppa=(block=0,page=2) data=data_2
BLOCK 0: erase=0 [V,V,V,F]
BLOCK 1: erase=0 [F,F,F,F]
BLOCK 2: erase=0 [F,F,F,F]
BLOCK 3: erase=0 [F,F,F,F]
BLOCK 4: erase=0 [F,F,F,F]
BLOCK 5: erase=0 [F,F,F,F]
BLOCK 6: erase=0 [F,F,F,F]
BLOCK 7: erase=0 [F,F,F,F]
STATS user_writes=3 gc_writes=0 total_writes=3 waf=1.00 total_erases=0
```

---

## 예제 입력 2 (덮어쓰기로 인한 GC 트리거와 쓰기 증폭 WAF 상승)

```text
CONFIG pages_per_block=4 total_blocks=4 op_pct=25 gc_threshold=1
WRITE lpa=0 data=a0
WRITE lpa=1 data=a1
WRITE lpa=2 data=a2
WRITE lpa=3 data=a3
WRITE lpa=4 data=b0
WRITE lpa=5 data=b1
WRITE lpa=6 data=b2
WRITE lpa=7 data=b3
WRITE lpa=0 data=new_a0
WRITE lpa=1 data=new_a1
WRITE lpa=8 data=c0
STATS
```

## 예제 출력 2

```text
OK pages_per_block=4 total_blocks=4 op_pct=25 gc_threshold=1
WRITE_OK lpa=0 ppa=(block=0,page=0) data=a0
WRITE_OK lpa=1 ppa=(block=0,page=1) data=a1
WRITE_OK lpa=2 ppa=(block=0,page=2) data=a2
WRITE_OK lpa=3 ppa=(block=0,page=3) data=a3
WRITE_OK lpa=4 ppa=(block=1,page=0) data=b0
WRITE_OK lpa=5 ppa=(block=1,page=1) data=b1
WRITE_OK lpa=6 ppa=(block=1,page=2) data=b2
WRITE_OK lpa=7 ppa=(block=1,page=3) data=b3
WRITE_OK lpa=0 ppa=(block=2,page=0) data=new_a0
WRITE_OK lpa=1 ppa=(block=2,page=1) data=new_a1
GC_TRIGGERED victim_block=0 invalid_pages=2 valid_pages_copied=2
BLOCK_ERASED block=0 erase_count=1
WRITE_OK lpa=8 ppa=(block=0,page=0) data=c0
STATS user_writes=11 gc_writes=2 total_writes=13 waf=1.18 total_erases=1
```

> **설명**:  
> 블록 0의 `lpa=0, 1`을 덮어쓰자 구 페이지들이 `INVALID`로 마킹되었습니다.  
> 이후 여유 블록이 임계값에 도달하자 블록 0이 희생양으로 선정되어, 블록 0에 남아있던 유효 페이지(`lpa=2, 3`) 2개가 새 블록으로 복사(`valid_pages_copied=2`)된 뒤 블록 0이 소거되었습니다.  
> 유저는 11개의 페이지만 썼으나 내부적으로는 13개의 페이지가 물리적으로 기록되어 $	ext{WAF} = 1.18$로 증가했습니다!\n