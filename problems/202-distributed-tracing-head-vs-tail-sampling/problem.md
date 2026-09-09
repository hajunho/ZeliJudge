# 분산 추적(Distributed Tracing): OpenTelemetry Head-based vs Tail-based 샘플링과 트레이스 버퍼 메모리 제어

## 문제 배경 및 개요
글로벌 초대형 이커머스 및 핀테크 플랫폼은 수백 개의 마이크로서비스(API Gateway, Auth, Catalog, Cart, Payment, Fraud, Notification 등)가 상호 호출하며 초당 수십만 개의 분산 추적 스팬(Span)을 쏟아냅니다.
초당 수십만 개의 트레이스를 100% 무차별 수집하면 하루에 페타바이트 단위의 스토리지 비용과 막대한 네트워크 대역폭, 스토리지 백엔드(Elasticsearch, ClickHouse, Tempo)의 과부하가 발생합니다.

이 비용을 줄이기 위해 많은 조직이 **헤드 기반 샘플링(Head-based Sampling)**을 도입합니다:
- 클라이언트 요청이 최초 진입하는 인그레스/API 게이트웨이(Root Span)에서 단순 확률(예: 1% 또는 5%)로 샘플링 여부를 결정합니다.
- 결정된 샘플링 플래그(`sampled=true` 또는 `sampled=false`)는 W3C TraceContext 헤더(`traceparent`)를 통해 다운스트림 서비스로 전파됩니다.

그러나 블랙 프라이데이 프로모션 도중 결제 게이트웨이에서 특정 은행사 연동 타임아웃으로 수만 건의 결제 승인 실패(HTTP 500/504)와 극심한 p99 지연 스파이크(3500ms)가 발생했을 때 **치명적인 관측성 붕괴(Observability Collapse)**가 발생했습니다:
1. **장애 트레이스 전량 증발 참사 (`HEAD_BASED_SAMPLING_CRITICAL_TRACE_LOSS`)**:
   - 루트 서비스 진입 시점에는 이 요청이 10ms 만에 끝날지, 3500ms 동안 멈출지, 리프(Leaf) 데이터베이스에서 500 에러를 뿜을지 전혀 알 수 없습니다.
   - 결과적으로 95%~99%의 장애 트레이스가 앞단에서 '정상 요청'과 동일한 확률로 버려져, SRE 팀이 장애 원인을 분석하려 대시보드를 열었을 때 *"No traces found for this error"* 라는 절망적인 화면만 마주하게 됩니다.
2. **단순 100% 수집 전환 시 버퍼 OOM 연쇄 크래시 (`TRACE_BUFFER_OOM_COLLAPSE`)**:
   - 개발팀이 급히 OpenTelemetry Collector의 샘플링을 100% 수집으로 변경하자, 수집기 인메모리 버퍼가 트래픽 서지를 견디지 못하고 폭발하여 OOM-Killer에 의해 전량 강제 종료되었습니다.

이를 완벽하게 해결하기 위해 현대 클라우드 네이티브 아키텍처는 **테일 기반 샘플링(Tail-based Sampling)**과 **메모리 리미터(Memory Limiter Flow Control)**를 결합합니다:
- **평가 대기 윈도우 (`decision_wait_ms`)**: 수집기는 유입되는 스팬들을 즉시 폐기하거나 전송하지 않고, `trace_id`를 키로 하여 인메모리 버퍼에 임시 적재합니다. 전체 분산 트레이스가 완료될 때까지 기다린 후 트레이스 전체를 사후 평가합니다.
- **다중 복합 샘플링 정책 (Composite Sampling Policies)**:
  - **에러 정책 (Error Policy)**: 트레이스 내 어느 자식 스팬이라도 `status_code == "ERROR"` 또는 `http_status >= 500`이면 **100% 무조건 캡처**!
  - **지연시간 정책 (Latency Policy)**: 트레이스 총 소요 시간(`max(end_time) - min(start_time)`)이 임계치(`latency_threshold_ms`) 이상이면 **100% 무조건 캡처**!
  - **정상 요청 정책 (Normal Policy)**: 정상 트레이스에 대해서만 희소 확률로 샘플링하여 스토리지 비용을 절감.
