# [CS Deep Dive] 쿠버네티스 AWS VPC CNI와 IP 할당 아키텍처 (Prefix Delegation & Warm Targets)

## 1. AWS VPC CNI의 철학과 태생적 문제점

Kubernetes의 표준 네트워크 모델(CNI)은 "모든 파드가 NAT 없이 고유한 IP로 서로 직접 통신할 수 있어야 한다"고 규정합니다.

대부분의 오픈소스 CNI(Flannel, Calico)는 노드 간 패킷을 VXLAN이나 Geneve 등의 터널링 프로토콜로 감싸는 **오버레이 네트워크(Overlay Network)** 를 구축하여 VPC 외부 IP와 분리된 가상 IP 대역을 부여합니다.

반면 **AWS VPC CNI (`aws-node`)** 는 AWS VPC 인프라와의 네이티브 통합을 위해 파드에 **실제 VPC 서브넷의 사설 IP(Secondary Private IP)** 를 직접 할당합니다:

```
[ 장점 ]
1. VPC 내부 리소스(RDS, ElastiCache, 온프레미스 DirectConnect)와 파드가 NAT 없이 초고속 직접 통신 가능.
2. AWS Security Group for Pods(파드별 보안 그룹) 적용 가능.
3. 패킷 인캡슐레이션 오버헤드가 없어 네트워크 대역폭 및 CPU 효율 극대화.

[ 단점 및 재앙 ]
1. VPC 서브넷 CIDR IP 고갈 (Subnet Exhaustion).
2. EC2 인스턴스 타입별 ENI 및 보조 IP 개수 제약에 갇혀 노드당 파드 밀도 제한.
3. 파드 스케줄링 시 AWS EC2 API 호출 지연(AttachENI, AssignIP) 및 API Throttling (RequestLimitExceeded).
```

---

## 2. 인스턴스 타입별 ENI 및 IP 계산 공식

AWS EC2 가상머신은 하드웨어 수준에서 장착 가능한 ENI 수와 ENI당 보조 IP 수가 고정되어 있습니다:

$$\text{Max Pods per Node} = (\text{Number of ENIs} \times (\text{IPs per ENI} - 1)) + 2$$

* 각 ENI의 첫 번째 IP는 노드 호스트(인스턴스 자체의 프라이머리 IP)로 예약되므로 파드용으로 쓸 수 없습니다.
* `+2`는 `aws-node` 호스트 네트워킹 및 `kube-proxy`용 오프셋입니다.
* 예: `m5.large` (3 ENIs, 10 IPs/ENI)
  $$\text{Max Pods} = (3 \times (10 - 1)) + 2 = 29 \text{ pods (기본 설정 28 pods)}$$
* 결과적으로 수십 GB의 메모리와 넉넉한 CPU가 남아돌아도, 단지 **ENI 슬롯이 꽉 찼다는 이유로 노드에 파드를 더 이상 띄우지 못하는 심각한 자원 낭비**가 발생합니다.

---

## 3. CNI 튜닝 핵심: WARM_IP_TARGET vs Prefix Delegation

| 구분 | On-Demand (기본값) | WARM_IP_TARGET | Prefix Delegation (/28) |
| :--- | :--- | :--- | :--- |
| **IP 할당 시점** | 파드가 스케줄링된 직후 | 클러스터 기동 시 및 여유분 부족 시 사전 할당 | 노드 기동 시 `/28` (16개 IP) 단위 사전 할당 |
| **파드 기동 지연** | **수초 ~ 수분 (ContainerCreating)** | **0ms (사전 할당된 웜 풀 사용)** | **0ms (사전 할당된 프리픽스 블록 사용)** |
| **EC2 API 부하** | 파드마다 1~2회 API 호출 (극심한 Throttling) | 웜 풀 보충 시 주기적 호출 | **1/16 수준으로 극감 (호출 횟수 93% 절감)** |
| **서브넷 IP 소비** | 필요한 만큼만 정밀 소비 | 웜 타깃만큼 서브넷 IP 선점 낭비 | 16개 단위로 블록 소비 (서브넷 여유 필요) |
| **노드당 파드 밀도** | 기존 한계 (`m5.large`: 28개) | 기존 한계 (`m5.large`: 28개) | **최대 110~250개 파드로 대폭 확장!** |

---

## 4. Prefix Delegation 동작 원리 (`ENABLE_PREFIX_DELEGATION=true`)

AWS VPC는 2021년부터 EC2 인스턴스의 개별 ENI 슬롯에 단일 IP 대신 **`/28` 서브넷(16개 연속 IP)** 을 통째로 할당하는 Prefix Delegation 기능을 제공합니다:

```
[ Traditional Secondary IP Allocation ]
ENI 1: [Slot 1: 10.0.1.10] [Slot 2: 10.0.1.11] ... [Slot 10: 10.0.1.19]
-> 10개 슬롯에 단 9개 파드만 수용 가능!

[ Prefix Delegation Allocation ]
ENI 1: [Slot 1: 10.0.1.16/28 (16 IPs)] [Slot 2: 10.0.1.32/28 (16 IPs)] ...
-> 단 1개 슬롯으로 16개 파드 수용! 9개 슬롯이면 144개 파드 수용!
```

### 주의점 및 베스트 프랙티스
1. **서브넷 프래그멘테이션(단편화) 방지**:
   - Prefix Delegation은 연속된 16개 IP 블록(`/28`)이 필요하므로, 서브넷에 자투리 IP만 남아있으면 프리픽스 할당이 실패할 수 있습니다.
   - 파드 전용 서브넷을 `/20` 이상의 넉넉한 대역으로 설계하거나, Secondary CIDR(100.64.0.0/16 Carrier-Grade NAT)을 EKS 클러스터에 바인딩하여 해결합니다.
2. **`WARM_PREFIX_TARGET=1` 설정**:
   - 불필요하게 많은 프리픽스를 선점하지 않도록 항상 1개의 여유 `/28` 블록만 대기시키도록 설정하여 서브넷 IP 고갈을 방지합니다.
