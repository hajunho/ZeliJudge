# 📘 [CS 이론 #006] 쿼리 지옥과 DB 사망: N+1 문제와 스트리밍 집계

> **"ORM으로 코드 3줄 짰을 뿐인데 왜 데이터베이스 커넥션 풀이 마비되고 OOM이 터졌을까?"**  
> 모든 백엔드 엔지니어와 DBA가 입을 모아 경고하는 백엔드의 영원한 숙적, N+1 쿼리와 지연 평가.

---

## 1. 달콤한 ORM의 함정과 N+1 참사

Django, SQLAlchemy, JPA/Hibernate, Prisma 등 현대 ORM(Object-Relational Mapping) 도구들은 SQL을 직접 짜지 않고도 파이썬 객체처럼 데이터베이스를 다룰 수 있게 해줍니다.

```python
# AI가 너무나 자연스럽게 짜준 코드
orders = Order.objects.all()          # 1. 주문 목록 조회 (쿼리 1번)
for order in orders:
    items = order.items.all()         # 2. 루프 돌며 상품 조회 (주문 N개마다 쿼리 1번씩!)
    total = sum(i.price * i.quantity for i in items)
```

이 코드는 개발 환경에서 주문이 5개일 때는 쿼리가 딱 6번 나가므로 아무런 문제가 없어 보입니다.  
하지만 **주문이 10만 개($N=100,000$)가 되는 순간, 데이터베이스에는 100,001번의 쿼리가 폭포수처럼 쏟아집니다.**

---

## 2. 왜 10만 번의 쿼리는 시스템을 파괴하는가?

10만 번의 쿼리가 실행된다는 것은 단순히 CPU 연산을 10만 번 한다는 뜻이 아닙니다:

```
[ 웹 서버 ]                                  [ 데이터베이스 서버 ]
    │                                                 │
    │─── 1. "101번 주문 상품 줘" (TCP 패킷 전송) ──►│ (쿼리 파싱, 실행 계획, 디스크 I/O)
    │◄── 2. "여기 결과 데이터야" (네트워크 왕복) ────│
    │                                                 │
    │─── 3. "102번 주문 상품 줘" (TCP 패킷 전송) ──►│ (쿼리 파싱, 실행 계획, 디스크 I/O)
    │◄── 4. "여기 결과 데이터야" (네트워크 왕복) ────│
    ... (이 짓을 100,000번 반복!)
```

### 1) 네트워크 지연(RTT, Round Trip Time)의 누적
아무리 같은 로컬 네트워크라도 쿼리 1건을 주고받는 데 최소 **0.5ms ~ 1ms**의 네트워크 왕복 시간이 걸립니다:
$$100,000\text{ 회} \times 1\text{ms} = 100,000\text{ms} = \mathbf{100\text{초 (1분 40초!)불변}}$$
유저는 화면이 멈춘 채 100초 동안 로딩 바만 바라보다가 사이트를 이탈합니다.

### 2) 커넥션 풀(Connection Pool) 고갈과 전사적 장애
웹 서버가 하나의 요청을 처리하느라 DB 커넥션을 100초 동안 붙잡고 있으면, 다른 수천 명의 유저가 보내는 로그인, 장바구니, 결제 요청들이 커넥션을 얻지 못하고 줄줄이 대기 상태에 빠집니다.  
결국 **모든 API가 504 Gateway Timeout을 내뿜으며 전사 서비스가 올스톱**됩니다.

---

## 3. 엔지니어의 해결책 1: Eager Loading (JOIN과 `IN` 쿼리)

엔지니어는 루프 안에서 DB를 10만 번 찌르는 대신, **단 1번 또는 2번의 쿼리로 필요한 모든 데이터를 한 번에 가져옵니다(Eager Loading)**.

### 방법 A: SQL JOIN (단 1번의 쿼리)
```sql
SELECT o.id, SUM(i.price * i.quantity)
FROM orders o
LEFT JOIN order_items i ON o.id = i.order_id
GROUP BY o.id;
```
DB 엔진의 고도로 최적화된 해시 조인(Hash Join)을 통해 단 한 번의 쿼리로 모든 주문의 총액을 $O(N + M)$에 끝냅니다.

