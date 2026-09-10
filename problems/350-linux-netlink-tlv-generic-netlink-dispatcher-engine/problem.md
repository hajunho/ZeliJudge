# Linux Kernel Netlink IPC Protocol & Nested TLV Attribute Parsing & Generic Netlink (genl) Dispatcher Engine

> **실무/시니어 트랙 350문제 대기록 돌파 기념작 (Grand Milestone #350 / 누적 840문제 달성!)**  
> *Linux Kernel IPC의 핵심 중추: 커널 공간과 유저 공간을 비동기·양방향으로 연결하는 Netlink 프로토콜, 중첩 TLV(Type-Length-Value) 속성 검증 및 Generic Netlink(genl) 다중화 디스패처 엔진 (`net/netlink/af_netlink.c`, `net/netlink/genl.c`)*

---

## 1. 개요 및 배경

리눅스 커널과 유저 공간 애플리케이션 간의 통신은 운영체제 아키텍처의 핵심 과제입니다. 초기 유닉스/리눅스 환경에서는 `ioctl()` 시스템 콜이나 `procfs`/`sysfs` 가상 파일시스템을 주로 활용했습니다. 그러나:
1. **`ioctl`의 한계**: 아키텍처별 32비트/64비트 구조체 패딩 불일치, 타입 안전성 결여, 동기식 단방향 블로킹 호출에 국한되는 치명적 한계가 존재했습니다.
2. **`procfs`/`sysfs`의 한계**: 문자열 포맷팅 및 파싱 오버헤드가 크고, 대규모 네트워크 라우팅 테이블이나 링크 상태 변화를 고속으로 스트리밍하기에 부적합했습니다.

이를 혁신하기 위해 리눅스 커널 2.2에서 도입되고 2.6에서 대대적으로 확장된 것이 바로 **Netlink 소켓(`AF_NETLINK`)**과 **Generic Netlink(`genl`)**입니다. Netlink는 표준 소켓 API(`socket()`, `bind()`, `sendmsg()`, `recvmsg()`)를 통해 비동기 이벤트 통지, 멀티캐스트 브로드캐스트, 유연한 바이너리 직렬화를 제공하며, `iproute2` (`ip`, `ss`, `bridge`), `nl80211` (Wi-Fi 스택), `wireguard-tools`, `ethtool`, `devlink`, `audit`, `taskstats` 등 현대 리눅스 시스템 관리 도구의 100% 표준 통신 버스로 자리 잡았습니다.

특히 커널 내부의 정적 프로토콜 번호(최대 32개) 한계를 극복하기 위해 탄생한 **Generic Netlink(genl)**는, 단일 Netlink 프로토콜 번호(`NETLINK_GENERIC = 16`) 위에서 무한히 많은 동적 서브 패밀리를 등록하고 **중첩 TLV (Type-Length-Value, `struct nlattr`) 속성 스트림**을 통해 유연한 확장성을 보장합니다.

본 과제에서는 리눅스 커널의 핵심 컴포넌트인 `net/netlink/af_netlink.c`와 `net/netlink/genl.c`의 동작 원리를 바탕으로, Netlink 메시지 헤더 검증, Generic Netlink 패밀리 조회, 중첩 TLV 속성 파싱 및 정책(`nla_policy`) 유효성 검사, 권한 제어, 멀티파트 덤프(`NLM_F_DUMP`) 및 ACK 응답을 완벽하게 수행하는 **Netlink IPC & Generic Netlink 디스패처 엔진**을 구현합니다.

---

## 2. 시스템 아키텍처 및 패킷 파이프라인

```
+-------------------------------------------------------------------------+
|                  User Space (ip, iw, wg, ethtool 등)                    |
|             socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC)               |
+-------------------------------------------------------------------------+
                                   |
                         sendmsg() | [Binary Stream]
                                   v
+-------------------------------------------------------------------------+
| [1단계] Netlink 메시지 헤더 검증 (struct nlmsghdr)                       |
|   · nlmsg_len >= 16 (최소 헤더 크기)                                    |
|   · nlmsg_len % 4 == 0 (NLMSG_ALIGNTO 4바이트 정렬 검증)                |
|   · nlmsg_type < 16: 코어 제어 메시지 (NLMSG_NOOP, NLMSG_ERROR 등)      |
|   · nlmsg_type >= 16: Generic Netlink 패밀리 메시지                     |
+-------------------------------------------------------------------------+
                                   | (nlmsg_type >= 16)
                                   v
+-------------------------------------------------------------------------+
| [2단계] Generic Netlink 디스패칭 (struct genlmsghdr)                     |
|   · Family Registry 조회: family_id == nlmsg_type                       |
|       - 미등록 패밀리 -> NLMSG_ERROR (-ENOENT)                          |
|   · genlmsghdr (cmd, version) 추출 (nlmsg_len >= 20 필요)               |
|   · 버전 검증: msg.version <= family.version (-EPROTONOSUPPORT)         |
|   · 명령(cmd) 매핑 및 권한 검증:                                        |
|       - 미지원 명령 -> -EOPNOTSUPP                                      |
|       - requires_root == True AND sender != root -> -EPERM              |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [3단계] TLV 속성 스트림 파싱 및 정책 검증 (struct nlattr & nla_policy)   |
|   · Attribute 헤더: nla_len (16비트), nla_type (16비트)                 |
|       - NLA_F_NESTED (bit 15 = 0x8000), attr_id = nla_type & 0x3FFF    |
|   · attr_id 유효 범위: 1 <= attr_id <= family.maxattr                   |
|   · Policy Schema 검증:                                                 |
|       - U8, U16, U32: 정수 범위 및 바이트 길이                          |
|       - STRING: 널 종단 포함 바이트 길이, min_len / max_len 검증         |
|       - FLAG: 불리언 플래그                                             |
|       - NESTED: NLA_F_NESTED 플래그 검증 및 재귀적 자식 속성 파싱       |
|   · 4바이트 와이어 정렬: NLA_ALIGN(nla_len) = (nla_len + 3) & ~3        |
+-------------------------------------------------------------------------+
                                   |
                                   v
+-------------------------------------------------------------------------+
| [4단계] 명령 실행 및 커널 응답 생성                                     |
|   · NLM_F_DUMP 플래그 검사:                                             |
|       - Dump 지원 시: Multipart 스트림 (NLM_F_MULTI) 전송                |
|       - 종단 프레임: NLMSG_DONE (type 3) 전송                           |
|   · 유니캐스트 응답: 파싱된 속성 요약 및 와이어 바이트 수 반환          |
|   · NLM_F_ACK 플래그: 성공 시 NLMSG_ERROR (errno = 0) ACK 프레임 응답   |
+-------------------------------------------------------------------------+
```

---

## 3. 핵심 커널 자료구조 및 알고리즘 명세

### 3.1 Netlink 메시지 헤더 (`struct nlmsghdr`)
```c
struct nlmsghdr {
    __u32 nlmsg_len;    /* 헤더를 포함한 전체 메시지 길이 */
    __u16 nlmsg_type;   /* 메시지 타입 (컨트롤: 1~3, 동적 패밀리: >= 16) */
    __u16 nlmsg_flags;  /* 플래그 (NLM_F_REQUEST, NLM_F_ACK, NLM_F_DUMP 등) */
    __u32 nlmsg_seq;    /* 시퀀스 번호 (요청-응답 매핑) */
    __u32 nlmsg_pid;    /* 송신자 포트 ID / 프로세스 PID (커널은 0) */
};
```
- **검증 규칙**:
  - `nlmsg_len < 16`: `NLMSG_LEN_TOO_SHORT` (에러 코드 `-EINVAL`, errno -22)
  - `nlmsg_len % 4 != 0`: `NLMSG_NOT_ALIGNED` (에러 코드 `-EINVAL`, errno -22)
- **컨트롤 메시지 타입 (`nlmsg_type < 16`)**:
  - `1` (`NLMSG_NOOP`): 유효한 무동작 메시지. 처리 결과 `status: "NOOP"`, `details: "NLMSG_NOOP_IGNORED"`.
  - `2` (`NLMSG_ERROR`), `3` (`NLMSG_DONE`), 기타 `< 16`: 미지원 컨트롤 타입. `EOPNOTSUPP` (errno -95).

### 3.2 Generic Netlink 헤더 (`struct genlmsghdr`)
```c
struct genlmsghdr {
    __u8  cmd;          /* 패밀리별 명령 번호 */
    __u8  version;      /* 프로토콜 버전 */
    __u16 reserved;     /* 예약 패딩 */
};
```
- Generic Netlink 메시지(`nlmsg_type >= 16`)는 `nlmsg_len >= 20` (헤더 16B + genl 헤더 4B)이어야 합니다. 부족할 경우 `-EINVAL` (`GENL_HDR_TOO_SHORT`).
- 패밀리 등록 테이블에서 `family_id == nlmsg_type`을 검색합니다. 미발견 시 `-ENOENT` (errno -2).
- `genlmsghdr.version > family.version`이면 `-EPROTONOSUPPORT` (errno -93).
- 패밀리의 명령 목록에서 `cmd`를 검색합니다. 미발견 시 `-EOPNOTSUPP` (errno -95).
- 명령의 `requires_root == true`이고 송신자가 비루트(`is_sender_root == false`)이면 `-EPERM` (errno -1, `GENL_PERMISSION_DENIED`).

### 3.3 TLV 속성 구조 (`struct nlattr`) 및 정책 검증
```c
struct nlattr {
    __u16 nla_len;      /* 속성 헤더(4B) + 페이로드 길이 */
    __u16 nla_type;     /* Bit 15: NLA_F_NESTED, Bit 14: NLA_F_NET_BYTEORDER, 하위 14비트: Attr ID */
};
```
- **속성 식별자**: `attr_id = nla_type & 0x3FFF`.
- **중첩 여부**: `is_nested = bool(nla_type & 0x8000)`.
- **속성 ID 범위**: $1 \le 	ext{attr\_id} \le 	ext{maxattr}$. 범위를 벗어나거나 0인 경우 `-EINVAL` (`ATTR_ID_OUT_OF_RANGE`).
- **정책 타입별 검증**:
  - `U8`: $0 \le 	ext{val} \le 255$, 페이로드 길이 1B.
  - `U16`: $0 \le 	ext{val} \le 65535$, 페이로드 길이 2B.
  - `U32`: $0 \le 	ext{val} \le 4294967295$, 페이로드 길이 4B.
  - `STRING`: 문자열 타입, 널 종단 포함 길이 = `len(utf8_bytes) + 1`. 문자열 길이가 `min_len`과 `max_len` 사이여야 함. 벗어날 경우 `-EINVAL` (`STRING_LEN_OUT_OF_BOUNDS`).
  - `FLAG`: 불리언 플래그, 페이로드 길이 0B.
  - `NESTED`: 반드시 `is_nested == true`여야 하며, 자식 속성 리스트를 재귀적으로 `child_policies`에 따라 검증.
- **와이어 길이 계산**:
  - $	ext{nla\_len} = 4 + 	ext{payload\_len}$
  - $	ext{aligned\_wire\_len} = (	ext{nla\_len} + 3) \ \& \ \sim 3$ (4바이트 올림 정렬)

### 3.4 응답 생성 및 플래그 핸들링
- `NLM_F_DUMP` 플래그 존재 시:
  - 명령의 `supports_dump == false`이면 `-EOPNOTSUPP` (`CMD_DOES_NOT_SUPPORT_DUMP`).
  - 덤프 지원 시, 각 청크는 `NLM_F_MULTI` 플래그를 가지며 스트림의 마지막에 `nlmsg_type = 3` (`NLMSG_DONE`) 프레임을 전송합니다.
- 일반 유니캐스트 요청 시:
  - 응답 프레임(`nlmsg_type = family_id`)을 생성하며, 파싱된 속성 수(`parsed_attr_count`)와 총 속성 와이어 바이트 수(`total_attr_bytes`)를 반환합니다.
- `NLM_F_ACK` 플래그 존재 시 (덤프가 아닌 경우):
  - 표준 리눅스 Netlink 규격에 따라 `nlmsg_type = 2` (`NLMSG_ERROR`), `error_code = 0` (성공 ACK) 프레임을 원본 `nlmsg_seq`와 함께 응답합니다.

---

## 4. 입출력 형식 및 제약 조건

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "families": [
    {
      "family_id": 16,
      "name": "nl80211",
      "version": 1,
      "maxattr": 10,
      "policies": {
        "1": {"type": "STRING", "min_len": 1, "max_len": 16},
        "2": {"type": "U32"},
        "3": {"type": "FLAG"},
        "4": {"type": "NESTED", "child_policies": {
          "1": {"type": "U32"},
          "2": {"type": "STRING", "min_len": 1, "max_len": 32}
        }}
      },
      "commands": [
        {"cmd_id": 1, "name": "GET_WIPHY", "requires_root": false, "supports_dump": true},
        {"cmd_id": 2, "name": "SET_WIPHY", "requires_root": true, "supports_dump": false}
      ]
    }
  ],
  "messages": [
    {
      "msg_id": "MSG_WIPHY_INFO",
      "is_sender_root": false,
      "nlmsghdr": {
        "nlmsg_len": 44,
        "nlmsg_type": 16,
        "nlmsg_flags": ["NLM_F_REQUEST", "NLM_F_ACK"],
        "nlmsg_seq": 101,
        "nlmsg_pid": 4512
      },
      "genlmsghdr": {
        "cmd": 1,
        "version": 1
      },
      "raw_attrs": [
        {"type": 1, "value": "wlan0"},
        {"type": 2, "value": 5180}
      ]
    }
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 JSON 직렬화 결과를 공백 없는 단일 라인(`separators=(',', ':')`, `ensure_ascii=False`)으로 출력합니다:
```json
{
  "processed_count": 1,
  "results": [
    {
      "msg_id": "MSG_WIPHY_INFO",
      "status": "SUCCESS",
      "dispatched_family": "nl80211",
      "command": "GET_WIPHY",
      "parsed_attrs": {
        "1": {
          "attr_id": 1,
          "type": "STRING",
          "is_nested": false,
          "nla_len": 10,
          "aligned_wire_len": 12,
          "value": "wlan0"
        },
        "2": {
          "attr_id": 2,
          "type": "U32",
          "is_nested": false,
          "nla_len": 8,
          "aligned_wire_len": 8,
          "value": 5180
        }
      },
      "total_attr_wire_bytes": 20,
      "replies": [
        {
          "nlmsg_type": 16,
          "nlmsg_flags": [],
          "nlmsg_seq": 101,
          "genl_cmd": "GET_WIPHY",
          "dispatched_family": "nl80211",
          "parsed_attr_count": 2,
          "total_attr_bytes": 20
        },
        {
          "nlmsg_type": 2,
          "nlmsg_flags": [],
          "nlmsg_seq": 101,
          "error_code": 0,
          "status": "ACK_SUCCESS"
        }
      ]
    }
  ]
}
```

### 제약 조건
- $1 \le \text{len(families)} \le 32$
- $16 \le \text{family\_id} \le 1024$
- $1 \le \text{len(messages)} \le 100$
- $1 \le \text{maxattr} \le 64$
- 모든 TLV 바이트 계산은 커널의 `NLMSG_ALIGNTO` 및 `NLA_ALIGNTO` (4바이트) 정렬 규칙을 엄격히 준수해야 합니다.
