# 문제 424: 리눅스 커널 기밀 컴퓨팅 및 ARM64 아키텍처: ARM CCA Realm Management Extension(RME) 및 과립 보호 테이블(GPT) 보안 엔진

## 1. 개요 (Overview)

클라우드 컴퓨팅 환경에서 가상 머신(VM)을 실행하는 테넌트는 호스트 하이퍼바이저(KVM, Xen)나 클라우드 제공자(CSP)의 악의적 내부자 또는 침해된 호스트 커널로부터 자신의 민감한 데이터와 실행 코드를 완전히 격리하여 보호해야 합니다. x86 아키텍처에서 AMD SEV-SNP와 Intel TDX가 하드웨어 기반 기밀 가상화(Confidential Virtual Machine, CVM)를 주도해왔다면, **ARM 아키텍처는 ARMv9-A에서 ARM CCA(Confidential Compute Architecture)**를 공식 도입하였습니다.

ARM CCA의 심장은 **RME(Realm Management Extension)**입니다. 기존의 2대 보안 세계(Secure World / Non-secure World)를 확장하여 시스템을 **4대 보안 세계(Root World, Secure World, Non-secure World, Realm World)**로 완전히 분리합니다.
1. **Root World (EL3)**: 플랫폼 신뢰의 닻(Root of Trust)으로 과립 보호 테이블(GPT)을 구성하고 하드웨어 모니터를 실행합니다.
2. **Non-secure World (NS-EL0/EL1/EL2)**: 기존 리눅스 호스트 커널 및 KVM 하이퍼바이저가 동작합니다.
3. **Realm World (RL-EL0/EL1/EL2)**: 호스트로부터 완벽히 보호받는 기밀 가상 머신(**Realm**)이 동작합니다.
4. **Secure World (S-EL0/EL1/EL2)**: 전통적인 하드웨어 보안 서비스(OP-TEE 등)가 동작합니다.

