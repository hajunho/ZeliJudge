# 문자열 대소문자 변환과 Title Case

텍스트 에디터나 웹사이트에서 제목을 멋지게 꾸밀 때 'Title Case' 변환이 자주 쓰입니다.

## 1. 단어 단위 분리 (`split`)
`sentence.split()`을 호출하면 문장을 공백을 기준으로 쪼개어 단어들의 리스트로 만들어줍니다.

## 2. 첫 글자 대문자화 (`capitalize()`)
각 단어 `w`에 대해:
- `w.capitalize()` 메서드는 첫 글자를 대문자로, 뒤의 모든 글자를 소문자로 깔끔하게 바꿔줍니다.
- 직접 슬라이싱으로 구현할 수도 있습니다: `w[0].upper() + w[1:].lower()`

## 3. 다시 문장으로 합치기 (`join`)
변환된 단어들을 공백 한 칸(`" "`)으로 다시 결합합니다:
```python
result = " ".join(w.capitalize() for w in words)
```
