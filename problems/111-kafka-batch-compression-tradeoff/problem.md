# 카프카 배치 압축 알고리즘 4대장과 실무 트레이드오프 (Kafka Batch Compression Tradeoff)

## 문제 설명

대규모 데이터 스트리밍 플랫폼인 **아파치 카프카(Apache Kafka)**에서 초당 수십만~수백만 건의 이벤트를 처리할 때 가장 중요한 튜닝 포인트 중 하나는 바로 **배치(Batch)와 압축(Compression)**입니다.

많은 주니어 개발자가 "메시지를 보낼 때마다 개별 압축한다"고 생각하지만, 카프카 프로듀서는 메모리 버퍼(`RecordAccumulator`)에 레코드를 모아 **레코드 배치(`RecordBatch`) 단위로 한꺼번에 압축**합니다. 이렇게 하면 공통 JSON 키나 텍스트 패턴이 사전에 등록되어 엄청난 압축률을 달성할 수 있습니다.

하지만 압축 알고리즘마다 **압축률 vs CPU 소모량 vs 압축 해제 속도**의 트레이드오프가 극명하게 갈립니다:
1. **`NONE`**: 압축을 전혀 하지 않습니다. CPU 소모는 0이지만 네트워크 대역폭과 디스크 용량을 어마어마하게 낭비하여 **네트워크 병목(`NETWORK_BOUND`)**을 초래합니다.
2. **`SNAPPY`**: 구글이 개발한 초경량 압축 코덱입니다. 압축률은 중간이지만 CPU 소모가 극히 적습니다.
3. **`LZ4`**: 압축률도 우수하고 무엇보다 **압축 해제 속도가 번개처럼 빠른 카프카 실무의 사실상 표준(De facto Standard)** 코덱입니다. 대부분의 고처리량 환경에서 CPU와 네트워크가 균형(`BALANCED`)을 이룹니다.
4. **`GZIP`**: 압축률이 극도로 높지만, CPU 연산 비용이 너무 커서 프로듀서가 메시지를 채 보내기도 전에 CPU 100%를 찍고 **CPU 병목(`CPU_BOUND`)**에 빠집니다.
5. **`ZSTD` (Zstandard)**: 메타(Facebook)가 개발한 차세대 압축 알고리즘으로, 압축 레벨(`1~9`, 기본값 3)을 유연하게 튜닝할 수 있습니다.

또한, 브로커 설정의 `compression.type`이 `producer`가 아닌 다른 코덱으로 강제 지정되어 프로듀서의 코덱과 불일치할 경우, 브로커가 매 배치마다 **압축 해제 후 재압축(Recompression)**을 감행하여 브로커 CPU가 폭발하는 **치명적 장애(`BROKER_DEGRADED`)**가 발생합니다.

당신은 카프카 프로듀서 및 브로커의 배치 압축 파이프라인을 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 시뮬레이션 규칙 및 계산 공식

### 1. 레코드 배치 수집 및 플러시 규칙
- 프로듀서는 하나의 활성 배치(`current_batch`)를 관리합니다.
- 레코드가 추가될 때:
  - 현재 배치가 비어있지 않고, `(현재 배치 누적 바이트 + 새 레코드 바이트) > batch_size`인 경우:
    - **즉시 현재 배치를 마감(Flush)**하여 압축 및 브로커 전송을 수행합니다.
    - 이후 새 배치를 열고 새 레코드를 추가합니다.
  - 레코드를 추가한 뒤 `현재 배치 누적 바이트 == batch_size`가 되면 즉시 해당 배치를 마감합니다.
- `FLUSH` 명령이 호출되면 현재 열려있는 배치에 데이터가 있을 경우 즉시 마감합니다.

### 2. 배치 압축 및 CPU 계산 공식
각 배치는 데이터 페이로드 크기 $S_{raw}$ (바이트)와 가중 평균 중복률 $R \in [0, 100]$ (%)을 가집니다.  
(가중 중복률: $R_{batch} = \frac{\sum (\text{record\_size} \times \text{redundancy})}{S_{raw}}$)  
배치 단위 크기 $K = \lceil S_{raw} / 1024.0 \rceil$ (최소 1 KB 단위 올림)

