# 문제 #029: 바흐의 평균율 클라비어는 왜 12평균율이 아니었을까요?!: 서양 음악학과 음향학(Musicology & Acoustics): 피타고라스 음률·순정률·1/4 콤마 중전음률(Meantone)·베르크마이스터(Werckmeister) 및 늑대 5도(Wolf Fifth) 조율 음향학 시뮬레이터

## 1. 개요 (Story & Context)
요한 세바스티안 바흐(J. S. Bach)의 1722년 불멸의 명작 **《잘 조율된 클라비어곡집(Das Wohltemperirte Clavier)》**은 현대에 종종 '평균율 클라비어곡집'으로 번역되지만, 음악사학적으로 바흐가 연주했던 악기는 오늘날 피아노의 **12평균율(12-TET)**로 조율된 것이 결코 아니었습니다!

서양 음악사에서 완벽한 화음을 얻기 위한 여정은 2천 년 넘게 **피타고라스 콤마(Pythagorean Comma, $23.46 \text{ cents}$)** 및 **신토닉 콤마(Syntonic Comma, $81/80 \approx 21.51 \text{ cents}$)**라는 수학적 불일치와의 치열한 사투였습니다:
1. **피타고라스 음률(Pythagorean Tuning)**:
   기원전 6세기 피타고라스 학파는 순수 5도($3:2 = 1.5$, $701.96 \text{ cents}$)만을 거듭 쌓아 12음을 만들었습니다. 그러나 5도를 12번 쌓으면 원래 옥타브($2^7$)보다 약 23.46 센트 초과하여, 3도 화음($407.82 \text{ cents}$)이 너무 높아 극도로 거칠고 귀를 찌르는 불협화음이 발생했습니다.
2. **순정률(Just Intonation)**:
   르네상스 다성음악의 발전과 함께 화음의 울림이 중요해지며 순수 장3도($5:4 = 1.25$, $386.31 \text{ cents}$)를 채택했습니다. 화음은 천상의 소리처럼 맑고 맥놀이(Beating)가 0이지만, 기준음(C)을 벗어나 조옮김(Modulation)을 하면 건반 수가 부족하여 심각한 불협화음이 터져 나왔습니다.
3. **1/4 콤마 중전음률(Quarter-Comma Meantone Temperament)**:
   16세기 르네상스 건반 악기(하프시코드, 오르간)의 표준. 순수 장3도($386.31 \text{ cents}$) 8개를 완벽하게 살리기 위해 11개의 5도를 신토닉 콤마의 $1/4$($5.38 \text{ cents}$)씩 좁혔습니다. 그 대가로 나머지 5도 하나에 모든 오차가 몰리며 무시무시하게 울부짖는 **‘늑대 5도(Wolf Fifth, $G\sharp - E\flat \approx 737.64 \text{ cents}$)’**가 발생했습니다! 이로 인해 샤프나 플랫이 많은 조(Remote Keys, 예: $F\sharp, C\sharp, A\flat$)는 연주 자체가 불가능했습니다.
4. **잘 조율된 음률(Well-Temperament, Werckmeister III / Vallotti)**:
   안드레아스 베르크마이스터(1691) 등 바로크 음악이론가들은 늑대 5도를 완전히 없애면서 24개 모든 장·단조의 자유로운 조옮김을 가능하게 했습니다. 동시에 12평균율처럼 모든 조가 밋밋하고 똑같아지는 대신, 조표마다 화음의 협화도가 미세하게 달라지는 독특한 **'조의 성격(Key Color / Affekt)'**을 간직했습니다. 바흐는 바로 이 시스템에 감탄하여 24개 전 조(All 24 Keys)를 아우르는 전무후무한 전주곡과 푸가 전곡집을 작곡했습니다!

