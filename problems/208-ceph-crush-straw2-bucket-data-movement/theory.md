# 분산 스토리지 Ceph: CRUSH 알고리즘, Straw vs Straw2 버킷과 데이터 이동 최소화

## 1. 개요: 메타데이터 없는 분산 스토리지와 CRUSH 혁신

전통적인 대규모 분산 파일 시스템(HDFS NameNode, Lustre MDS, Google GFS Master)은 어떤 파일 청크나 오브젝트가 어떤 스토리지 노드(디스크)에 저장되어 있는지를 중앙 메타데이터 서버의 룩업 테이블(Lookup Table)에 기록하여 관리했습니다.

그러나 수천 대의 스토리지 서버와 수만 개의 디스크 드라이브, 수십억 개의 오브젝트를 수용하는 페타바이트~엑사바이트 규모에서는 **중앙 메타데이터 서버의 메모리 용량 및 네트워크 I/O가 절대적인 병목(Single Point of Bottleneck)**이자 단일 장애점(SPOF)이 됩니다.

Ceph(Sage Weil et al., 2006)는 중앙 메타데이터 테이블을 완전히 제거하고, 수학적 의사 난수 해시 함수를 통해 데이터의 위치를 클라이언트가 직접 계산하는 **CRUSH(Controlled Replication Under Scalable Hashing)** 알고리즘을 발명했습니다:

$$\text{OSD List} = \text{CRUSH}(x, \text{rule}, \text{cluster\_map})$$

여기서 $x$는 배치 그룹(Placement Group, PG) ID이며, 클라이언트는 서버에 위치를 질의할 필요 없이 로컬 CPU에서 $1\,\mu\text{s}$ 만에 $R$개의 복제본이 저장될 OSD 목록을 즉시 결정합니다.

---

## 2. 계층적 클러스터 맵과 장애 도메인 격리 (Failure Domain Isolation)

물리적 데이터센터는 전원, 네트워크 스위치, 랙 단위의 집단 장애 위험을 내포합니다. 단일 랙의 ToR(Top-of-Rack) 스위치가 고장 나면 해당 랙의 OSD 수십 개가 동시에 오프라인이 됩니다.

CRUSH는 데이터센터의 물리적 토폴로지를 계층적 트리 구조(Tree Hierarchy)로 모델링합니다:

```
                  ┌──────────────┐
                  │  root: default│
                  └───────┬──────┘
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
   ┌───────────┐    ┌───────────┐    ┌───────────┐
   │  rack-0   │    │  rack-1   │    │  rack-2   │  <=== Failure Domain (장애 도메인)
   └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
     ┌───┴───┐        ┌───┴───┐        ┌───┴───┐
     ▼       ▼        ▼       ▼        ▼       ▼
  [osd.0] [osd.1]  [osd.4] [osd.5]  [osd.8] [osd.9]
```

- **`step chooseleaf type rack`**: $R=3$ 복제본을 선택할 때, CRUSH는 먼저 서로 다른 랙(`rack-0`, `rack-1`, `rack-2`)을 1개씩 선택한 뒤, 각 랙 내부에서 OSD를 1개씩 선출합니다.
- 이로써 단일 랙 전체가 정전되더라도 나머지 2개 랙에 온전한 복제본이 상주하므로 $100\%$ 무중단 가용성을 달성합니다.

---

## 3. 버킷(Bucket) 알고리즘의 진화와 Classic Straw의 비극

CRUSH 트리의 각 내부 노드(Root, Rack, Host)는 자식 항목들을 담고 있는 **버킷(Bucket)**입니다. 자식 항목들 중 하나를 의사 난수로 공정하게 선출하는 알고리즘은 4세대에 걸쳐 발전했습니다:

1. **Uniform Bucket**: 모든 자식의 용량(가중치)이 동일할 때 사용. $O(1)$ 속도이지만 OSD 추가 시 거의 모든 PG가 재배치됨.
2. **List Bucket**: 연결 리스트 구조. 헤드에 추가할 때는 효율적이나 중간 항목 삭제 시 대규모 데이터 이동 발생.
3. **Tree Bucket**: 이진 트리 가중치 합산. $O(\log n)$ 탐색 속도를 제공하지만 가중치 변경 시 서브트리 간 데이터 요동 발생.
4. **Straw Bucket (Classic Straw)**: 임의의 서로 다른 가중치를 가진 OSD들을 지원하기 위해 도입.

### 3.1 Classic Straw의 수학적 구조
Classic Straw는 "가장 긴 짚(Straw)을 뽑은 항목이 승리한다"는 은유에서 출발했습니다.
항목 $i$의 스트로 팩터 $S_i$는 버킷에 속한 모든 항목들의 가중치를 오름차순 정렬한 뒤 다음과 같은 누적 적분 수식으로 계산되었습니다:

$$S_i = S_{i-1} \times \left( \frac{W_{\text{below}} + w_{i+1}}{W_{\text{below}}} \right)^{\frac{1}{n - 1 - i}}$$

그리고 해시 평가 시:
$$\text{Draw}_i = (\text{hash32}(pg, item_i, r) \ \& \ \text{0xffff}) \times S_i$$

### 3.2 Classic Straw의 치명적 결함: 가중치 결합 왜곡 (Weight Coupling Anomaly)
수식을 자세히 보면, 항목 $i$의 스트로 팩터 $S_i$가 **자신과 무관한 다른 모든 항목들의 가중치($W_{\text{below}}, w_{i+1}$)와 버킷 내 총 항목 수 $n$에 종속**되어 있습니다.