- **메모리 리미터 (Memory Limiter & Early Eviction)**: 인메모리 트레이스 버퍼가 상한선(`max_buffer_traces`)에 도달하면, OOM으로 크래시되는 대신 가장 오래된 미완료 정상 트레이스를 조기 평가/축출하여 무중단 라인 레이트를 보장합니다 (`OPTIMAL_TAIL_BASED_SAMPLING_TUNED`).

당신은 OpenTelemetry Collector의 핵심 샘플링 파이프라인을 시뮬레이션하여, 헤드 기반 샘플링의 장애 트레이스 유실과 테일 기반 샘플링의 지연 평가 및 메모리 제어 메커니즘을 정확히 구현하고 진단해야 합니다.

---

## 시스템 동작 규칙 및 상태 머신

### 1. 헤드 기반 샘플링 (`mode == "head_based"`)
- 모든 스팬은 `trace_id`별로 묶이며, 루트 스팬에 기록된 `head_sampled` 플래그에 따라 트레이스 전체의 수집 여부가 결정됩니다.
- `head_sampled == true`이면 트레이스 수집(`sampled_traces_count += 1`), 그렇지 않으면 폐기(`dropped_traces_count += 1`)됩니다.
- 사후 분석 시 트레이스 내에 에러(`status_code == "ERROR"` 또는 `http_status >= 500`)가 있거나 총 지연시간이 `latency_threshold_ms` 이상임에도 불구하고 폐기된 경우, 각각 `error_traces_lost += 1`, `slow_traces_lost += 1`로 집계됩니다.

### 2. 테일 기반 샘플링 (`mode == "tail_based"`)
- 스팬들은 도착 시간(`arrival_time_ms`, 없으면 `start_time_ms`) 순으로 수집기 버퍼에 유입됩니다.
- 각 트레이스는 `trace_id`별로 인메모리 버퍼에 적재되며, 트레이스의 첫 스팬 도착 시간(`first_arrival_ms`)을 기록합니다.
- **메모리 리미터 검사**:
  - 신규 트레이스 유입 시 현재 버퍼의 활성 트레이스 수가 `max_buffer_traces`에 도달한 경우:
    - `memory_limiter_enabled == false`이면 버퍼 오버플로우가 발생하여 `buffer_overflow_occurred = True`로 기록됩니다.
    - `memory_limiter_enabled == true`이면 버퍼 내 가장 오래된 트레이스(`first_arrival_ms`가 가장 작은 트레이스)를 조기 평가(Early Eviction)하여 버퍼에서 방출하고 의사결정을 완료합니다.
- **의사결정 대기 시간 (`decision_wait_ms`) 만료**:
  - 현재 시간(`current_time_ms`) 기준으로 `current_time_ms - first_arrival_ms >= decision_wait_ms`를 만족하는 트레이스는 버퍼에서 꺼내어 샘플링 정책을 평가합니다:
    1. **Error Rule**: 트레이스에 속한 스팬 중 하나라도 `status_code == "ERROR"` 또는 `http_status >= 500`이면 수집 (`sampled = True`).
    2. **Latency Rule**: 트레이스의 총 지속 시간(`max(end_time_ms) - min(start_time_ms)`)이 `latency_threshold_ms` 이상이면 수집 (`sampled = True`).
    3. **Normal Rule**: 위 조건에 해당하지 않는 정상 트레이스는 기본 폐기 (또는 `tail_sample_override`에 따름).
- 유입이 종료된 후 버퍼에 남아있는 잔여 트레이스들도 동일한 정책으로 일괄 평가 및 방출됩니다.

---

## 판정 기준 (System Status)

1. `TRACE_BUFFER_OOM_COLLAPSE`:
   - `mode == "tail_based"`에서 `memory_limiter_enabled == false` 상태로 트레이스 버퍼가 `max_buffer_traces` 한도를 초과하여 수집기가 OOM으로 크래시된 상태.
