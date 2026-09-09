# 📘 [ZeliJudge Junior #019] 긴 문장을 단어로 쪼개는 split()과 첫 글자 word[0]

---

## 1. 띄어쓰기로 단어 쪼개기: `split()`

문장을 컴퓨터가 읽을 때는 공백(스페이스)을 기준으로 싹둑싹둑 잘라 단어들의 리스트로 만듭니다.
이것을 파이썬에서는 `split()`이라고 불러요:
```python
words = "as soon as possible".split()
# ['as', 'soon', 'as', 'possible']
```

---

## 2. 첫 글자 뽑기와 대문자 변환: `word[0].upper()`

단어 리스트를 `for` 문으로 돌면서:
1. 맨 앞글자 가져오기: `word[0]` (컴퓨터는 0번이 첫 번째 칸!)
2. 대문자로 변신시키기: `.upper()`

```python
letters = [w[0].upper() for w in words]
result = "".join(letters) # 'ASAP'
```

이렇게 문자열 조작 기술을 익히면 검색창에 들어온 문장을 분석하고 단어를 자동으로 다듬는 자연어 처리(NLP) 인공지능의 첫걸음을 뗀 것입니다!
