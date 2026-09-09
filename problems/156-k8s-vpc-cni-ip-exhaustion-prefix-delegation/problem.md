# #156 파드가 50개 떴는데 왜 전부 ContainerCreating에서 멈춰있어요?!: 쿠버네티스 AWS VPC CNI 보조 IP 할당 지연과 WARM_IP_TARGET vs Prefix Delegation

## 1. 실무 장애 시나리오: "타임세일 오픈하자마자 HPA로 뜬 파드들이 5분째 기동되지 않는다고?!"

클라우드 네이티브 이커머스 기업 '젤리마켓'은 AWS EKS(Elastic Kubernetes Service) 클러스터에서 수백 개의 마이크로서비스를 운영하고 있습니다.

오전 10시 한정판 스니커즈 드롭(Drop) 이벤트 오픈과 동시에 트래픽이 폭증하여 주문 서비스의 HPA(Horizontal Pod Autoscaler)가 작동했고, 워커 노드 5대에 걸쳐 총 50개의 신규 파드가 한꺼번에 스케줄링되었습니다.

```
       [ Kubernetes Scheduler ]
                  │ Schedule 50 Pods
                  ▼
       ┌────────────────────────────────────────────────────────┐
       │ Worker Node (Instance: m5.large, Max 3 ENIs, 10 IPs/ENI) │
       │ aws-node (AWS VPC CNI DaemonSet)                       │
       └──────────────────────────┬─────────────────────────────┘
                                  │
          Default Mode            │ No free IP on node!
     (ON_DEMAND / WARM_IP=0)      │ Calls AWS EC2 API per Pod!
                                  ▼
                     [ AWS EC2 API Control Plane ]
                     * AttachNetworkInterface (takes 3,000ms)
                     * AssignPrivateIpAddresses (takes 500ms)
                                  │
                                  ▼
                "RequestLimitExceeded" (API Throttling!)
                Exponential Backoff delay jumps to 5,000ms+
                                  │
                                  ▼
         Pods STUCK in 'ContainerCreating' for 5+ minutes!
         Users receive 504 Gateway Timeout Disasters!
```

그러나 기대와 달리 신규 파드들이 즉시 트래픽을 처리하지 못하고, **무려 3~5분 동안 `ContainerCreating` 상태에 갇혀(Stuck)** 트래픽 처리가 지연되면서 결제 요청 대기열이 터져버렸습니다!

### 근본 원인 분석 (Root Cause)
1. **AWS VPC CNI의 직접 IP 바인딩 구조**:
   - AWS EKS의 공식 CNI인 `aws-node`는 오버레이(VXLAN) 네트워크를 쓰지 않고, 파드마다 실제 AWS VPC 서브넷의 **보조 사설 IP(Secondary Private IP)** 를 부여합니다.
   - 인스턴스 타입마다 장착 가능한 ENI(Elastic Network Interface) 수와 ENI당 IP 슬롯 수가 하드웨어적으로 엄격히 제한됩니다:
     - `m5.large`: 최대 ENI 3개, ENI당 10개 IP (기본 IP 1개 + 보조 IP 9개) $\implies$ 노드당 최대 파드 수 28개.
2. **On-Demand 할당 지연 및 EC2 API Rate Limit (Throttling) 폭탄**:
   - 기본 설정(`cni_mode: ON_DEMAND`, `WARM_IP_TARGET=0`)에서는 파드가 노드에 배치된 *후에야* 비로소 `aws-node`가 AWS EC2 API(`AssignPrivateIpAddresses`, `AttachNetworkInterface`)를 비동기로 호출합니다.
   - ENI 신규 부착은 약 3,000ms, IP 할당은 약 500ms가 소요됩니다.
   - 수십 대의 노드에서 수백 개의 파드가 동시에 뜨면서 **AWS EC2 API Rate Limit (초당 호출 제한)** 에 도달했고, 지수 백오프 페널티(+5,000ms)가 누적되어 파드 1개 뜨는 데 8초~수 분이 걸리는 사태가 벌어졌습니다!
3. **서브넷 CIDR 고갈 참사**:
   - 노드가 3개의 ENI를 꽉 채워 IP를 사전 선점해두면, 실제 파드는 5개만 떠 있어도 서브넷의 `/24`(251개 가용 IP) 풀이 순식간에 고갈되어 신규 노드와 파드가 영구 `Pending`(`SubnetIPExhausted`)으로 폭사합니다.

---

## 2. 구원 아키텍처: VPC CNI 최적화 2대 전략

인프라 플랫폼팀은 EKS CNI 설정을 전면 개편했습니다:

1. **`WARM_IP_TARGET` 버퍼링**:
   - 노드에 항상 $K$개(예: 5개)의 여유 보조 IP 풀을 사전에 확보(Pre-warm)해둡니다.
   - 파드가 스케줄링되는 즉시 **0ms 레이턴시**로 준비된 웜 IP를 즉각 할당하여 `ContainerCreating` 지연을 제거합니다.
