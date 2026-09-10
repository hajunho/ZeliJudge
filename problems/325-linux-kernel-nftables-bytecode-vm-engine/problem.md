# Linux Kernel Netfilter nftables: 레지스터 기반 가상 머신(VM) 및 동적 셋 분류 엔진

## 문제 설명

리눅스 커널 3.13부터 도입된 **nftables(`net/netfilter/nf_tables_core.c`)**는 기존의 `iptables`가 지니고 있던 거대한 모놀리식 C 매치/타깃 확장 구조와 과도한 커널-유저스페이스 메모리 복사 문제를 해결하기 위해 설계된 차세대 고성능 패킷 필터링 서브시스템입니다.

`nftables`의 핵심 혁신은 커널 내부에서 실행되는 **경량 레지스터 기반 바이트코드 가상 머신(Register-based Bytecode VM)**입니다. 기존의 하드코딩된 규칙 체인 대신, 사용자 공간 도구(`nft`)가 필터링 규칙을 일련의 직교적인 표현식(`nft_expr`) 바이트코드로 컴파일하여 커널에 전달하면, 커널 VM(`nft_do_chain`)은 1개의 평결 레지스터(`NFT_REG_VERDICT`)와 16개의 범용 32비트 데이터 레지스터(`NFT_REG32_00` ~ `NFT_REG32_15`)를 사용하여 초당 수천만 패킷을 나노초 단위로 평가합니다.

또한 `nftables`는 집합(Set)과 맵(Map)을 1급 시민(First-class citizen)으로 지원하여 $O(N)$ 선형 규칙 탐색을 $O(1)$ 해시 테이블 또는 $O(\log N)$ 레드-블랙 트리 룩업으로 대체하며, 패킷 유입에 따라 실시간으로 상태를 갱신하고 타임아웃 만료 시 가비지 컬렉션(GC)을 수행하는 동적 셋(`DYNSET`)을 제공합니다.

본 문제에서는 리눅스 커널의 `net/netfilter/nf_tables_core.c`에 구현된 `nft_do_chain` 패킷 처리 루프, 레지스터 상태 머신, 표현식(`PAYLOAD`, `CMP`, `RANGE`, `BITWISE`, `LOOKUP`, `DYNSET`, `COUNTER`, `IMMEDIATE`), 체인 호출 스택(`JUMP`, `GOTO`, `RETURN`), 그리고 타임아웃 만료 GC를 갖춘 동적 셋 분류 엔진을 완벽히 모델링하는 커널급 가상 머신을 구현합니다.

---

## 아키텍처 및 내부 메커니즘

```
                              [ sk_buff 패킷 유입 ]
                                        │
                                        ▼
                      ┌───────────────────────────────────┐
                      │    Netfilter 훅 (Hook Points)     │
                      │  PREROUTING / LOCAL_IN / FORWARD  │
                      └─────────────────┬─────────────────┘
                                        │
             우선순위(Priority) 정렬에 따른 Base Chain 선택
                                        ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │              nftables 가상 머신 (VM: nft_do_chain)                │
    │                                                                   │
    │  [레지스터 구조]                                                   │
    │  - Verdict Register: code (CONTINUE/ACCEPT/DROP/BREAK/JUMP/GOTO)  │
    │  - Data Registers: REG_00 ~ REG_15 (32-bit Integer / Bytes)       │
    │  - Call Stack: [(caller_chain, return_rule_idx), ...]             │
    │                                                                   │
    │  [표현식 평가 루프 (Expressions)]                                  │
    │   1. PAYLOAD  : 패킷 헤더(IP/TCP) 필드 추출 -> dest_reg 저장       │
    │   2. BITWISE  : (sreg & mask) ^ xor -> dreg 저장                  │
    │   3. CMP/RANGE: 레지스터 값과 비교 불일치 시 NFT_BREAK 발생        │
    │   4. LOOKUP   : Set 검색 ($O(1)$), 일치 시 Verdict/Data 로드      │
    │   5. DYNSET   : 동적 셋에 키 등록/업데이트 및 타임아웃 설정       │
    │   6. COUNTER  : 규칙 단위 packets / bytes 카운터 증가             │
    │   7. IMMEDIATE: 레지스터 값 또는 Verdict 직접 설정                │
    └─────────────────┬───────────────────────────────┬─────────────────┘
                      │                               │
                      ▼                               ▼
               [ NF_ACCEPT ]                    [ NF_DROP ]
              (패킷 통과/수신)                 (패킷 폐기/차단)
```

### 1. 표현식 연산 명세 (Expressions)

1. **`PAYLOAD` (`dest_reg`, `base`, `offset`, `length`)**:
   - `base == "NETWORK_HEADER"`:
     - `offset == 12`: `src_ip` 추출 -> `regs[dest_reg]`
     - `offset == 16`: `dst_ip` 추출 -> `regs[dest_reg]`
     - `offset == 9`: `proto` 추출 (예: TCP=6, UDP=17) -> `regs[dest_reg]`
   - `base == "TRANSPORT_HEADER"`:
     - `offset == 0`: `src_port` 추출 -> `regs[dest_reg]`
     - `offset == 2`: `dst_port` 추출 -> `regs[dest_reg]`
     - `offset == 13`: `tcp_flags` 추출 -> `regs[dest_reg]`
2. **`IMMEDIATE`**:
   - `"dest_reg"`와 `"value"` 지정 시: `regs[dest_reg] = value`
   - `"verdict"` 지정 시: 평결 레지스터에 `verdict` 설정
