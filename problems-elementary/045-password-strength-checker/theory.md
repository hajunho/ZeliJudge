# 📘 [ZeliJudge Junior #045] 파이썬의 글자 감별사 3총사: isupper(), islower(), isdigit()

---

## 1. 글자의 신분증을 확인하는 메서드들

파이썬에는 글자의 종류를 알려주는 훌륭한 도구들이 있습니다:
* `ch.isupper()`: 대문자니? (참/거짓)
* `ch.islower()`: 소문자니? (참/거짓)
* `ch.isdigit()`: 숫자니? (참/거짓)

---

## 2. 하나라도 있는지 검사하는 `any()` 함수

"글자들 중에 대문자가 단 하나라도 있니?"라고 물어볼 때:
```python
cond_upper = any(ch.isupper() for ch in p)
```
`any()` 함수는 조건에 맞는 글자가 1개라도 발견되면 즉시 `True`를 반환합니다.
이처럼 명확하고 안전한 유효성 검사(Validation)는 모든 웹 서비스 보안의 기본입니다!
