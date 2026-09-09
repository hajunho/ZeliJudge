# 직렬 지옥 탈출기: 동기 순차 호출(Serial) vs 병렬 비동기 I/O (Fan-Out / Fan-In)

> "네트워크 I/O를 기다리는 동안 CPU는 아무 일도 하지 않고 빈둥거린다.  
> 5개의 요청을 차례대로 기다리는 것은, 5대의 세탁기를 1대씩 순서대로 돌리는 것과 같다."

---

## 1. 현실 세계 비유: 5대의 전화기와 여행사 견적서

고객이 여행사에 전화를 걸어 "호텔, 항공권, 렌터카, 여행자보험, 공연티켓 견적을 한 번에 뽑아주세요!"라고 요청했습니다.

```text
❌ 직렬 동기 호출 (Serial Sync, for 루프의 비극):
   직원이 한 손에 수화기를 들고...
   1. 호텔에 전화 걸어 3초 통화 후 끊음
   2. 항공사에 전화 걸어 3초 통화 후 끊음
   3. 렌터카에 전화 걸어 3초 통화 후 끊음
   4. 보험사에 전화 걸어 3초 통화 후 끊음
   5. 공연기획사에 전화 걸어 3초 통화 후 끊음
   소요 시간: 3 + 3 + 3 + 3 + 3 = 15초! 고객은 화를 내며 전화를 끊어버립니다.

✅ 병렬 비동기 I/O (Async Fan-Out / Fan-In):
   직원이 책상 위에 전화기 5대를 놓고 양손으로 동시에 5개 업체에 전화를 겁니다(Fan-Out).
   5개 업체가 각자 확인하는 동안 직원은 여유롭게 기다리다가,
   가장 늦게 끝나는 업체의 응답 시간인 max(T_i) = 3초 만에 5개 견적을 모두 취합해 전달합니다!
```

---

## 2. 왜 네트워크 I/O는 무조건 병렬 비동기로 처리해야 하는가?

프로그래밍에서 작업은 크게 두 가지로 나뉩니다:
1. **CPU-Bound (연산 집약적)**: 암호 해시 계산, 비디오 인코딩, 머신러닝 연산. (CPU 코어가 100% 돌아감)
2. **I/O-Bound (입출력 대기 집약적)**: DB 쿼리 대기, 외부 API HTTP 요청 대기, 디스크 파일 읽기.

외부 API 호출의 99%는 **"우리 서버가 네트워크 패킷을 던져놓고, 저 멀리 다른 데이터센터 서버가 응답을 보내줄 때까지 멍하니 기다리는 유휴 시간(Idle Waiting)"**입니다.

```mermaid
flowchart TD
    subgraph Serial [직렬 호출: 합산 시간 소요]
        S1[API 1 (1.0s)] --> S2[API 2 (1.5s)] --> S3[API 3 (0.5s)]
        NoteS[총 소요 시간: 1.0 + 1.5 + 0.5 = 3.0초]
    end

    subgraph Parallel [병렬 Fan-Out: 최댓값 수렴]
        P_Start((요청 시작)) --> P1[API 1 (1.0s)]
        P_Start --> P2[API 2 (1.5s)]
        P_Start --> P3[API 3 (0.5s)]
        P1 --> P_End((동시 수거))
        P2 --> P_End
        P3 --> P_End
        NoteP[총 소요 시간: max(1.0, 1.5, 0.5) = 1.5초]
    end
```

수학적으로 $K$개의 독립적인 API를 호출할 때:
- **직렬 동기 호출 지연시간**: $T_{serial} = \sum_{i=1}^K T_i$
- **병렬 비동기 호출 지연시간**: $T_{parallel} = \max_{1 \le i \le K}(T_i)$

$K=5$개이고 각 응답이 평균 1초라면, **직렬은 5초가 걸리지만 병렬은 1초 만에 끝납니다 (5배 속도 향상!).**

---

## 3. 부분 실패(Partial Failure)를 다루는 2대 실무 아키텍처

5개의 외부 API를 동시에 불렀을 때, 1개 API가 500 에러를 뱉거나 네트워크 타임아웃에 걸리면 어떻게 해야 할까요?

