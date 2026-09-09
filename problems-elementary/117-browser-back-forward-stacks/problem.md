# [초등] #117 웹 브라우저 뒤로 가기 / 앞으로 가기 2스택

## 📖 문제 줄거리 & 상황
웹 브라우저(크롬, 사파리)의 '뒤로 가기'와 '앞으로 가기' 버튼은 사실 2개의 스택(`back_stack`, `forward_stack`)으로 구현되어 있습니다!
- `VISIT url`: 현재 페이지를 `back_stack`에 넣고 새 `url`로 이동하며, `forward_stack`은 완전히 비웁니다.
- `BACK`: `back_stack`에 페이지가 있으면, 현재 페이지를 `forward_stack`에 넣고 `back_stack`에서 꺼낸 페이지로 이동합니다.
- `FORWARD`: `forward_stack`에 페이지가 있으면, 현재 페이지를 `back_stack`에 넣고 `forward_stack`에서 꺼낸 페이지로 이동합니다.
처음에 `home` 페이지에서 시작할 때, 모든 명령을 수행한 후 최종 머물러 있는 페이지 주소를 구해주세요!

---

## 💻 문제 설명
명령의 수 $Q$와 $Q$개의 브라우저 탐색 명령이 주어집니다. 초기 페이지는 `home`입니다. 모든 명령 수행 후 최종 현재 페이지를 출력하세요.

---

## 📥 입력 형식 (Input)
첫째 줄에 명령의 개수 $Q$가 주어집니다. ($1 \le Q \le 100$)
둘째 줄부터 $Q$개의 줄에 걸쳐 명령(`VISIT url`, `BACK`, `FORWARD`)이 한 줄에 하나씩 주어집니다.

---

## 📤 출력 형식 (Output)
최종 현재 페이지의 주소를 문자열로 출력합니다.

---

## 💡 입출력 예시

### 예제 1
- **입력:**
```text
3
VISIT google
VISIT naver
BACK
```
- **출력:**
```text
google
```

### 예제 2
- **입력:**
```text
3
VISIT a
BACK
FORWARD
```
- **출력:**
```text
a
```
