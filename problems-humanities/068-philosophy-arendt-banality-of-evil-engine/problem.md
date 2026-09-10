# 한나 아렌트의 예루살렘의 아이히만: 악의 평범성(Banality of Evil), 관료제적 사유 불능 및 도덕적 외주화 판정 엔진 (Hannah Arendt Banality of Evil & Bureaucratic Thoughtlessness Engine)

## 문제 설명

20세기 최고의 정치철학자 한나 아렌트(Hannah Arendt)는 1961년 예루살렘 법정에서 열린 나치 전범 아돌프 아이히만(Adolf Eichmann)의 재판을 취재하며 저작 『예루살렘의 아이히만: 악의 평범성에 대한 보고서(Eichmann in Jerusalem: A Report on the Banality of Evil, 1963)』를 발표했습니다.

전 세계인들은 수백만 명의 유대인을 기차에 태워 가스실로 보낸 장본인이 피에 굶주린 광신적 악마나 사이코패스일 것이라 예상했으나, 법정에 선 아이히만은 그저 상관의 명령을 준수하고 승진을 열망하는 **"지극히 평범하고 성실한 관료"**에 불과했습니다.

아렌트는 역사상 가장 참혹한 악이 악마적 악의에서가 아니라, **"타인의 입장에서 생각하는 능력이 마비된 무사유(Thoughtlessness, Gedankenlosigkeit)"**와 자신의 윤리적 판단을 조직의 법령과 명령에 백지위임하는 **"도덕적 외주화(Moral Outsourcing)"**에서 비롯된다는 **'악의 평범성(The Banality of Evil)'** 개념을 정립했습니다.

```
+---------------------------------------------------------------------------------+
|               한나 아렌트의 '악의 평범성' 인지·행동 분석 아키텍처                |
+---------------------------------------------------------------------------------+
|  상관의 명령 수신 (Receive Bureaucratic Orders)                                 |
+---------------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                     사유 불능 (Thoughtlessness, T)                        |
   |                     "나 자신과의 소리 없는 대화(Two-in-one)" 부재         |
   |                     반성적 성찰(Reflection) 및 의문 제기 결여            |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |             상투어 및 완곡어법 의존도 (Cliche Reliance, C)                |
   |  - 나치 관료제 언어 규칙(Sprachregelung): "최종 해결책", "특별 취급"      |
   |  - 현실을 차단하는 상투적 슬로건 및 관료적 클리셰 맹종                    |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                 도덕적 외주화 (Moral Outsourcing, M)                      |
   |  - 내면의 양심을 폐기하고 "명령 준수(Befehl ist Befehl)"에 복종          |
   |  - 맹목적 집행 비율: orders_blindly_executed / orders_received           |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |                     공감 결여 (Lack of Empathy, E)                        |
   |  - 타인의 고통을 상상하는 '확장된 심상(Enlarged Mentality)' 부재         |
   +---------------------------------------------------------------------------+
                                         |
                                         v
               +---------------------------------------------------+
               |  악의 평범성 지수 B (Banality of Evil Index)       |
               |  B = 0.35*T + 0.30*C + 0.25*M + 0.10*E           |
               +---------------------------------------------------+
                       |                                    |
          B >= 0.70    |                       B < 0.40     |
          v            v                                    v
   [ BANALITY_OF_EVIL ]    [ BUREAUCRATIC_CONFORMISM ]  [ AUTONOMOUS_CRITICAL ]
   (사유 정지된 살인기계)   (0.40 <= B < 0.70 체제순응)   (비판적 저항과 양심)
```

### 1. 4대 핵심 평가 지표와 계산 수식

#### 1.1 사유 불능 지수 (Thoughtlessness, $T$)
스스로 생각하고 권위에 질문을 던지는 내면적 성찰 수준을 측정합니다:
$$	ext{reflection\_score} = \min(1.0, 	ext{critical\_inquiries} 	imes 0.3 + 	ext{self\_reflections} 	imes 0.2)$$
$$T = 	ext{round}(\max(0.0, 1.0 - 	ext{reflection\_score}), 4)$$

#### 1.2 상투어 의존도 지수 (Cliche Reliance, $C$)
현실의 참혹함을 은폐하는 관료제적 완곡어법(`euphemisms`)과 상투어구(`cliche_phrases_count`)에 의존하는 비율입니다:
$$	ext{cliche\_total} = 	ext{euphemisms\_used} + 	ext{cliche\_count}$$
$$	ext{vocab\_total} = 	ext{cliche\_total} + 	ext{critical\_inquiries}$$
$$C = 	ext{round}\left(\min\left(1.0, rac{	ext{cliche\_total}}{	ext{vocab\_total}}ight), 4ight) \quad (	ext{단, vocab\_total} = 0	ext{이면 } 0.0)$$

#### 1.3 도덕적 외주화 지수 (Moral Outsourcing, $M$)
자신의 행위가 야기할 결과를 고민하지 않고 맹목적으로 상관의 명령을 집행한 비율입니다:
$$M = 	ext{round}\left(rac{	ext{orders\_blindly\_executed}}{\max(1, 	ext{orders\_received})}, 4ight)$$

#### 1.4 공감 결여도 (Lack of Empathy, $E$)
타인의 입장에서 상상하고 공감하는 능력의 부재 여부입니다:
$$E = 0.0 \quad (	ext{empathy\_shown == True}), \quad 1.0 \quad (	ext{empathy\_shown == False})$$

### 2. 종합 악의 평범성 지수 ($B$) 및 주체 상태 판정
$$B = 	ext{round}(\min(1.0, 0.35 	imes T + 0.30 	imes C + 0.25 	imes M + 0.10 	imes E), 4)$$

- **`BANALITY_OF_EVIL`** ($B \ge 0.70$):
  사유 기능이 완전히 마비되어, 관료제의 나사못(Cog in the machine)으로서 아무런 죄책감 없이 참극을 집행하는 상태.
- **`BUREAUCRATIC_CONFORMISM`** ($0.40 \le B < 0.70$):
  소극적 양심의 가책이나 공감을 느끼면서도 제도와 조직의 규범에 순응하는 체제 순응적 방관자.
- **`AUTONOMOUS_CRITICAL_CONSCIENCE`** ($B < 0.40$):
  부당한 권력에 맞서 도덕적 질문을 던지고 자율적 윤리 판단과 공감을 실천하는 주체.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "bureaucratic_euphemisms": ["special_treatment", "final_solution"],
    "critical_inquiry_keywords": ["moral_responsibility", "human_dignity"]
  },
  "operations": [
    {
      "op": "REGISTER_AGENT",
      "agent_id": "eichmann_01",
      "name": "Adolf Eichmann",
      "role": "Section Chief"
    },
    {
      "op": "PROCESS_ACTION",
      "agent_id": "eichmann_01",
      "action": {
        "type": "EXECUTE_ORDER",
        "blind_compliance": true,
        "euphemisms": ["special_treatment", "final_solution"],
        "cliche_phrases_count": 2,
        "critical_inquiries": [],
        "empathy_shown": false
      }
    }
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "evaluations": 1,
    "banality_of_evil_count": 1,
    "bureaucratic_conformism_count": 0,
    "autonomous_conscience_count": 0,
    "max_banality_index": 1.0
  },
  "agents": {
    "eichmann_01": {
      "name": "Adolf Eichmann",
      "role": "Section Chief",
      "orders_received": 1,
      "orders_blindly_executed": 1,
      "euphemisms_used": 2,
      "critical_inquiries": 0,
      "banality_index": 1.0,
      "state": "BANALITY_OF_EVIL"
    }
  },
  "history": [...],
  "event_log": [...]
}
```
