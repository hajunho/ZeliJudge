# [음악학/음향학/컴퓨터음악] 피타고라스 음률(Pythagorean Tuning)과 순정률·12평균율 비교, 피타고라스 콤마(Comma) 및 플롬프-레벨트(Plomp-Levelt) 화음 불협화도(Dissonance) 전산 음향 엔진

## 문제 설명

고대 그리스의 철학자 피타고라스(Pythagoras)는 대장간의 망치 소리와 현의 길이 비율($1:2$ 옥타브, $2:3$ 완전 5도, $3:4$ 완전 4도)에서 우주의 수학적 질서(Musica Universalis)를 발견했습니다.
동양에서도 춘추전국시대 관자(管子)와 한서(漢書) 율력지에서 대나무 관의 길이를 $1/3$ 덜어내고(三分損一, $2/3$) $1/3$ 더하는(三分益一, $4/3$) **삼분손익법(三分損益法)**을 통해 12율려(황종, 대려, 태주 등)를 도출하여, 동서양 문명이 완벽히 동일한 음향 수학적 원리를 독자 발견했습니다.

그러나 순수한 완전 5도($3/2$)를 12번 거듭 쌓아 올렸을 때 중대한 수학적 모순이 발생합니다:
- 완전 5도를 12번 쌓은 진동수 비율:
  $$\left(\frac{3}{2}\right)^{12} = \frac{531441}{4096} \approx 129.7463$$
- 옥타브($2$)를 7번 쌓은 진동수 비율:
  $$2^7 = 128$$
- 두 수의 차이인 **피타고라스 콤마(Pythagorean Comma)**:
  $$\text{Comma} = \frac{(3/2)^{12}}{2^7} = \frac{531441}{524288} \approx 1.013643 \quad (23.46 \text{ cents})$$

이 $23.46\text{ 센트}$의 불일치로 인해, 피타고라스 음률에서는 원환의 마지막 5도 구간에서 심한 맥놀이(Beating)와 불협화음을 유발하는 악명 높은 **울프 5도(Wolf Fifth, 678.49 cents)**가 발생합니다.
서양 음악사는 이 콤마의 잉여를 해결하기 위해 중전음률(Meantone Temperament), 순정률(Just Intonation, 5-limit pure thirds $5/4$), 그리고 바흐의 평균율 클라비어곡집으로 유명한 **12평균율(12-Tone Equal Temperament, 12-TET)**을 개발했습니다.
12평균율은 옥타브를 12개의 균등한 반음 비율($\sqrt[12]{2} \approx 1.059463$)로 나누어 조옮김(Transposition)을 자유롭게 만든 대신, 모든 3도와 5도에 미세한 순도 손실(Major Third가 순정 386 cents 대비 400 cents로 14 cents 날카로움)을 감수했습니다.

인지 음향학(Psychoacoustics)에서는 **플롬프-레벨트(Plomp-Levelt, 1965)** 모델을 통해 두 음의 배음(Harmonics) 구조와 임계 대역폭(Critical Bandwidth) 간의 간섭으로 발생하는 **감각적 거칠기(Sensory Roughness / Dissonance)**를 수학적으로 정밀하게 계산합니다.

음악학 및 컴퓨터 오디오 신호처리 연구팀의 일원이 되어, 기준 음높이($C_4$)를 바탕으로 12평균율, 피타고라스 음률, 순정률의 12음 진동수와 센트(Cents) 편차를 계산하고, 피타고라스 콤마와 울프 5도의 패널티를 정량화하며, 플롬프-레벨트 배음 간섭 적분을 통해 임의의 화음(Chord)과 음정의 불협화도(Dissonance) 및 협화도 순위를 자동 도출하는 **컴퓨터 음악학 조율 및 화음 협화도 분석 엔진**을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "base_c4_hz": 261.625565,
  "num_harmonics": 6,
  "queries": [
    {
      "query_id": "Q1",
      "type": "SCALE_TABLE",
      "tuning_system": "12-TET"
    },
    {
      "query_id": "Q2",
      "type": "CHORD_DISSONANCE",
      "tuning_system": "JUST_INTONATION",
      "chords": [
        {"name": "Octave", "notes": ["C4", "C5"]},
        {"name": "Major_Third", "notes": ["C4", "E4"]},
        {"name": "Minor_Second", "notes": ["C4", "C#4"]}
      ]
    },
    {
      "query_id": "Q3",
      "type": "WOLF_FIFTH_COMPARISON"
    }
  ]
}
```

- `base_c4_hz` (Float): 가온 다($C_4$) 기준 진동수 (기본값: $261.625565\text{ Hz}$, $A_4=440\text{ Hz}$ 기준).
- `num_harmonics` (Integer): 불협화도 계산 시 고려할 배음(Harmonics) 개수 (기본값: 6, $k=1 \dots 6$, 진폭 $a_k = 1/k$).
- `queries`:
  - `query_id` (String): 쿼리 고유 식별자
  - `type` (String): `"SCALE_TABLE"`, `"CHORD_DISSONANCE"`, `"WOLF_FIFTH_COMPARISON"`
  - `tuning_system` (String): `"12-TET"`, `"PYTHAGOREAN"`, `"JUST_INTONATION"`

---

## 출력 형식

표준 출력(stdout)으로 음률 콤마 정보와 쿼리별 계산 결과가 포함된 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "commas": {
    "pythagorean_comma": {
      "ratio": 1.013643,
      "cents": 23.46,
      "description": "12 perfect fifths vs 7 octaves shortfall"
    },
    "syntonic_comma": {
      "ratio": 1.0125,
      "cents": 21.51,
      "description": "Pythagorean ditone (81/64) vs pure major third (5/4)"
    }
  },
  "results": [ ... ]
}
```