호스트 커널의 KVM은 물리 메모리(4KB 과립, Granule)를 Realm에 할당하기 위해 SMC(Secure Monitor Call)를 통해 **RMI(Realm Management Interface)**를 호출하며, 하드웨어 MMU에 내장된 **과립 보호 검사(Granule Protection Check, GPC)** 유닛은 호스트가 Realm 소유의 물리 메모리에 접근하려는 모든 시도를 하드웨어 레벨에서 즉각 차단(#GPF)합니다.

본 과제에서는 리눅스 커널 `arch/arm64/kvm/rme.c` 및 ARM RME 사양에 기반하여, 물리 메모리 과립 위임(Delegation), 렐름 생성 및 2단계 변환 테이블(RTT) 매핑, 롤링 측정값(Measurement) 봉인, 호스트 침입 시 하드웨어 GPC 장애 차단, 챌린지 기반 원격 증명(Attestation Token) 발행, 그리고 렐름 파괴 시 메모리 스크러빙(Scrubbing) 및 위임 해제(Undelegation) 생명주기를 완벽히 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 시스템 아키텍처 및 4대 보안 세계 (System Topology)

```
+-------------------------------------------------------------------------+
|                                ARMv9-A CPU Core                         |
|   +-----------------------------------------------------------------+   |
|   |                  Granule Protection Check (GPC)                 |   |
|   |   (Hardware Filter on Physical Bus: Non-secure vs Realm vs ...) |   |
|   +-----------------------------------------------------------------+   |
+------------------------------------+------------------------------------+
                                     |
    +-------------------+------------+------------+-------------------+
    |                   |                         |                   |
    v                   v                         v                   v
[Root World EL3]   [Secure World]           [Non-secure World]   [Realm World]
- Firmware Monitor - TrustZone OP-TEE       - Host Linux OS      - Confidential VM
- Configures GPT   - Secure OS / DRM        - KVM Hypervisor     - Realm (Protected)
                                            - Untrusted Entity   - Encrypted/Isolated
                                                  │ (SMC)              ▲
                                                  ▼                    │
                                            +------------+             │
                                            |  RMM / RMI |─────────────+
                                            +------------+
                                            (Realm Management Interface)
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 상태 모델 (State Models)

1. **물리 과립 (`Granule`)**:
   - `pa`: 물리 주소 문자열 (예: `"0x10000"`).
   - `state`: 과립의 보안 상태 (`"NON_SECURE"`, `"REALM"`). 기본 상태는 `"NON_SECURE"`.
   - `realm_id`: 해당 과립이 매핑된 Realm 식별자 문자열 (미매핑 시 `None`).
   - `scrubbed`: 메모리 0-소거 여부 (`True`/`False`).

2. **렐름 (`Realm`)**:
   - `realm_id`: 고유 식별자 문자열.
   - `state`: 렐름 상태 (`"NEW"`, `"ACTIVE"`, `"DESTROYED"`).
   - `measurement`: 16진수 16글자 롤링 해시 문자열. 초기값은 SHA-256("RME_INITIAL_SEED")의 앞 16자리 (`f25a...`).
   - `ipa_map`: Stage 2 매핑 딕셔너리 (`ipa -> { "pa": pa, "ripas": "RAM"|"DESTROYED", "data_hash": ... }`).

### 3.2 이벤트 처리 규칙

1. **`RMI_GRANULE_DELEGATE` (`time`, `pa`)**:
   - 호스트가 물리 과립을 Realm 월드로 위임(Delegate)합니다.
   - 해당 과립의 상태가 `"NON_SECURE"`가 아니면 `RMI_ERROR` 이벤트를 기록하고 실패 처리합니다.
   - 과립 상태를 `"REALM"`으로 전이하고, `scrubbed = False`, `delegated_granules_count`를 1 증가시킵니다.
   - `event_logs`에 `RMI_GRANULE_DELEGATE_SUCCESS`를 기록합니다.

2. **`RMI_REALM_CREATE` (`time`, `realm_id`, `params`)**:
   - 신규 Realm 인스턴스를 생성합니다.
   - 이미 존재하는 `realm_id`이면 `RMI_ERROR`를 기록하고 실패 처리합니다.
   - `state = "NEW"`, 초기 `measurement` 설정, `realms_created`를 1 증가시킵니다.
   - `event_logs`에 `RMI_REALM_CREATE_SUCCESS`를 기록합니다.

3. **`RMI_RTT_MAP` (`time`, `realm_id`, `ipa`, `pa`, `data_hash`)**:
   - Realm의 Stage 2 RTT(Realm Translation Table)에 물리 과립 `pa`를 가상 주소 `ipa`로 매핑합니다.
   - 검증 조건:
     - 해당 Realm이 `"NEW"` 상태여야 합니다 (이미 `"ACTIVE"`이면 매핑 불가 -> `RMI_ERROR`).
     - `pa`의 상태가 `"REALM"`이어야 하며, 다른 Realm이나 이미 매핑된 상태(`realm_id is not None`)가 아니어야 합니다.
   - 검증 통과 시:
     - `pa` 과립의 `realm_id`를 등록합니다.
     - `ipa_map`에 `{ "pa": pa, "ripas": "RAM", "data_hash": data_hash }`를 등록합니다.
     - **롤링 측정값(Measurement) 갱신**:
       `new_measurement = SHA256(current_meas + ipa + pa + data_hash)[:16]`
     - `event_logs`에 `RMI_RTT_MAP_SUCCESS`를 기록합니다.

4. **`RMI_REALM_ACTIVATE` (`time`, `realm_id`)**:
   - Realm의 구성을 완료하고 실행 가능한 `"ACTIVE"` 상태로 봉인(Seal)합니다.
   - `state = "ACTIVE"`로 전이하고, `realms_active`를 1 증가시킵니다.
   - `security_logs`에 `REALM_SEALED_AND_ACTIVATED` 액션을 기록하고, `event_logs`에 성공을 기록합니다.

5. **`HOST_ACCESS_ATTEMPT` (`time`, `pa`, `access_type` ["READ" | "WRITE"])**:
   - 호스트 CPU가 물리 주소 `pa`에 직접 읽기/쓰기를 시도하는 하드웨어 접근을 모사합니다.
   - **과립 보호 검사 (Hardware GPC)**:
     - 해당 `pa`의 상태가 `"REALM"`인 경우:
       하드웨어 GPC 유닛이 버스 트랜잭션을 즉각 강제 중단하고 GPC 폴트를 발생시킵니다.
       - `gpc_faults_blocked`를 1 증가시킵니다.
       - `security_logs`에 `GPC_FAULT_BLOCKED`를 기록합니다.
       - `event_logs`에 `HARDWARE_GPC_FAULT`를 기록합니다 (`status = "TERMINATED_BY_GPC"`).
     - 해당 `pa`의 상태가 `"NON_SECURE"`인 경우:
       접근이 허용되며, `event_logs`에 `HOST_ACCESS_ALLOWED`를 기록합니다.

6. **`RSI_ATTESTATION_TOKEN` (`time`, `realm_id`, `challenge`)**:
   - 게스트가 RSI(Realm Service Interface)를 통해 원격 검증용 증명 토큰을 요청합니다.
   - `token_signature = SHA256(measurement + challenge)[:24]`를 생성합니다.
   - `security_logs`에 `RSI_ATTESTATION_ISSUED`를 기록하고, `event_logs`에 성공을 기록합니다.

7. **`RMI_REALM_DESTROY` (`time`, `realm_id`)**:
   - Realm을 종료 및 파괴합니다.
   - 이전 상태가 `"ACTIVE"`였다면 `realms_active`를 1 감소시키고, `state = "DESTROYED"`로 변경합니다.
   - 렐름에 매핑되어 있던 모든 과립의 `realm_id`를 `None`으로 해제하고, 매핑된 `ripas`를 `"DESTROYED"`로 갱신합니다.
   - `event_logs`에 `RMI_REALM_DESTROY_SUCCESS`를 기록합니다.

8. **`RMI_GRANULE_UNDELEGATE` (`time`, `pa`)**:
   - 물리 과립을 Non-secure World로 반환합니다.
   - 검증 조건:
     - 과립의 상태가 `"REALM"`이어야 합니다.
     - 과립이 여전히 활성 Realm에 매핑되어 있으면(`realm_id is not None`) 반환할 수 없습니다 (`RMI_ERROR`).
   - 검증 통과 시:
     - 커널 보안 규정에 따라 메모리의 잔존 기밀 데이터를 완벽히 제거하기 위해 **메모리 스크러빙(`scrubbed = True`)**을 수행합니다.
     - 상태를 `"NON_SECURE"`로 변경하고, `undelegated_granules_count`를 1 증가시킵니다.
     - `event_logs`에 `RMI_GRANULE_UNDELEGATE_SUCCESS`를 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {},
  "trace": [
    {"time": 10, "type": "RMI_GRANULE_DELEGATE", "pa": "0x10000"},
    {"time": 20, "type": "RMI_REALM_CREATE", "realm_id": "realm_01"},
    {"time": 30, "type": "RMI_RTT_MAP", "realm_id": "realm_01", "ipa": "0x40000000", "pa": "0x10000", "data_hash": "boot_code_v1"},
    {"time": 40, "type": "RMI_REALM_ACTIVATE", "realm_id": "realm_01"},
    {"time": 50, "type": "HOST_ACCESS_ATTEMPT", "pa": "0x10000", "access_type": "READ"}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"delegated_granules_count":1,"undelegated_granules_count":0,"gpc_faults_blocked":1,"realms_created":1,"realms_active":1},"realms":{"realm_01":{"state":"ACTIVE","measurement":"3203f569b9f93318","mapped_pages_count":1}},"granules":{"0x10000":{"state":"REALM","realm_id":"realm_01","scrubbed":false}},"security_logs":[{"time":40,"action":"REALM_SEALED_AND_ACTIVATED","realm_id":"realm_01","final_measurement":"3203f569b9f93318"},{"time":50,"action":"GPC_FAULT_BLOCKED","pa":"0x10000","access_type":"READ","granule_state":"REALM","realm_id":"realm_01"}],"event_logs":[{"time":10,"event":"RMI_GRANULE_DELEGATE_SUCCESS","pa":"0x10000","new_state":"REALM"},{"time":20,"event":"RMI_REALM_CREATE_SUCCESS","realm_id":"realm_01","initial_measurement":"1f06ae9ae5fa1d75"},{"time":30,"event":"RMI_RTT_MAP_SUCCESS","realm_id":"realm_01","ipa":"0x40000000","pa":"0x10000","new_measurement":"3203f569b9f93318"},{"time":40,"event":"RMI_REALM_ACTIVATE_SUCCESS","realm_id":"realm_01","final_measurement":"3203f569b9f93318"},{"time":50,"event":"HARDWARE_GPC_FAULT","pa":"0x10000","status":"TERMINATED_BY_GPC"}]}
```
