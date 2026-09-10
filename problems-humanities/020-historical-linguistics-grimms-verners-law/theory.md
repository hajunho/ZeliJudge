# [Humanities #020 깊이 읽기] 그림의 법칙(Grimm's Law)과 베르너의 법칙(Verner's Law): 역사언어학의 수학적 엄밀성과 게르만어 자음 추이의 비밀

## 1. 비교언어학의 탄생과 음운 법칙의 예외 없는 규칙성

1786년 윌리엄 존스(William Jones) 경이 산스크리트어, 그리스어, 라틴어가 공통의 조상 언어(인도유럽조어, Proto-Indo-European, PIE)에서 분화되었음을 선언한 이래, 19세기 언어학자들은 언어의 역사적 변화가 단순한 무작위적 변질인지, 아니면 자연과학적 법칙에 의해 지배되는 현상인지를 탐구하기 시작했습니다.

1822년 독일의 야코프 그림(Jacob Grimm)은 덴마크 언어학자 라스무스 라스크(Rasmus Rask)의 초기 관찰을 계승·체계화하여, 인도유럽조어가 게르만어파(Proto-Germanic)로 갈라져 나오는 과정에서 자음 체계 전체가 거대한 회전 바퀴처럼 일제히 전이되는 **제1차 게르만어 자음 추이(First Germanic Consonant Shift)**를 정식화했습니다.

```
                  [ 인도유럽조어 (PIE) ]
                            │
       ┌────────────────────┼────────────────────┐
       ▼ (제1막)             ▼ (제2막)             ▼ (제3막)
   무성 파열음           유성 무기 파열음       유성 유기 파열음
  (p, t, k, kw)          (b, d, g, gw)         (bh, dh, gh, gwh)
       │                     │                     │
       ▼                     ▼                     ▼
   무성 마찰음            무성 파열음            유성 파열음
  (f, th, h, hw)         (p, t, k, kw)          (b, d, g, gw)
       │
       └──────────────► [ 원시 게르만어 (PGmc) ]
```

이 규칙에 따르면:
- 그리스어 *pod-* / 라틴어 *ped-* $\implies$ 영어 *foot*, 고트어 *fōtus* ($p \to f$)
- 라틴어 *dent-* $\implies$ 영어 *tooth* ($d \to t$)
- 산스크리트어 *dhā-* $\implies$ 영어 *do* ($d^h \to d$)

---

## 2. 50년간의 수수께끼: '아버지'와 '형제'의 불일치

그림의 법칙은 놀라운 예측력을 보였지만, 곧이어 수많은 고전 문헌학자들을 곤혹스럽게 만드는 설명 불가능한 '예외'들이 발견되었습니다.

가장 대표적인 사례가 바로 친족 명칭의 불일치였습니다:
- **형제(Brother)**:
  - 산스크리트어: *bhrā́tar* (첫 음절에 강세)
  - 고트어: *brōþar* (무성 마찰음 $\theta$)
  - 영어: *brother* $\implies$ 그림의 법칙 제1막($t \to th$)에 완벽히 부합!
- **아버지(Father)**:
  - 산스크리트어: *pitár* (둘째 음절에 강세)
  - 고트어: *fadar* (유성음 $d$)
  - 영어: *father* (고대영어 *fæder*) $\implies$ 그림의 법칙에 따르면 $\*fa\theta ar$여야 하는데, 어째서 유성 파열음 $d$가 되었는가?
- **백(Hundred)**:
  - 그리스어: *hekatón* (둘째 음절에 강세)
  - 고트어: *hund* $\implies$ $\*hun\theta$가 아니라 유성음 $d$!

초기 학자들은 이를 단순한 '불규칙한 언어적 부패'나 '예외'로 치부하려 했습니다.

---

## 3. 카를 베르너의 통찰: 잃어버린 고대 악센트의 부활

1877년 덴마크의 젊은 언어학자 카를 베르너(Karl Verner)는 "음운 법칙에는 예외가 없다(Ausnahmslosigkeit der Lautgesetze)"는 신문법학파(Neogrammarians)의 신념을 입증하는 세기의 논문 **『Eine Ausnahme der ersten Lautverschiebung』(제1차 자음 추이의 한 가지 예외에 대하여)**를 발표했습니다.

베르너의 천재성은 게르만어 자체에는 이미 사라지고 없었던 **고대 인도유럽조어의 고저 악센트(Pitch Accent)**를 베다 산스크리트어와 고대 그리스어의 강세 위치와 대조 분석한 데 있었습니다.

```
  [ PIE *bhrā́-tēr ]                    [ PIE *pǝ-tḗr ]
   1st syllable ACCENTED                2nd syllable ACCENTED (Oxytone)
   Preceding vowel: *ā́ (ACCENTED)       Preceding vowel: *ǝ (UNACCENTED)
         │                                    │
         ▼ (Grimm Act 1)                      ▼ (Grimm Act 1)
     *brō-þar                             *fa-þar
         │                                    │
         ▼ (Verner: BLOCKED by accent!)       ▼ (Verner: TRIGGERED by unaccented ǝ!)
     *brōþar (Gothic)                     *fadar (Gothic / OE fæder)
     Voiceless fricative retained!        Voiced to 'd' (or ð)!
```

### 베르너의 법칙 정식화:
> 게르만어의 무성 마찰음 $f, \theta, x, s$가 유성음(모음 또는 공명음) 사이에 위치할 때, **그 직전 모음에 인도유럽조어의 원시 강세가 실리지 않았던 경우에 한하여**, 해당 마찰음은 유성화되어 각각 $\beta(b), \eth(d), \gamma(g), z(r)$로 바뀐다.

이 발견으로 인해, '아버지'와 '형제'의 자음 차이는 임의적인 우연이 아니라 수천 년 전 조상 언어의 강세 위치 차이가 게르만어 자음에 남겨놓은 **화석화된 음운학적 지문**임이 밝혀졌습니다.

---

## 4. 문법적 교체(Grammatischer Wechsel)와 강변화 동사

베르너의 법칙은 명사뿐만 아니라 게르만어 강변화 동사의 시제별 어간 자음 교체(Grammatical Alternation)의 비밀도 완벽하게 풀어냈습니다:
- **고대영어 *weorþan*(되다, turn)**:
  - 현재형: *ic weorþe* (원시 인도유럽조어 어간 강세 $\implies$ 무성 마찰음 $\theta / \text{þ}$)
  - 과거 분사형: *geworden* (원시 인도유럽조어 접미사 강세 $\*wurt-e-nós$ $\implies$ 베르너 법칙 발동, 유성음 $d$!)
- **현대 독일어의 흔적**:
  - *schneiden*(자르다) $\to$ 과거분사 *geschnitten* ($d \to t$)
  - *ziehen*(당기다, $h$) $\to$ 과거분사 *gezogen* ($g$, Verner $h \to g$)

---

## 5. 역사언어학과 컴퓨터 인문학의 융합

베르너의 법칙은 언어학이 자연과학(물리학, 화학)에 필적하는 엄밀한 인과율과 수학적 규칙성을 지니고 있음을 인문학계에 최초로 각인시킨 기념비적 사건이었습니다.

현대 컴퓨터 언어학과 진화언어학(Evolutionary Linguistics)에서는 이러한 규칙 적용 순서(Rule Ordering: Feeding relationship between Grimm's Law and Verner's Law)를 오토마타와 상태 전이 그래프로 전산화하여, 기록이 남아있지 않은 선사시대 인류의 언어를 100% 디지털로 복원하는 어원 재구(Automated Etymological Reconstruction) 기술로 계승·발전시키고 있습니다.
