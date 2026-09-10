# 기호학과 고전 암호학의 혁명: 알베르티(Alberti) 암호 원반, 트리테미우스(Trithemius) 타불라 렉타, 카시스키(Kasiski) 시험 및 프리드먼 일치지수(IC) 기반 다중 치환 암호 분석 엔진

## 문제 설명

인류 역사에서 고대 로마의 카이사르 암호(Caesar Cipher)와 같은 단일 치환(Monoalphabetic Substitution) 방식은 9세기 아랍의 철학자이자 기호학자인 알 킨디(Al-Kindi)가 **빈도 분석법(Frequency Analysis)**을 발견한 이래 완전히 무력화되었습니다. 단어 속 특정 글자(예: 영어의 E, T, A)의 통계적 출현 빈도가 암호문에서도 고스란히 보존되었기 때문입니다.

1467년, 이탈리아 르네상스의 인문주의자이자 기호학자, 건축가인 **레온 바티스타 알베르티(Leon Battista Alberti)**는 암호학 역사의 일대 혁명을 일으켰습니다. 그는 외경 고정 원반과 내경 회전 원반으로 구성된 **알베르티 암호 원반(Alberti Cipher Disk)**을 발명하여, 한 문장 내에서도 글자를 쓸 때마다 원반을 회전시켜 동일한 평문 글자(예: 'E')가 매번 다른 암호문 글자로 치환되는 **다중 치환 암호(Polyalphabetic Cipher)** 체계를 최초로 확립했습니다.

이 원리는 1518년 요하네스 트리테미우스(Johannes Trithemius)의 《폴리그라피아(Polygraphia)》 속 **타불라 렉타(Tabula Recta)**를 거쳐 16세기 블레즈 드 비즈네르(Blaise de Vigenère)에 의해 완성되었으며, 이후 수백 년 동안 *"해독 불가능한 암호(le chiffre indéchiffrable)"*로 군림했습니다.

그러나 19세기, 언어학자이자 프로이센 장교인 **프리드리히 카시스키(Friedrich Kasiski, 1863)**와 현대 암호학의 아버지 **윌리엄 프리드먼(William F. Friedman, 1922)**은 정보 이론과 통계학을 결합하여 이 난공불락의 암호를 수학적으로 해체하는 알고리즘을 발견했습니다:

1. **카시스키 시험 (Kasiski Examination)**:
   - 평문에서 우연히 같은 단어가 키 길이($L$)의 정수배 간격으로 떨어져 있으면, 암호문에서도 동일한 길이 $m \ge 3$의 n-gram 문자열이 반복 출현합니다.
   - 반복 출현하는 문자열들의 위치 간격($\Delta d = |pos_j - pos_i|$)을 모두 구하고, 이 간격들의 공약수(Factors) 빈도를 히스토그램으로 집계하면 키 길이 후보를 신속하게 좁힐 수 있습니다.
2. **프리드먼의 일치지수 (Index of Coincidence, $IC$)**:
   - 텍스트에서 임의로 추출한 두 글자가 서로 일치할 확률:
     $$IC = \frac{\sum_{c=A}^Z f_c(f_c - 1)}{N(N - 1)}$$
   - 영어 자연어 평문의 일치지수는 $IC_{\text{mono}} \approx 0.0667$인 반면, 무작위 균등 분포(다중 치환)의 일치지수는 $IC_{\text{poly}} \approx 0.0385$로 수렴합니다.
   - 후보 키 길이 $L$에 대해 암호문을 $L$개의 서브스트림($S_0, \dots, S_{L-1}$, 여기서 $S_k$는 $i \equiv k \pmod L$인 문자들)으로 분할했을 때, **각 서브스트림의 평균 $IC$가 $0.06$ 이상으로 급등하는 $L$이 진정한 키 길이**입니다!
3. **카이제곱($\chi^2$) 통계량을 통한 키워드 및 평문 복원**:
   - $L$개의 각 서브스트림에 대해 26가지 카이사르 시프트($s \in [0, 25]$)를 적용한 뒤, 영어 표준 알파벳 빈도와의 카이제곱 거리를 계산합니다:
     $$\chi^2(s) = \sum_{c='A'}^{'Z'} \frac{(O_c(s) - E_c)^2}{E_c}$$
   - 카이제곱 통계량이 최소화되는 시프트 $s^*$를 취하여 키 문자 $K_k = \text{chr}(\text{ord}('A') + s^*)$를 복원하고, 최종 평문을 무결하게 복호화합니다.

본 문제에서는 다중 치환 암호문이 주어졌을 때, 카시스키 시험, 프리드먼 일치지수 분석, 카이제곱 통계량을 순차적으로 실행하여 키 길이, 비밀 키워드, 알베르티 원반 회전각 및 평문을 자동으로 복원하는 **기호학 및 고전 암호 분석 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)을 통해 단일 JSON 객체가 전달됩니다:

```json
{
  "max_key_length": 12,
  "messages": [
    {
      "id": "msg_1",
      "ciphertext": "LXFOPVEFRNHRMHGLGWOGOEIBNEXMQXLXPOJY"
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 compact한 단일 행 JSON 문자열을 출력합니다:

```json
{
  "total_messages_analyzed": 1,
  "results": [
    {
      "id": "msg_1",
      "text_length": 36,
      "overall_index_of_coincidence": 0.0381,
      "friedman_estimated_key_length": 5.2,
      "kasiski_top_factors": [5, 2, 3],
      "ic_by_key_length": { "1": 0.0381, "2": 0.0392, "5": 0.0645 },
      "detected_key_length": 5,
      "recovered_key": "LEMON",
      "is_monoalphabetic": false,
      "alberti_disk_rotations": [11, 4, 12, 14, 13],
      "decrypted_plaintext": "ATTACKATDAWNATTACKATDAWNATTACKATDAWN"
    }
  ]
}
```
