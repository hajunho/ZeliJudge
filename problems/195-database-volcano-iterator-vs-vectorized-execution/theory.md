# 깊이 있는 컴퓨터 과학: 데이터베이스 쿼리 실행 엔진, 화산 모델 vs 벡터화 실행과 기수 조인

## 1. 1994년 화산 반복자(Volcano Iterator) 모델의 탄생과 한계

1994년 Goetz Graefe 교수가 발표한 화산 모델(Volcano Iterator Model, Tuple-at-a-time)은 데이터베이스 시스템 아키텍처의 표준으로 자리잡았습니다.
모든 관계대수 연산자가 단일 인터페이스를 공유합니다:
```cpp
class Operator {
    virtual void open() = 0;
    virtual Tuple* next() = 0;
    virtual void close() = 0;
};
```
- **장점**: 연산자 간의 결합도가 극도로 낮고, 전체 결과를 메모리에 올리지 않고도 파이프라이닝으로 스트리밍 처리 가능.
- **현대 하드웨어에서의 참패**:
  1. 1990년대 CPU는 66MHz였고 메모리 접근 속도와 큰 차이가 없었음.
  2. 2020년대 현대 CPU는 수 GHz로 발전했으나 DRAM 레이턴시는 크게 개선되지 않아 '메모리 장벽(Memory Wall)'이 형성됨.
  3. 튜플마다 가상 함수 호출(`vtable lookup`)을 수행하면 파이프라인 플러시와 I-Cache 오염이 발생하며, CPU 클록의 $70\% \sim 80\%$가 실제 데이터 계산이 아닌 연산자 제어 흐름에 낭비됨.

---

## 2. 2005년 벡터화 실행(Vectorized Execution) 혁명

Peter Boncz 교수는 CWI의 **MonetDB/X100 (이후 VectorWise, Snowflake, DuckDB의 모태)** 프로젝트를 통해 벡터화 실행 모델을 창시했습니다:
```cpp
class VectorizedOperator {
    virtual void open() = 0;
    virtual VectorBatch* next() = 0; // 1024개 값의 컬럼 벡터 반환!
    virtual void close() = 0;
};
```
- **가상 함수 호출 1/1024 축소**: 1,000만 건 처리 시 함수 호출이 1만 건 수준으로 격감.
- **원시 루프와 컴파일러 SIMD 최적화**:
  - `next()` 내부에서 1024개의 기본 타입 배열(`int32_t[]`)에 대해 단순 for 루프를 수행.
  - 현대 컴파일러(GCC, Clang)가 이를 인지하여 AVX2 / AVX-512 벡터 명령어로 자동 변환하여 1클록에 8~16개 데이터를 동시 연산.
- **CPU L1/L2 캐시 최적 적재**: 1024개 정수 벡터는 수 킬로바이트(KB)에 불과하므로 CPU L1 캐시(32KB~48KB) 안에 완벽하게 들어맞음.

---

## 3. 캐시 의식적 기수 해시 조인 (Radix Partitioned Hash Join)

### 3.1 나이브 해시 조인의 메모리 스톨
- 빌드 테이블로 생성한 해시 테이블 크기가 수백 MB에 달하면, CPU의 마지막 레벨 캐시(L3)를 크게 벗어남.
- 프로브 단계에서 들어오는 각 튜플의 해시값 위치는 메모리 전역에 걸쳐 완전한 무작위(Random Access)로 흩어짐.
- 결과적으로 거의 매 튜플마다 L3 캐시 미스가 발생하며, CPU는 수백 클록 사이클 동안 DRAM 버스에서 데이터를 기다리며 정지(Stall)함.

### 3.2 2단계 기수 분할(Two-Pass Radix Partitioning)
1. **분할 단계 (Partitioning Phase)**:
   - 해시값의 상위 $B$ 비트(Radix)를 읽어 빌드 테이블과 프로브 테이블을 $2^B$개의 작은 버킷으로 파티셔닝.
   - 각 버킷의 크기가 CPU L1 또는 L2 캐시 용량(약 256KB~1MB) 이하가 되도록 분할.
2. **조인 단계 (Join Phase)**:
   - 대응하는 작은 빌드 버킷과 프로브 버킷을 쌍으로 가져와 캐시 내에서 로컬 해시 조인 수행.
   - 해시 테이블이 L2 캐시 안에 완전히 상주하므로 L3 미스가 0%에 수렴하며 메모리 레이턴시 병목을 완전히 제거.
