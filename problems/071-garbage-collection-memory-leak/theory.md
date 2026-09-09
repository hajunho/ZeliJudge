# 가비지 컬렉션(GC)과 메모리 누수의 덫 (Garbage Collection & Memory Leak via GC Roots)

> **"Java/Python/Node.js는 GC가 알아서 메모리를 치워준다면서요?! 왜 서버가 매일 새벽 OOM으로 죽을까요?!"**  
> **"로봇 청소기와 기둥에 묶인 쓰레기의 비극 vs GC Roots 도달 가능성 분석(Reachability Analysis)"**

---

## 1. 현실 세계 비유: 로봇 청소기와 기둥에 묶인 쓰레기

자동으로 방 안의 먼지와 쓰레기를 빨아들이는 최신형 로봇 청소기(Garbage Collector)가 있는 자취방을 상상해 봅시다.

```
[비극적인 상황: 버려진 상자와 질긴 끈]
1. 집주인은 다 먹은 피자 상자(객체)를 버리려고 거실 구석에 두었습니다.
2. 그런데 실수로 거실 중앙의 대들보 기둥(GC Root: Static Map)에서 뻗어 나온 질긴 끈(강한 참조, Strong Reference)에 피자 상자를 묶어두었습니다!
3. 로봇 청소기가 방을 돌아다니며 쓰레기를 치우려 하지만, 기둥에서 연결된 끈이 팽팽하게 이어져 있는 것을 봅니다.
4. 로봇 청소기는 생각합니다: "어? 기둥에 단단히 묶여 있네? 주인이 아직 아끼는 보물인가 보다. 절대 치우면 안 돼!"
5. 집주인은 매일 피자 상자를 하나씩 묶어두었고, 로봇 청소기는 상자를 단 하나도 치우지 못합니다.
6. 한 달 뒤, 방 천장까지 피자 상자가 가득 차서 방 문조차 열 수 없는 상태(OutOfMemoryError, OOM)가 되어 집이 폭발합니다!
```

이것이 바로 자바(JVM), V8(Node.js), 파이썬 등 **가비지 컬렉터가 탑재된 최신 언어에서도 치명적인 메모리 누수(Memory Leak)가 발생하는 근본 원인**입니다.  
가비지 컬렉터는 게으르거나 고장 난 것이 아닙니다. 개발자가 **GC Root와 객체 사이의 끈(참조)을 끊어주지 않았기 때문에** 치우고 싶어도 치울 수 없는 것입니다.

---

## 2. 가비지 컬렉터의 수거 기준: 도달 가능성 분석 (Reachability Analysis)

현대 가비지 컬렉터는 "참조 카운팅(Reference Counting)"의 순환 참조 한계를 극복하기 위해 **도달 가능성 분석(Reachability Analysis, Tracing GC)**을 사용합니다:

```
[GC Roots (생명줄의 시작점)]
  ├── 1. Class Static Variables (전역 정적 변수)
  ├── 2. Active Thread Stack Frames (현재 실행 중인 메서드의 로컬 변수)
  └── 3. JNI Native References (C/C++ 네이티브 참조)
        │
        ▼ (참조 체인을 따라 탐색: Marking Phase)
   [Object A] ──> [Object B] ──> [Object C]  (✅ 도달 가능: Live Object, 보존!)
        
   [Object D] ──> [Object E]                 (❌ 어떤 GC Root에서도 도달 불가: Garbage, 수거!)
```

- **Live Object (생존 객체)**: GC Roots 중 어느 하나로부터라도 참조 체인을 타고 연결될 수 있는 객체.
- **Unreachable Object (가비지 객체)**: 모든 GC Roots로부터 고립된 객체. GC가 메모리를 회수(Reclaim)함.
- **메모리 누수(Memory Leak)의 진짜 정의**:  
  **"논리적으로는 비즈니스 로직에서 더 이상 쓰이지 않는데, 물리적으로는 GC Root가 강한 참조를 쥐고 있어 수거되지 못하는 객체들의 누적 상태"**

---

## 3. 실무에서 가장 흔한 3대 메모리 누수 안티패턴

| 안티패턴 | ❌ 치명적 코드 예시 | ⭕ 모범 개선 코드 |
| :--- | :--- | :--- |
| **1. 무제한 정적 캐시 (Unbounded Cache)** | `public static final Map<Long, User> cache = new HashMap<>();`<br>만료 조건 없이 무한정 `cache.put(id, user)` | Guava / Caffeine Cache 활용:<br>`Cache<Long, User> cache = Caffeine.newBuilder().maximumSize(1000).expireAfterWrite(10, MINUTES).build();` |
| **2. 미해제 이벤트 리스너 (Dangling Listener)** | 싱글톤 서비스에 리스너 등록 후 방치:<br>`eventBus.register(this);` (화면/요청이 끝났는데 unregister 누락) | 라이프사이클 종료 시 반드시 해제:<br>`public void destroy() { eventBus.unregister(this); }` 또는 `WeakReference` 기반 리스너 |
| **3. 스레드 풀 ThreadLocal 누수** | 톰캣 스레드 풀에서 작업 후 잔류:<br>`userContext.set(user);`<br>(요청 처리 후 remove 안 함) | `try ... finally` 블록에서 필수 정리:<br>`try { ... } finally { userContext.remove(); }` |

---

## 4. 자바의 4대 참조 강도 (Reference Strength)

객체의 메모리 수명 주기를 제어하기 위해 제공되는 4가지 참조 유형입니다:

1. **Strong Reference (강한 참조)**:
   - `User user = new User();` 우리가 흔히 쓰는 일반적인 참조.
   - GC Roots에 연결되어 있는 한 어떤 경우에도 수거되지 않으며, 힙이 가득 차면 OOM을 던집니다.
2. **Soft Reference (부드러운 참조)**:
   - `SoftReference<User> soft = new SoftReference<>(user);`
   - 평소에는 수거되지 않다가, **메모리가 정말 부족해서 OOM이 터지기 직전에만** GC가 수거합니다. (메모리 민감형 캐시에 유용)
3. **Weak Reference (약한 참조)**:
   - `WeakReference<User> weak = new WeakReference<>(user);`
   - 오직 Weak Reference로만 연결된 객체는 **다음 GC 주기가 돌면 무조건 수거**됩니다. (`WeakHashMap`, 이벤트 리스너에 최적)
4. **Phantom Reference (유령 참조)**:
   - 객체가 메모리에서 실제로 수거된 직후 사후 정리(Cleaner) 작업을 추적할 때 사용.

---

## 5. 메모리 프로파일링 실무 도구

- **Heap Dump 분석**: OOM 발생 시 `-XX:+HeapDumpOnOutOfMemoryError` 플래그로 힙 덤프(`.hprof`)를 남겨 **Eclipse Memory Analyzer(MAT)** 또는 VisualVM으로 누수 지점 탐색.
- **Dominator Tree 확인**: 어떤 단일 객체(예: static ArrayList)가 힙 메모리의 90% 이상을 쥐고 있는지(Retained Heap Size) 확인하여 범인 색출.

> **"가비지 컬렉터가 있다고 해서 메모리 관리를 손 놓지 마라. 객체를 생성할 때보다 객체와의 인연(참조)을 끊는 순간이 더 중요하다."**  
> 이것이 24시간 365일 무중단으로 동작하는 견고한 백엔드 시스템을 지키는 엔지니어의 핵심 덕목입니다.