### 1. Fail-Fast (All-or-Nothing)
- **철학**: "하나라도 틀어지면 전체가 무의미하다."
- **적용 사례**: 결제 승인, 계좌 이체, 사용자 회원가입 트랜잭션.
- **동작**: 서브태스크 중 1개라도 실패하면 즉시 나머지 작업들을 취소(Cancel)하고 에러를 반환합니다.
- **코드 매핑**:
  - Python: `asyncio.gather(*tasks, return_exceptions=False)`
  - JS: `Promise.all([p1, p2, p3])`

### 2. Graceful Degradation (All-Settled / 우아한 성능 저하)
- **철학**: "1개가 고장 났다고 해서 전체 화면을 하얗게 죽일 수는 없다."
- **적용 사례**: 쇼핑몰 메인 화면 (배너, 추천 상품, 최근 본 상품, 장바구니 수량 등).
- **동작**: 5개 중 추천 API가 터지더라도, 성공한 배너와 상품 정보는 정상 노출하고 추천 영역만 "지금은 추천을 불러올 수 없습니다"라는 기본값(Fallback)으로 대체합니다.
- **코드 매핑**:
  - Python: `asyncio.gather(*tasks, return_exceptions=True)`
  - JS: `Promise.allSettled([p1, p2, p3])`
  - Java: `CompletableFuture.allOf()` 후 각 Future 예외 핸들링 (`handle`, `exceptionally`)

---

## 4. 언어별 모범 비동기 병렬 구현체

### Python (`asyncio.gather` with Semaphore)
```python
import asyncio
import httpx

semaphore = asyncio.Semaphore(10) # 외부 서버 과부하 방지 세마포어

async def fetch_service(client, url):
    async with semaphore:
        resp = await client.get(url, timeout=3.0)
        return resp.json()

async def get_dashboard():
    async with httpx.AsyncClient() as client:
        # All-Settled 패턴: return_exceptions=True
        results = await asyncio.gather(
            fetch_service(client, "http://hotel/api"),
            fetch_service(client, "http://flight/api"),
            fetch_service(client, "http://car/api"),
            return_exceptions=True
        )
        # 성공/실패 분기 처리
        for res in results:
            if isinstance(res, Exception):
                print("Fallback logic applied")
```

### Java (`CompletableFuture` & Java 21 가상 스레드)
```java
List<CompletableFuture<Response>> futures = urls.stream()
    .map(url -> CompletableFuture.supplyAsync(() -> callHttp(url), executor)
        .exceptionally(ex -> FallbackResponse.empty())) // Graceful Degradation
    .toList();

CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]))
    .orTimeout(3, TimeUnit.SECONDS)
    .join();
```

---

## 5. 병렬 Fan-Out 시 절대 잊지 말아야 할 3대 함정

1. **무제한 동시성(Unbounded Concurrency) 금지**:
   - `for` 루프에서 1,000개의 태스크를 한꺼번에 `asyncio.gather`로 던지면, 순간적으로 1,000개의 소켓이 열려 OS 파일 디스크립터(FD)가 고갈되거나 상대방 서버를 DDoS 공격하게 됩니다.
   - 반드시 **`Semaphore` 또는 고정 크기 풀(Pool)**로 동시 실행 수를 제한해야 합니다.
2. **글로벌 타임아웃(Global Timeout) 필수**:
   - 병렬로 10개를 불렀는데 9개는 100ms 만에 끝나고, 1개가 60초 동안 응답이 없으면 전체 API가 60초 동안 블로킹됩니다.
   - 반드시 전체 요청을 감싸는 상위 타임아웃을 강제해야 합니다.
3. **가짜 비동기 라이브러리 주의**:
   - `async def` 함수 안에서 동기식 `requests.get()`이나 `time.sleep()`을 호출하면 싱글 스레드 이벤트 루프가 통째로 얼어붙습니다.
   - 반드시 논블로킹 비동기 클라이언트(`httpx`, `aiohttp`, `WebClient`)를 사용해야 합니다.

---

## 6. 요약

> 1. 독립적인 외부 API 호출은 직렬 순차 처리($\sum T_i$)하지 말고 **비동기 병렬 Fan-Out($\max T_i$)**으로 처리하라.
> 2. 전체를 멈춰야 하는 결제는 `Fail-Fast`, 화면을 살려야 하는 대시보드는 `All-Settled` 우아한 저하 전략을 선택하라.
> 3. 병렬화할 때는 상대방 서버를 보호하기 위한 **동시성 제어(Semaphore)**와 **글로벌 타임아웃**을 잊지 마라.