모든 배치는 압축 여부와 무관하게 20바이트의 카프카 레코드배치 엔벨로프 헤더(`batch_envelope = 20`)를 가집니다:
- 배치의 원본 총 바이트 = $S_{raw} + 20$
- 배치의 네트워크 전송 총 바이트 = $S_{comp} + 20$

각 코덱별 압축 후 페이로드 크기 $S_{comp}$ 및 CPU 소모량:
- **`NONE`**:
  - $S_{comp} = S_{raw}$
  - $CPU_{comp} = 0$, $CPU_{decomp} = 0$
- **`SNAPPY`**:
  - $C_{eff} = 1.0 - (R / 100.0) \times 0.55$
  - $S_{comp} = \min(S_{raw}, \lfloor S_{raw} \times C_{eff} \rfloor) + 24$ (프레이밍 오버헤드 24B)
  - $CPU_{comp} = K \times 6$, $CPU_{decomp} = K \times 2$
- **`LZ4`**:
  - $C_{eff} = 1.0 - (R / 100.0) \times 0.65$
  - $S_{comp} = \min(S_{raw}, \lfloor S_{raw} \times C_{eff} \rfloor) + 16$ (프레이밍 오버헤드 16B)
  - $CPU_{comp} = K \times 8$, $CPU_{decomp} = K \times 2$
- **`GZIP`**:
  - $C_{eff} = 1.0 - (R / 100.0) \times 0.80$
  - $S_{comp} = \min(S_{raw}, \lfloor S_{raw} \times C_{eff} \rfloor) + 32$ (프레이밍 오버헤드 32B)
  - $CPU_{comp} = K \times 45$, $CPU_{decomp} = K \times 15$
- **`ZSTD`** (압축 레벨 $L \in [1, 9]$, 기본값 3):
  - $E = 0.70 + (L \times 0.02)$
  - $C_{eff} = 1.0 - (R / 100.0) \times E$
  - $S_{comp} = \min(S_{raw}, \lfloor S_{raw} \times C_{eff} \rfloor) + 20$ (프레이밍 오버헤드 20B)
  - $CPU_{comp} = K \times (10 + L \times 3)$, $CPU_{decomp} = K \times 4$

> 프로듀서는 배치 마감 시 해당 프로듀서 코덱의 $CPU_{comp}$를 누적합니다.

### 3. 브로커 처리 및 리컴프레션(Recompression)
- 브로커 코덱이 `PRODUCER`이거나, 프로듀서 코덱과 동일한 경우:
  - 브로커는 Zero-Copy로 바이트를 그대로 디스크에 저장합니다. (브로커 CPU 0, 재압축 횟수 0)
- 브로커 코덱이 프로듀서 코덱과 다른 경우 (**코덱 불일치 장애**):
  - 브로커는 프로듀서 코덱으로 압축 해제 ($CPU_{decomp}(\text{producer})$ 소모)
  - 브로커는 자신의 코덱으로 재압축 ($CPU_{comp}(\text{broker})$ 소모)
  - 브로커 CPU 누적 += $(\text{해제 CPU} + \text{재압축 CPU})$
  - 브로커 재압축 횟수 누적 += 1

### 4. 병목(Bottleneck) 판단 기준
- 정규화된 네트워크 부하: $N_{norm} = \text{total\_wire\_bytes} / 1000.0$
- 정규화된 CPU 부하: $C_{norm} = \text{producer\_cpu\_units} / 20.0$
- 판정 순서:
  1. `broker_recompressions > 0`인 경우: `BROKER_DEGRADED`
  2. $N_{norm} > 2.0 \times C_{norm}$인 경우: `NETWORK_BOUND`
  3. $C_{norm} > 2.0 \times N_{norm}$인 경우: `CPU_BOUND`
  4. 그 외의 경우: `BALANCED`

