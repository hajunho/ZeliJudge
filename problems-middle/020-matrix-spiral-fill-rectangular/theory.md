# 직사각형 나선형 순회 (Rectangular Spiral Traversal)

$R \ne C$인 직사각형 격자에서는 4개의 경계선 변수를 두어 영역을 좁혀나가는 방식이 가장 직관적이고 버그가 없습니다.

## 1. 4대 경계 변수
- `top = 0`, `bottom = R - 1`
- `left = 0`, `right = C - 1`
- 채울 숫자: `num = 1`부터 `R * C`까지

## 2. 4단계 회전 루프
1. **우(Right)**: `top`행에서 `left`부터 `right`까지 채우고 `top += 1`
2. **하(Down)**: `right`열에서 `top`부터 `bottom`까지 채우고 `right -= 1`
3. **좌(Left)**: (아직 행이 남아있다면 `top <= bottom`) `bottom`행에서 `right`부터 `left`까지 채우고 `bottom -= 1`
4. **상(Up)**: (아직 열이 남아있다면 `left <= right`) `left`열에서 `bottom`부터 `top`까지 채우고 `left += 1`