그 결과, 새로운 드라이브 $K$를 1개 추가하거나 특정 드라이브의 가중치를 수정하면:
- 새 드라이브와 전혀 상관없는 기존 OSD $A$와 OSD $B$의 스트로 팩터 비율이 비선형적으로 뒤틀립니다!
- 어떤 PG $x$에 대해 기존에는 $\text{Draw}_A > \text{Draw}_B$였으나, 드라이브 $K$가 추가되자 갑자기 $\text{Draw}_B > \text{Draw}_A$로 대소 관계가 뒤집힙니다!
- **결과**: OSD $A$에 있던 수 테라바이트의 데이터가 아무런 변경도 없었던 OSD $B$로 불필요하게 이동(Unnecessary Movement)합니다.
- 대규모 클러스터에서 디스크 1개를 교체했을 뿐인데, 수백 테라바이트의 무의미한 데이터가 스위치 네트워크를 타고 마구잡이로 교차 이동하는 **백필 폭풍(Backfill Storm)**이 발생하여 서비스가 마비되었습니다.

---

## 4. Straw2: 완벽한 독립성과 최소 데이터 이동의 수학적 증명

Ceph 코어 팀은 Ceph Hammer / Jewel 버전에서 Classic Straw를 완전히 폐기하고 **Straw2 버킷 알고리즘**을 도입했습니다.

### 4.1 Straw2 점수 함수 (Score Function)
Straw2는 통계학의 지수 분포 난수 발생(Exponential Random Variates) 및 가중치 저수지 샘플링(Weighted Reservoir Sampling) 원리를 적용했습니다.

각 항목 $i$에 대해 균등 의사 난수 $U_i \in (0, 1)$를 생성한 뒤, 다음과 같이 점수를 산출합니다:

$$U_i = \frac{(\text{hash32}(pg, item_i, r) \pmod{65535} + 1)}{65536.0}$$

$$\text{Score}_i = \frac{\ln(U_i)}{w_i}$$

여기서 $\ln(U_i) < 0$이므로 $\text{Score}_i$는 음수이며, **$\text{Score}_i$를 최대화(가장 0에 가깝게)하는 항목이 최종 승자**로 선출됩니다.

### 4.2 데이터 이동 최소성(Minimal Data Movement)의 증명
Straw2 수식의 핵심 혁신은 **독립성(Complete Independence)**입니다:

$$\frac{\partial \text{Score}_i}{\partial w_j} = 0 \quad (\forall j \neq i)$$

항목 $i$의 점수 $\text{Score}_i$는 오직 **자신의 가중치 $w_i$와 고유 해시 $U_i$**에 의해서만 결정되며, 다른 어떤 항목의 추가, 삭제, 가중치 변경에도 영향을 받지 않습니다!

#### 증명:
1. 기존에 OSD $A$가 승자였다고 가정합니다:
   $$\text{Score}_A > \text{Score}_B, \quad \text{Score}_A > \text{Score}_C, \quad \dots$$
2. 새로운 OSD $K$가 가중치 $w_K$로 버킷에 추가되었습니다.
3. 이때 기존 OSD들의 점수 $\text{Score}_A, \text{Score}_B, \text{Score}_C$는 단 $1\,\text{bit}$도 변하지 않습니다.
4. 따라서 가능한 결과는 단 두 가지뿐입니다:
   - Case 1: $\text{Score}_K > \text{Score}_A$인 경우 $\rightarrow$ 승자는 $K$가 되며, 데이터는 $A \rightarrow K$로 이동합니다.
   - Case 2: $\text{Score}_K \le \text{Score}_A$인 경우 $\rightarrow$ 승자는 여전히 $A$이며, 데이터는 $A$에 그대로 머무릅니다.
5. **결론**:
   $\text{Score}_B$나 $\text{Score}_C$가 $\text{Score}_A$를 추월하는 일은 **수학적으로 절대 발생할 수 없습니다!**
   따라서 변경되지 않은 OSD들 간의 데이터 이동은 **정확히 0건(Zero Unnecessary Movement)**으로 보장됩니다.

---

## 5. 프로덕션 운영 및 성능 지표 비교

| 비교 항목 | Classic Straw | Straw2 (현대 Ceph 표준) |
| :--- | :--- | :--- |
| **점수 계산 복잡도** | $O(n)$ 계수 사전 계산 필요 | $O(1)$ 즉시 계산 ($\ln(U) / w$) |
| **OSD 추가 시 불필요한 이동** | **대량 발생 (전체 이동의 15% ~ 40%)** | **0건 (Zero Unnecessary Movement)** |
| **OSD 가중치 변경 시** | 주변 OSD들 간 데이터 셔플링 | 오직 대상 OSD와만 데이터 교환 |
| **10PB 클러스터 디스크 증설 시** | 수십 TB의 불필요한 네트워크 폭풍 | 정확히 증설 용량에 비례한 최소 이동 |
| **장애 도메인 안전성** | 랙/호스트 격리 보장 | 랙/호스트 격리 완벽 보장 |

### 프로덕션 권장 CRUSH 튜너블
Ceph Luminous, Nautilus, Quincy, Reef 등 현대 프로덕션 클러스터에서는 CRUSH 맵의 모든 버킷 타입을 `straw2`로 강제합니다:

```bash
# 버킷 타입 확인 및 전환
ceph osd crush tunables optimal
ceph osd getcrushmap -o /tmp/crush.map
crushtool -d /tmp/crush.map -o /tmp/crush.txt
# bucket ... alg straw2 확인
```