### 방법 B: `IN` 쿼리를 통한 배치 패치 (단 2번의 쿼리)
```python
# 1번째 쿼리: 주문 10만 개 조회
orders = Order.objects.all()
order_ids = [o.id for o in orders]

# 2번째 쿼리: 10만 개 주문에 속한 상품들을 IN 절로 단 1번에 몽땅 가져옴!
# SELECT * FROM order_items WHERE order_id IN (...)
items = OrderItem.objects.filter(order_id__in=order_ids)
```
100,001번 나가던 쿼리가 **단 2번**으로 줄어듭니다!

---

## 4. 엔지니어의 해결책 2: 메모리 폭발을 막는 해시 맵 그룹핑

가져온 데이터를 애플리케이션 메모리에서 집계할 때도 $O(N \times M)$ 루프를 돌리면 절대 안 됩니다.  
**해시 맵(Hash Map / Python `dict`)을 활용한 단 1회의 선형 스캔**으로 처리해야 합니다:

```python
# 1. 상품 목록을 단 1회 순회하며 order_id별 총액 누적: O(M)
totals = {}
for order_id, price, quantity in items:
    totals[order_id] = totals.get(order_id, 0) + (price * quantity)

# 2. 주문 목록을 순회하며 O(1) 해시 조회로 결과 매핑: O(N)
for order_id in orders:
    total_amount = totals.get(order_id, 0)
    print(order_id, total_amount)
```

* **기존 무식한 루프**: $100,000 \times 100,000 = \mathbf{100억\text{ 번의 연산 (100초 이상 소요)}}$
* **해시 맵 그룹핑**: $100,000 + 100,000 = \mathbf{단\ 20만\text{ 번의 연산 (0.05초 완료!)}}$

$$\text{100억 번 연산} \xrightarrow{\quad \text{해시 맵 그룹핑} \quad} \mathbf{단\ 20만 번으로 50,000배 최적화!}$$

---

## 5. 지연 평가(Lazy Evaluation)와 제너레이터(Generator)

데이터가 수백만 건, 수천만 건으로 불어나면 10만 개 데이터를 한 번에 리스트(`[ ... ]`)로 메모리에 올리는 것조차 **메모리 부족(OOM, Out of Memory)**을 일으킵니다.

이때 사용하는 컴퓨터 과학의 비기가 **지연 평가(Lazy Evaluation)**와 **제너레이터(`yield`)**입니다:

```python
# 100만 개 데이터를 한 번에 메모리에 올리지 않고 1개씩 흘려보내는 제너레이터
def stream_items(file_path):
    with open(file_path, "r") as f:
        for line in f:
            yield parse_item(line)  # 필요한 순간에 딱 1줄씩만 메모리에 올림!
```

* **리스트 방식**: 10만 개 객체를 메모리에 전부 적재 $\rightarrow$ **수 GB 메모리 점유, OOM 위험**
* **제너레이터 방식**: 현재 처리 중인 딱 1개 객체만 메모리에 유지 $\rightarrow$ **메모리 사용량 $O(1)$ (수 KB 수준!)**

---

## 💡 AI 바이브 코더를 위한 실무 체크리스트
1. **`for` 루프 안에서 절대 DB 쿼리나 ORM `filter()`, `get()`을 호출하지 마세요.** (N+1 참사의 제1원인)
2. **외래키(FK) 관계로 연결된 자식 데이터를 조회할 땐 반드시 Eager Loading을 쓰세요.**
   - Django: `select_related()` (1:1, N:1 JOIN), `prefetch_related()` (1:N IN 쿼리)
   - JPA: `JOIN FETCH` 또는 `@EntityGraph`
3. **대량의 1:N 데이터를 집계할 때는 해시 맵(`dict`)으로 먼저 $O(M)$에 그룹핑한 뒤 매핑하세요.**