---

## 명령어 명세

모든 명령어는 표준 입력(stdin)으로 한 줄씩 주어지며, 빈 줄이나 `#`으로 시작하는 주석은 무시합니다.

1. **`PRODUCER_CONFIG batch_size=<int> codec=<str> [zstd_level=<int>]`**
   - 프로듀서 설정을 변경합니다. (기본값: `batch_size=16384`, `codec=NONE`, `zstd_level=3`)
   - 기존 열려있던 활성 배치에 데이터가 있다면 이전 설정으로 즉시 플러시합니다.
   - 출력:
     - 코덱이 ZSTD인 경우: `PRODUCER_CONFIG_OK batch_size=<B> codec=ZSTD level=<L>`
     - 그 외: `PRODUCER_CONFIG_OK batch_size=<B> codec=<CODEC>`

2. **`BROKER_CONFIG codec=<str> [zstd_level=<int>]`**
   - 브로커의 저장 코덱 정책을 설정합니다. (기본값: `PRODUCER`)
   - 출력: `BROKER_CONFIG_OK codec=<CODEC>`

3. **`PRODUCE count=<int> size=<int> redundancy=<int>`**
   - 크기가 `size`바이트이고 중복률이 `redundancy`%인 레코드를 `count`개 순차 발행합니다.
   - 출력: `PRODUCE_OK records=<count> total_raw_bytes=<count*size>`

4. **`FLUSH`**
   - 현재 활성 배치가 비어있지 않다면 즉시 마감하여 브로커로 전송합니다.
   - 출력:
     - 마감된 레코드가 있는 경우: `FLUSH_OK flushed_records=<N> flushed_raw_bytes=<bytes>`
     - 활성 배치가 비어있었던 경우: `FLUSH_OK idle`

5. **`REPORT`**
   - 현재까지의 누적 지표를 리포트합니다.
   - 압축률(`COMPRESSION_RATIO`)은 `total_wire_bytes / total_raw_bytes`를 소수점 4자리까지 포맷팅합니다. (총 원본 바이트가 0이면 1.0000)
   - 출력 형식:
     ```
     --- KAFKA_METRICS_REPORT ---
     TOTAL_RECORDS: <int>
     TOTAL_BATCHES: <int>
     RAW_PAYLOAD_BYTES: <int>
     TOTAL_RAW_BYTES: <int>
     TOTAL_WIRE_BYTES: <int>
     COMPRESSION_RATIO: <float:.4f>
     PRODUCER_CPU_UNITS: <int>
     BROKER_CPU_UNITS: <int>
     BROKER_RECOMPRESSIONS: <int>
     BOTTLENECK: <CPU_BOUND|NETWORK_BOUND|BALANCED|BROKER_DEGRADED>
     --- END_REPORT ---
     ```

6. **`RESET`**
   - 모든 설정과 누적 지표를 초기 상태로 리셋합니다.
   - 출력: `RESET_OK`

---

## 입출력 예시

### 예시 입력
```
PRODUCER_CONFIG batch_size=4096 codec=NONE
BROKER_CONFIG codec=PRODUCER
PRODUCE count=4 size=1024 redundancy=80
REPORT
```

### 예시 출력
```
PRODUCER_CONFIG_OK batch_size=4096 codec=NONE
BROKER_CONFIG_OK codec=PRODUCER
PRODUCE_OK records=4 total_raw_bytes=4096
--- KAFKA_METRICS_REPORT ---
TOTAL_RECORDS: 4
TOTAL_BATCHES: 1
RAW_PAYLOAD_BYTES: 4096
TOTAL_RAW_BYTES: 4116
TOTAL_WIRE_BYTES: 4116
COMPRESSION_RATIO: 1.0000
PRODUCER_CPU_UNITS: 0
BROKER_CPU_UNITS: 0
BROKER_RECOMPRESSIONS: 0
BOTTLENECK: NETWORK_BOUND
--- END_REPORT ---
```
