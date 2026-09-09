# 117. 정규표현식 하나 검사했을 뿐인데 CPU 100%로 서버가 영구 동결?!: ReDoS(정규표현식 서비스 거부 공격)와 비결정적 유한 오토마타(NFA 백트래킹 지수 폭발 vs Thompson 선형 RE2)

## 문제 설명

웹 서버에 회원가입 시 이메일이나 사용자 ID 형식을 검사하기 위해 정규표현식을 작성했습니다.  
그런데 어떤 악의적인 사용자가 `"aaaaaaaaaaaaaaaaaaaaX"`와 같은 문자열을 보내자마자, 서버의 CPU 사용률이 **100%**로 치솟으며 다른 정상 요청들을 전혀 처리하지 못하고 서버가 영구 동결(Deadlock 유사 상태)되어 버렸습니다! 😱

이 현상은 **ReDoS (Regular Expression Denial of Service, 정규표현식 서비스 거부 공격)**라고 불립니다.  
2019년 7월 2일, 글로벌 CDN 기업 **Cloudflare**는 WAF(웹 방화벽) 룰에 `.*.*=.*` 형태의 불량 정규식을 배포했다가, 전 세계 수만 대의 엣지 프록시 서버 CPU가 100%로 치솟으며 구글, 디스코드, 쇼피파이 등 전 세계 인터넷 트래픽이 30분간 올스톱되는 역사상 최대 규모의 ReDoS 대장애를 겪었습니다.

### 왜 이런 일이 발생할까요?
Python `re`, Java, JavaScript, PCRE 등 전통적인 정규식 엔진은 **NFA 백트래킹(Backtracking DFS)** 방식을 사용합니다.
- 패턴이 `(a+)+$`(중첩 수량자) 또는 `(a|aa)+$`(모호한 대안)인 경우:
- 끝 글자가 불일치할 때, 엔진은 "앞의 `+`가 몇 글자를 먹고 뒤의 `+`가 몇 글자를 먹을지" 가능한 모든 경우의 수($2^{N-1}$)를 재귀적으로 전부 시도합니다.
- 문자열 길이가 1글자 늘어날 때마다 탐색 횟수가 **2배($O(2^N)$)**로 폭증하여, 단 30~40글자만으로도 수십억~수천억 번의 헛발질(Backtracking)을 수행하게 됩니다!

반면, 컴퓨터 과학의 거장 켄 톰슨(Ken Thompson)이 고안한 **Thompson NFA / DFA 시뮬레이션(Google RE2, Go 표준 `regexp`, Rust `regex`)**은 백트래킹을 원천 배제하고 문자열의 각 글자마다 도달 가능한 오토마타 상태 집합(State Set)만을 추적하여, **어떠한 악의적인 패턴이나 입력에도 반드시 $O(N)$ 선형 시간**을 보장합니다.

