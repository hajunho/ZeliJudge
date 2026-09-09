# 문제 252 이론: NVMe ZNS (Zoned Namespaces) 플래시 아키텍처, Zone Append 원자성과 호스트 주도 가비지 컬렉션

---

## 1. 기존 SSD의 한계와 FTL(Flash Translation Layer)의 딜레마

전통적인 NVMe SSD는 하드디스크처럼 임의의 LBA에 대한 덮어쓰기(Overwrite)가 가능한 것처럼 보이지만, 물리적 NAND 플래시 메모리는 **페이지(Page, 4KB~16KB) 단위로만 쓸 수 있고, 지우기는 거대한 블록(Block, 4MB~32MB) 단위로만 가능**합니다.

```
+-------------------------------------------------------------+
| Conventional SSD Architecture                               |
|                                                             |
| Host Random Writes ──► [ FTL (L2P Table in DRAM) ]          |
|                             │ Out-of-place writes           |
|                             ▼                               |
|                    [ NAND Flash Blocks ]                    |
|                             │ Drive GC: Copy & Erase Block  |
|                             ▼                               |
|                    Write Amplification (WAF: 3x - 10x)      |
|                    Tail Latency Spike (p99.99 > 50ms)       |
+-------------------------------------------------------------+
```

### 전통적 SSD의 치명적 결함:
1. **DRAM 비용 폭증**: 1TB SSD당 약 1GB의 DRAM이 L2P 매핑 테이블 유지에 필요합니다.
2. **쓰기 증폭(WAF)**: 드라이브 내부의 FTL이 유효 데이터를 이리저리 복사하며 NAND를 계속 지우므로 수명이 급감합니다.
3. **I/O 충돌 및 테일 레이턴시**: 호스트의 읽기/쓰기 요청과 FTL의 백그라운드 블록 소거 작업이 충돌하여 레이턴시가 수십 밀리초 이상 치솟습니다.

---

## 2. NVMe ZNS (TP 4053) 아키텍처와 순차 쓰기 제약

NVMe Zoned Namespaces는 FTL을 완전히 제거하고, 물리 플래시 블록의 경계를 호스트에게 **Zone**이라는 논리적 단위(보통 1GB~2GB)로 직접 매핑합니다.

```
+-------------------------------------------------------------+
| Zone Architecture (e.g. Zone 0, Capacity: 1024MB)           |
|                                                             |
| [Written Data] [Written Data] [WP] [Unwritten Free Area]    |
| 0MB            128MB          256MB                1024MB   |
|                                 ▲                           |
|                                 │ Write Pointer (WP)        |
+-------------------------------------------------------------+
```

### ZNS의 핵심 규칙:
- 각 존 내의 쓰기는 반드시 현재 **Write Pointer (WP)** 위치에서만 시작되어야 합니다.
- 만약 호스트가 `WP`보다 크거나 작은 LBA에 일반 쓰기(`NVME_NVM_CMD_WRITE`)를 요청하면, 드라이브는 **`NVME_SC_ZONE_INVALID_WRITE` (0x2DF)** 에러를 반환합니다.
- 데이터 덮어쓰기는 절대 불가능하며, 존을 다시 사용하려면 전체 존을 지우는 **`Zone Reset`** 명령을 내려야 합니다.

---

## 3. Zone Append: 멀티스레드 락 경합의 혁신적 해결

전통적인 쓰기(`Write`) 명령을 ZNS에서 멀티스레드로 수행할 경우:
1. 스레드 1과 스레드 2가 동시에 현재 `WP=256MB`를 읽습니다.
2. 스레드 1은 `LBA=256`에, 스레드 2는 `LBA=384`에 쓰려고 합니다.
3. 그러나 OS 스케줄러나 PCIe 버스 지연으로 인해 스레드 2의 명령이 드라이브에 먼저 도달하면, 드라이브의 실제 WP는 아직 256MB이므로 스레드 2의 명령은 즉시 에러로 실패합니다.
4. 이를 막으려면 호스트의 모든 스레드가 단일 뮤텍스(Mutex)를 잡고 쓰기를 직렬화해야 하므로 I/O 성능이 바닥을 칩니다.

### Zone Append (`NVME_NVM_CMD_ZONE_APPEND`)의 메커니즘:
```
 Host Threads                    NVMe Controller
      │                                 │
      │ 1. Zone Append (ZSLBA=0, 128MB) │
      ├────────────────────────────────►│ 2. Atomically assign WP (0)
      │                                 │    WP becomes 128
      │ 3. Zone Append (ZSLBA=0, 128MB) │
      ├────────────────────────────────►│ 4. Atomically assign WP (128)
      │                                 │    WP becomes 256
      │                                 │
      │◄── CQE (Assigned LBA: 0) ───────┤
      │◄── CQE (Assigned LBA: 128) ─────┤
```
- 호스트는 구체적인 LBA를 명시하지 않고 단지 존의 시작 주소(`ZSLBA`)로 데이터를 전송합니다.
- 드라이브 컨트롤러 하드웨어가 현재 WP 위치에 데이터를 원자적으로 배치하고, 완료 큐(CQE)에 할당된 실제 LBA를 반환합니다.
- 호스트 측의 어떠한 락도 없이 완벽한 병렬 동시 쓰기가 가능해집니다.

---

## 4. 호스트 주도 가비지 컬렉션 (Host-Managed GC)

ZNS에서는 FTL이 없으므로, 데이터의 삭제/무효화에 따른 공간 회수를 **호스트 소프트웨어(RocksDB ZenFS / Ceph Crimson)**가 직접 주도합니다.

```
 [ FULL Zone (Victim) ]
 ├─ Key 1: Invalidate (Deleted)
 ├─ Key 2: Valid (100MB) ──────► Copy to Active Zone via Zone Append
 └─ Key 3: Invalidate (Deleted)
 
 ──► Issue NVME_ZONE_MGMT_SEND (Zone Reset)
 ──► Zone becomes EMPTY (WP = 0)! WAF = 1.05!
```

### 이점:
- 스토리지 엔진이 데이터의 수명(Lifetime)과 핫/콜드 속성을 이미 알고 있으므로, 비슷한 수명의 데이터를 같은 존에 배치할 수 있습니다.
- 쓰기 증폭(WAF)을 이론적 최솟값인 $1.0 \sim 1.1$로 억제할 수 있습니다.
- 불필요한 드라이브 내부 GC가 없어 테일 레이턴시가 10배 이상 안정화됩니다.