2. `HEAD_BASED_SAMPLING_CRITICAL_TRACE_LOSS`:
   - `mode == "head_based"`에서 에러 트레이스 또는 고지연 트레이스가 단 1건이라도 유실된 상태 (`error_traces_lost > 0` 또는 `slow_traces_lost > 0`).
3. `OPTIMAL_TAIL_BASED_SAMPLING_TUNED`:
   - 테일 기반 샘플링이 정상 작동하여 모든 에러 및 고지연 트레이스를 100% 수집하고, 메모리 리미터를 통해 버퍼가 안전하게 통제된 상태.

---

## 입력 형식
표준 입력(`sys.stdin`)으로 다음 필드를 갖는 단일 JSON 객체가 주어집니다:
- `collector_config`: 수집기 설정
  - `mode`: `"head_based"` 또는 `"tail_based"`
  - `head_sample_rate`: 헤드 샘플링 비율 (실수, 예: 0.05)
  - `decision_wait_ms`: 테일 샘플링 평가 대기 윈도우 시간 (밀리초, 실수)
  - `latency_threshold_ms`: 고지연 트레이스 판정 임계치 (밀리초, 실수)
  - `max_buffer_traces`: 인메모리 버퍼 최대 보관 가능 트레이스 수 (정수)
  - `memory_limiter_enabled`: 메모리 리미터 활성화 여부 (boolean)
- `spans`: 분산 트레이스 스팬 객체 목록
  - `trace_id`: 트레이스 고유 식별자 문자열
  - `span_id`: 스팬 고유 식별자 문자열
  - `start_time_ms`: 스팬 시작 시간 (밀리초, 실수)
  - `end_time_ms`: 스팬 종료 시간 (밀리초, 실수)
  - `status_code`: 상태 코드 (`"OK"` 또는 `"ERROR"`)
  - `http_status`: HTTP 응답 상태 코드 (정수, 예: 200, 500, 504)
  - `arrival_time_ms`: 수집기 도착 시간 (밀리초, 실수, 생략 시 `start_time_ms`)
  - `head_sampled`: 헤드 샘플링 여부 (boolean, 헤드 기반 모드용)

---

## 출력 형식
표준 출력(`sys.stdout`)으로 다음 필드를 갖는 단일 JSON 객체를 인덴트 2칸(`indent=2`)으로 출력해야 합니다:
- `status`: 판정 결과 문자열 (`HEAD_BASED_SAMPLING_CRITICAL_TRACE_LOSS` | `TRACE_BUFFER_OOM_COLLAPSE` | `OPTIMAL_TAIL_BASED_SAMPLING_TUNED`)
- `metrics`:
  - `total_spans_received`: 수신된 총 스팬 수
  - `total_traces`: 고유 트레이스 수
  - `sampled_traces_count`: 최종 수집 결정된 트레이스 수
  - `dropped_traces_count`: 최종 폐기 결정된 트레이스 수
  - `sampling_ratio_pct`: 전체 트레이스 중 수집 비율 (소수점 1자리 반올림)
  - `error_traces_total`: 전체 에러 트레이스 건수
  - `error_traces_captured`: 성공적으로 수집된 에러 트레이스 건수
  - `error_traces_lost`: 폐기되어 유실된 에러 트레이스 건수
  - `error_capture_pct`: 에러 트레이스 수집율 백분율 (소수점 1자리)
  - `slow_traces_total`: 전체 고지연 트레이스 건수
  - `slow_traces_captured`: 성공적으로 수집된 고지연 트레이스 건수
  - `slow_traces_lost`: 폐기되어 유실된 고지연 트레이스 건수
  - `slow_capture_pct`: 고지연 트레이스 수집율 백분율 (소수점 1자리)
  - `peak_buffer_traces`: 인메모리 버퍼에 동시 적재된 최대 트레이스 수
- `root_cause_analysis`: 한국어 원인 분석 및 아키텍처 진단 메시지