3. **`CMP` (`sreg`, `cmp_op`, `value`)**:
   - `sreg`의 값과 `value`를 비교 연산자(`EQ`, `NEQ`, `LT`, `LTE`, `GT`, `GTE`)로 평가합니다.
   - 조건 불일치 시 평결 레지스터를 `NFT_BREAK`로 설정하고 현재 규칙의 남은 표현식 실행을 중단(break)합니다.
4. **`RANGE` (`sreg`, `min_val`, `max_val`)**:
   - $	ext{min\_val} \le 	ext{regs}[sreg] \le 	ext{max\_val}$ 여부를 검사합니다.
   - 불일치 시 `NFT_BREAK`를 설정하고 규칙 실행을 중단합니다.
5. **`BITWISE` (`sreg`, `dreg`, `mask`, `xor`)**:
   - 비트 연산 수행: $	ext{regs}[dreg] = (	ext{regs}[sreg] \ \& \ 	ext{mask}) \ \oplus \ 	ext{xor}$
6. **`LOOKUP` (`set_name`, `sreg`, `dreg`)**:
   - 지정된 셋에서 `regs[sreg]`를 키로 탐색합니다. (만료된 요소는 자동 GC 제외)
   - 키가 없으면 `NFT_BREAK`를 설정하고 중단합니다.
   - 키가 존재하고 요소에 맵 데이터가 있으며 `dreg`가 지정된 경우:
     - 만약 데이터가 `{"verdict": ...}` 객체이면 평결 레지스터에 로드합니다.
     - 그 외의 경우 `regs[dreg]`에 데이터를 로드합니다.
7. **`DYNSET` (`set_name`, `sreg_key`, `timeout_ms`)**:
   - 동적 셋에 `regs[sreg_key]`를 추가하거나 갱신합니다.
   - 해당 요소의 패킷 수(`packets`)를 1 증가시키고 바이트 수(`bytes`)를 패킷의 `length`만큼 누적합니다.
8. **`COUNTER`**:
   - 현재 규칙(`rule`)의 `stats.packets`를 1 증가시키고 `stats.bytes`에 패킷 길이를 누적합니다.

### 2. 체인 및 제어 흐름 (Control Flow)

- `NFT_BREAK`: 현재 규칙 불일치. 체인의 다음 규칙으로 이동합니다.
- `NFT_CONTINUE`: 현재 규칙의 모든 표현식이 통과되었으나 명시적 종결 평결이 없음. 체인의 다음 규칙으로 이동합니다.
- `NF_ACCEPT` / `NF_DROP`: 최종 평결. 패킷 평가를 즉시 종료하고 수락 또는 폐기합니다.
- `NFT_JUMP` (`chain`): 대상 체인으로 점프하며, 복귀 주소(`caller_chain`, `next_rule_idx`)를 호출 스택에 푸시합니다.
- `NFT_GOTO` (`chain`): 대상 체인으로 점프하되 스택에 복귀 주소를 남기지 않습니다.
- `NFT_RETURN`: 서브 체인 실행 종료 후 호출 스택의 상위 체인/규칙으로 복귀합니다. 호출 스택이 비어 있다면 현재 기본 체인의 기본 정책(`policy`)을 적용합니다.
- 체인의 모든 규칙을 다 돌았을 때:
  - 호출 스택에 복귀 주소가 남아있으면 스택을 팝하여 상위 체인으로 돌아갑니다.
  - 호출 스택이 비어있다면 해당 베이스 체인의 기본 정책(`policy`: `ACCEPT` 또는 `DROP`)에 따라 패킷을 처리합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "name": "filter",
    "sets": [
      {
        "name": "blacklist",
        "key_type": "ipv4_addr",
        "elements": [{"key": 167772165}]
      }
    ],
    "chains": [
      {
        "name": "input",
        "hook": "LOCAL_IN",
        "priority": 0,
        "policy": "DROP",
        "rules": [
          {
            "expressions": [
              {"op": "PAYLOAD", "dest_reg": 1, "base": "NETWORK_HEADER", "offset": 12, "length": 4},
              {"op": "LOOKUP", "set_name": "blacklist", "sreg": 1},
              {"op": "COUNTER"},
              {"op": "IMMEDIATE", "verdict": {"code": "NF_DROP"}}
            ]
          }
        ]
      }
    ]
  },
  "commands": [
    {
      "type": "PACKET",
      "hook": "LOCAL_IN",
      "packet": {
        "id": "p1",
        "src_ip": 167772165,
        "dst_ip": 167772161,
        "proto": 6,
        "src_port": 1234,
        "dst_port": 80,
        "length": 64,
        "timestamp_ms": 100
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 한 줄로 출력합니다:
```json
{"table":"filter","stats":{"packets_processed":1,"packets_accepted":0,"packets_dropped":1,"rules_evaluated":1,"expressions_executed":4},"packet_results":[{"packet_id":"p1","verdict":"DROP","timestamp_ms":100}],"sets":{"blacklist":{"name":"blacklist","key_type":"ipv4_addr","data_type":null,"dynamic":false,"elements":{"167772165":{"key":167772165,"data":null,"timeout_ms":null,"expiration_ts":null,"packets":0,"bytes":0}}}},"chains":{"input":{"name":"input","hook":"LOCAL_IN","priority":0,"policy":"DROP","rules":[{"expressions":[{"op":"PAYLOAD","dest_reg":1,"base":"NETWORK_HEADER","offset":12,"length":4},{"op":"LOOKUP","set_name":"blacklist","sreg":1},{"op":"COUNTER"},{"op":"IMMEDIATE","verdict":{"code":"NF_DROP"}}],"stats":{"packets":1,"bytes":64}}]}},"snapshots":[]}
```