여러분은 음악학 및 디지털 음향학(Musicology & Acoustics) 연구원으로서, 5대 역사적 조율법의 음고(Cent)와 물리 주파수(Hz)를 계산하고, 화음의 맥놀이(Beat Frequency) 및 늑대 음정을 감별하는 **고전 건반 조율 음향학 시뮬레이터**를 구축해야 합니다!

---

## 2. 연산 규칙 및 음향학 공식

### 2.1 옥타브와 센트(Cents) 환산
- 1 옥타브는 $1200 \text{ cents}$입니다.
- 기준음 C4의 주파수 $f_{C4}$ 산출:
  A4의 기준 주파수가 $f_{A4}$ (기본 440 Hz 또는 바로크 피치 415 Hz)일 때:
  $$f_{C4} = \frac{f_{A4}}{2^{\text{cents}(A) / 1200}}$$
- 특정 음 $X$(옥타브 $oct$)의 물리 주파수:
  $$f = f_{C4} \times 2^{\frac{\text{cents}(X) + (oct - 4) \times 1200}{1200}}$$

### 2.2 5대 조율법 센트(Cent) 체계 ($C = 0 \text{ cents}$)
- **12-TET (`equal_temperament`)**: 각 반음 $100.0 \times i$ ($i = 0 \dots 11$).
- **피타고라스 (`pythagorean`)**: C=0, C#=113.69, D=203.91, D#=294.14, E=407.82, F=498.05, F#=611.73, G=701.96, G#=815.64, A=905.87, A#=996.09, B=1109.78
- **1/4 콤마 중전음률 (`quarter_comma_meantone`)**: C=0, C#=76.05, D=193.16, D#=310.26, E=386.31, F=503.42, F#=579.47, G=696.58, G#=772.63, A=889.74, A#=1006.84, B=1082.89
- **베르크마이스터 III (`werckmeister_iii`)**: C=0, C#=90.23, D=192.18, D#=294.14, E=390.23, F=498.05, F#=588.27, G=696.09, G#=792.18, A=888.27, A#=996.09, B=1092.18
- **순정률 (`just_intonation`)**: C=0, C#=111.73, D=203.91, D#=315.64, E=386.31, F=498.05, F#=590.22, G=701.96, G#=813.69, A=884.36, A#=1017.60, B=1088.27

### 2.3 늑대 음정(Wolf Interval) 판정
- 5도 음정(7반음 차이)의 이상적 순수 음정은 $701.955 \text{ cents}$ ($3:2$)입니다.
- 5도 음정의 편차 $|\text{cents} - 701.955| > 15.0 \text{ cents}$인 경우 **늑대 5도(`is_wolf = True`)**로 판정합니다.

### 2.4 화음 맥놀이 주파수(Acoustic Beat Frequency) 및 협화도
장3화음(Major Triad: Root, Third, Fifth)에서:
- 장3도 맥놀이(Beat Frequency): 근음의 5차 배음과 3음의 4차 배음의 간섭 주파수
  $$f_{\text{beat, 3rd}} = |4 \times f_{\text{third}} - 5 \times f_{\text{root}}|$$
- 완전5도 맥놀이: 근음의 3차 배음과 5음의 2차 배음의 간섭 주파수
  $$f_{\text{beat, 5th}} = |2 \times f_{\text{fifth}} - 3 \times f_{\text{root}}|$$
- 협화도 분류(`classification`):
  - 화음 내에 늑대 음정이 포함된 경우: `"DISCORDANT_WOLF"`
  - $f_{\text{beat, 3rd}} < 1.0 \text{ Hz}$ 이고 $f_{\text{beat, 5th}} < 1.0 \text{ Hz}$ 인 경우: `"PURE_CONSONANT"`
  - $f_{\text{beat, 3rd}} \le 12.0 \text{ Hz}$ 이고 $f_{\text{beat, 5th}} \le 4.0 \text{ Hz}$ 인 경우: `"TEMPERED_CONSONANT"`
  - 그 외: `"HARSH_BEATING"`