본 문제에서는:
1. **정적 취약점 분석기 (`ANALYZE`)**: 정규식에 ReDoS 취약점(중첩 수량자 `NESTED_QUANTIFIER`, 모호한 대안 `AMBIGUOUS_ALTERNATION`)이 있는지 사전에 검사합니다.
2. **NFA 백트래킹 엔진 (`engine=BACKTRACKING`)**: 재귀적 백트래킹 스텝을 계측하며, `max_steps`를 초과할 경우 ReDoS 타임아웃(`REDOS_CATASTROPHIC_BACKTRACKING`)으로 프로세스를 강제 중단하여 서버를 방어합니다.
3. **선형 RE2 엔진 (`engine=LINEAR_RE2`)**: 톰슨 NFA 상태 전이를 통해 아무리 악의적인 입력도 선형 시간 $O(N)$에 안전하게 매칭하는 가상 정규식 엔진을 시뮬레이션합니다.

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG engine=<BACKTRACKING|LINEAR_RE2> max_steps=<int>`
   - 엔진 모드를 `BACKTRACKING` 또는 `LINEAR_RE2`로 설정합니다.
   - `max_steps`: 백트래킹 엔진에서 허용할 최대 스텝 수(기본값: 100,000)를 지정합니다.
   - 출력: `OK engine=<engine> max_steps=<max_steps>`

2. `ANALYZE pattern=<regex>`
   - 입력된 정규식 패턴의 ReDoS 취약점을 정적 분석합니다:
     - 중첩 수량자(`(a+)+`, `([a-z]+)+`, `(a*)*`, `(a+)*` 등):  
       `ANALYZE_RESULT pattern=<pattern> risk=HIGH_VULNERABILITY reason=NESTED_QUANTIFIER`
     - 모호한 대안 반복(`(a|aa)+`, `(a|a)+`, `(b|b+)+` 등):  
       `ANALYZE_RESULT pattern=<pattern> risk=HIGH_VULNERABILITY reason=AMBIGUOUS_ALTERNATION`
     - 안전한 패턴:  
       `ANALYZE_RESULT pattern=<pattern> risk=SAFE reason=NONE`

3. `MATCH pattern=<regex> text=<string>`
   - 현재 설정된 엔진 모드로 정규식 매칭을 수행합니다.
   - **백트래킹 모드**:
     - 탐색 도중 총 스텝 수가 `max_steps`를 초과하면 즉시 중단하고 타임아웃 에러를 출력합니다:  
       `MATCH_TIMEOUT pattern=<pattern> text=<text> steps=<steps> error=REDOS_CATASTROPHIC_BACKTRACKING`
     - 매칭 성공 시:  
       `MATCH_SUCCESS pattern=<pattern> text=<text> matched=true steps=<steps> elapsed_us=<elapsed_us>`
     - 매칭 실패 시:  
       `MATCH_FAILURE pattern=<pattern> text=<text> matched=false steps=<steps> elapsed_us=<elapsed_us>`
   - **선형 RE2 모드**:
     - 톰슨 NFA 상태 전이로 처리하며, 타임아웃 없이 $O(N)$ 스텝만에 즉시 완료합니다:  
       `MATCH_SUCCESS` 또는 `MATCH_FAILURE` 형식으로 출력됩니다. (가상 지연 `elapsed_us = steps`)

4. `RESET`
   - 엔진 설정을 기본값(`engine=BACKTRACKING`, `max_steps=100000`)으로 초기화합니다.
   - 출력: `OK engine=BACKTRACKING max_steps=100000`

---

## 출력 형식

각 명령어에 대응하는 결과를 한 줄씩 표준 출력(stdout)으로 출력합니다.

---

## 예제 입력 1

```text
CONFIG engine=BACKTRACKING max_steps=100000
ANALYZE pattern=(a+)+$
ANALYZE pattern=(a|aa)+$
ANALYZE pattern=^[0-9]+$
MATCH pattern=(a+)+$ text=aaaa
MATCH pattern=(a+)+$ text=aaaX
```

## 예제 출력 1

```text
OK engine=BACKTRACKING max_steps=100000
ANALYZE_RESULT pattern=(a+)+$ risk=HIGH_VULNERABILITY reason=NESTED_QUANTIFIER
ANALYZE_RESULT pattern=(a|aa)+$ risk=HIGH_VULNERABILITY reason=AMBIGUOUS_ALTERNATION
ANALYZE_RESULT pattern=^[0-9]+$ risk=SAFE reason=NONE
MATCH_SUCCESS pattern=(a+)+$ text=aaaa matched=true steps=17 elapsed_us=17
MATCH_FAILURE pattern=(a+)+$ text=aaaX matched=false steps=34 elapsed_us=34
```

---

## 예제 입력 2 (ReDoS 백트래킹 참사 vs Google RE2 방어)

```text
CONFIG engine=BACKTRACKING max_steps=50000
MATCH pattern=(a+)+$ text=aaaaaaaaaaaaaaaX
CONFIG engine=LINEAR_RE2 max_steps=50000
MATCH pattern=(a+)+$ text=aaaaaaaaaaaaaaaX
```

## 예제 출력 2

```text
OK engine=BACKTRACKING max_steps=50000
MATCH_TIMEOUT pattern=(a+)+$ text=aaaaaaaaaaaaaaaX steps=50001 error=REDOS_CATASTROPHIC_BACKTRACKING
OK engine=LINEAR_RE2 max_steps=50000
MATCH_FAILURE pattern=(a+)+$ text=aaaaaaaaaaaaaaaX matched=false steps=92 elapsed_us=92
```

> **설명**:  
> 불과 16글자(`15개의 a + 1개의 X`)에 불과한 문자열임에도 불구하고, 백트래킹 엔진은 $2^{15}$가지가 넘는 분기 탐색을 시도하다 `max_steps=50000`을 초과하여 **ReDoS 타임아웃**으로 서버를 보호했습니다.  
> 반면, 동일한 악마 패턴과 동일한 입력에 대해 **Google RE2(선형 톰슨 NFA)** 모드로 전환하자, 단 **92스텝**만에 $O(N)$으로 즉시 불일치를 판정했습니다!\n