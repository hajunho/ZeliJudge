# 리눅스 Cgroup v2 메모리 컨트롤러와 PSI(Pressure Stall Information) 아키텍처

## 1. Cgroup v1의 구조적 한계와 Cgroup v2의 단일 계층 혁신

리눅스 커널 2.6 대에 도입된 Cgroup v1은 서브시스템(cpu, memory, blkio 등)마다 서로 다른 임의의 계층 트리(Multi-Hierarchy)를 구성할 수 있었습니다. 이로 인해 다음과 같은 치명적 아키텍처 결함이 발생했습니다:
1. **페이지 캐시와 블록 I/O의 분리**: 쓰기 버퍼에 저장된 더티 페이지 캐시는 `memory` cgroup에 속하지만, 플러시 스레드가 이를 디스크에 기록할 때 어느 `blkio` cgroup의 대역폭으로 차감해야 할지 추적할 수 없는 문제.
2. **단일 임계값(limit_in_bytes)의 경직성**: 시스템 여유 메모리가 풍부함에도 `limit`에 닿으면 즉시 OOM이 발생하거나, 반대로 메모리 압박 상황에서 보호선(Protection Watermark)이 없어 핵심 프로세스의 캐시가 약탈당하는 문제.

Cgroup v2(Unified Hierarchy)는 모든 컨트롤러를 단일 프로세스 트리에 통합하고, 메모리 컨트롤러에 **다단계 워터마크(`min`, `low`, `high`, `max`)**를 도입하여 부드러운 완충과 절대 보호를 동시에 달성했습니다.

---

## 2. 4단계 메모리 워터마크 수학적 모델

| 인터페이스 | 성격 | 동작 및 커널 회수 정책 |
|---|---|---|
| `memory.min` | 절대적 보호 (Hard Protection) | 시스템 OOM 직전이라도 절대 회수하지 않음 ($R_i = 0$) |
| `memory.low` | 최선 노력 보호 (Soft Protection) | 미보호 메모리($\sum \text{excess} > 0$)가 있는 한 회수 면제. 비상 시에만 비례 침투 |
| `memory.high` | 스로틀링 임계치 (Throttling Watermark) | 초과 시 유저스페이스 복귀 지연 부과 및 선제적 동기 회수 수행 |
| `memory.max` | 절대적 한계 (Hard Limit) | 직접 회수 실패 시 OOM Killer 즉시 격발 |

### memory.high 스로틀링 지연 계산:
$$\text{overshoot\\_pct} = \frac{\text{usage} - \text{high}}{\text{high}} \times 100$$
$$\text{delay\\_ms} = \min(\text{max\\_throttle\\_ms}, \text{round}(\text{overshoot\\_pct} \times \text{throttle\\_factor}))$$

---

## 3. PSI (Pressure Stall Information) 수학과 SRE 조기 경보

기존의 CPU 점유율이나 메모리 사용률($\%$)은 **"리소스 부족으로 인해 실제 작업이 얼마나 멈췄는가?"**를 알려주지 못합니다. PSI는 작업 정체 시간을 0.0~100.0%의 정량적 손실 지표로 계측합니다:

- **`some`**: 실행 가능한 스레드 중 최소 1개 이상이 메모리 I/O(페이지 폴트, 스왑, 다이렉트 리클레임)로 블로킹된 시간 비율.
- **`full`**: 모든 활성 스레드가 동시에 메모리에 묶여 CPU가 완전히 공회전(완전 마비)한 시간 비율.

10초 이동평균(EWMA) 공식:
$$\text{avg10}(t) = \alpha \cdot \text{sample}(t) + (1 - \alpha) \cdot \text{avg10}(t-1) \quad (\alpha = 1 - e^{-1/10} \approx 0.09516)$$

SRE와 쿠버네티스 오토스케일러(Keda, Custom HPA)는 PSI 지표를 모니터링하여 `full.avg10 > 20%` 또는 `some.avg10 > 35%` 도달 시 OOM Killer가 프로세스를 사살하기 전에 선제적으로 팟을 스케일아웃하거나 저우선순위 캐시를 비우는 자동 치유 루프를 구축할 수 있습니다.