2. **Prefix Delegation (`ENABLE_PREFIX_DELEGATION=true`)**:
   - IP를 1개씩 찔끔찔끔 요청하는 대신, AWS VPC가 제공하는 **`/28` IPv4 프리픽스 (16개 연속 IP 블록)** 를 단 1개의 ENI 슬롯에 한 번에 통째로 할당받습니다!
   - 단 1번의 EC2 API 호출로 16개의 파드 IP가 즉시 확보되므로:
     - EC2 API 호출 횟수가 90% 이상 격감하여 API Throttling 완전 소멸!
     - ENI 개수 제약에서 해방되어 노드당 파드 밀도(Pod Density)가 비약적으로 상승!
     - 초고속 버스트 스케일링 환경에서도 평균 0ms 지연으로 파드가 기동됩니다.

당신은 Kubernetes AWS VPC CNI의 인스턴스 ENI/IP 할당, EC2 API 레이트 리밋, 서브넷 CIDR 고갈, 프리픽스 위임을 정밀 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 3. 입력 형식 (JSON)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "cni_mode": "ON_DEMAND",
  "warm_ip_target": 0,
  "subnet_available_ips": 50,
  "nodes": [
    { "node_id": "node-1", "instance_type": "m5.large" }
  ],
  "delays": {
    "eni_attach_ms": 3000,
    "ip_assign_ms": 500,
    "api_throttle_penalty_ms": 5000,
    "api_rate_limit_per_second": 3
  },
  "events": [
    { "time_ms": 0, "action": "SCHEDULE", "pod_id": "pod-0", "node_id": "node-1" },
    { "time_ms": 1000, "action": "TERMINATE", "pod_id": "pod-0" }
  ]
}
```

### 인스턴스 타입 스펙 (하드웨어 제약)
* `t3.medium`: `max_enis: 3`, `ips_per_eni: 6` (보조 IP 슬롯: ENI당 5개)
* `m5.large`: `max_enis: 3`, `ips_per_eni: 10` (보조 IP 슬롯: ENI당 9개)
* `c5.xlarge`: `max_enis: 4`, `ips_per_eni: 15` (보조 IP 슬롯: ENI당 14개)
* `m5.2xlarge`: `max_enis: 4`, `ips_per_eni: 30` (보조 IP 슬롯: ENI당 29개)

---

## 4. 출력 형식 (JSON)

표준 출력(stdout)으로 들여쓰기 2칸(`indent=2`)이 적용된 JSON 객체를 출력합니다:

```json
{
  "cni_mode": "ON_DEMAND",
  "total_pods_requested": 15,
  "running_pods": 15,
  "failed_pods": 0,
  "remaining_subnet_ips": 35,
  "metrics": {
    "total_api_calls": 16,
    "throttled_calls": 12,
    "eni_attach_calls": 1,
    "avg_provisioning_latency_ms": 4700.0,
    "max_provisioning_latency_ms": 8500.0,
    "p95_provisioning_latency_ms": 8500.0
  },
  "diagnosis": "CRITICAL: EC2 API rate limit exceeded (12 throttled calls). Pods suffered provisioning delays up to 8500.0ms due to on-demand ENI/IP allocation."
}
```

### 진단 메시지(diagnosis) 판정 규칙
1. `failed_pods > 0`일 때:
   * 서브넷 IP 고갈: `"CRITICAL: Subnet CIDR IP exhaustion! {N} pods failed to schedule because the VPC subnet has no remaining IP addresses."`
   * 노드 ENI 한계: `"CRITICAL: Node ENI capacity limit reached! {N} pods failed because node instance type exceeded maximum ENIs and secondary IPs."`
2. `failed_pods == 0`일 때:
   * `ON_DEMAND` 모드:
     * API Throttling 발생 시: `"CRITICAL: EC2 API rate limit exceeded ({N} throttled calls). Pods suffered provisioning delays up to {max_latency:.1f}ms due to on-demand ENI/IP allocation."`
     * 지연만 발생 시: `"WARNING: On-demand IP allocation caused pod startup latency of {max_latency:.1f}ms. Consider WARM_IP_TARGET or Prefix Delegation."`
     * 지연 없음: `"ON_DEMAND allocation succeeded without delay."`
   * `WARM_IP` 모드: `"WARM_IP_TARGET maintained warm buffer. Pods scheduled with average latency {avg_latency:.1f}ms ({N} throttled API calls)."`
   * `PREFIX_DELEGATION` 모드: `"OPTIMAL: AWS VPC CNI Prefix Delegation achieved zero-delay pod provisioning and minimal EC2 API overhead via /28 prefix blocks."`
