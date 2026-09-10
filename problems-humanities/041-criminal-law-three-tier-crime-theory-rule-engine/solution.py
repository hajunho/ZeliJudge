import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import sys
import json

def evaluate_single_case(case):
    case_id = case.get("case_id", "CASE_000")
    defendant = case.get("defendant", {})
    charge = case.get("charge", {})
    tier1 = case.get("tier1_facts", {})
    tier2 = case.get("tier2_justification", {})
    tier3 = case.get("tier3_culpability", {})
    
    reasoning = []
    
    # Tier 1: Constituent Elements (구성요건 해당성)
    act_ok = tier1.get("act_committed", False)
    res_ok = tier1.get("result_occurred", False)
    caus_ok = tier1.get("causality_established", False)
    
    if not (act_ok and res_ok and caus_ok):
        reasoning.append({
            "tier": 1,
            "element": "OBJECTIVE_ELEMENTS",
            "passed": False,
            "detail": f"객관적 구성요건 탈락 (실행행위:{act_ok}, 결과발생:{res_ok}, 인과관계:{caus_ok})"
        })
        return {
            "case_id": case_id,
            "stage_reached": "TIER_1_CONSTITUENT_ELEMENTS",
            "verdict": "NOT_GUILTY_NO_CONSTITUENT_ELEMENT",
            "guilty": False,
            "reasoning_chain": reasoning,
            "sentencing": {
                "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                "mitigations": [],
                "final_penalty_months": 0.0
            }
        }
    
    # Subjective elements (고의 및 과실, 사실의 착오)
    mens_rea = tier1.get("mens_rea", "NONE")
    mistake_fact = tier1.get("mistake_of_fact", False)
    negligence_punishable = charge.get("negligence_punishable", False)
    
    if mistake_fact:
        if mens_rea == "NEGLIGENCE" and negligence_punishable:
            reasoning.append({
                "tier": 1,
                "element": "SUBJECTIVE_ELEMENTS",
                "passed": True,
                "detail": "사실의 착오로 고의 조각, 과실범 구성요건 충족(처벌규정 존재)"
            })
        else:
            reasoning.append({
                "tier": 1,
                "element": "SUBJECTIVE_ELEMENTS",
                "passed": False,
                "detail": "사실의 착오로 고의 조각 및 과실범 불성립"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_1_CONSTITUENT_ELEMENTS",
                "verdict": "NOT_GUILTY_NO_CONSTITUENT_ELEMENT",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }
    else:
        if mens_rea in ["INTENT_DIRECT", "INTENT_CONDITIONAL"]:
            reasoning.append({
                "tier": 1,
                "element": "SUBJECTIVE_ELEMENTS",
                "passed": True,
                "detail": f"고의({mens_rea}) 인정으로 주관적 구성요건 충족"
            })
        elif mens_rea == "NEGLIGENCE":
            if negligence_punishable:
                reasoning.append({
                    "tier": 1,
                    "element": "SUBJECTIVE_ELEMENTS",
                    "passed": True,
                    "detail": "과실 인정 및 과실범 처벌규정 존재로 구성요건 충족"
                })
            else:
                reasoning.append({
                    "tier": 1,
                    "element": "SUBJECTIVE_ELEMENTS",
                    "passed": False,
                    "detail": "과실 인정되나 법률상 과실범 처벌규정 결여 (형법 제14조)"
                })
                return {
                    "case_id": case_id,
                    "stage_reached": "TIER_1_CONSTITUENT_ELEMENTS",
                    "verdict": "NOT_GUILTY_NO_CONSTITUENT_ELEMENT",
                    "guilty": False,
                    "reasoning_chain": reasoning,
                    "sentencing": {
                        "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                        "mitigations": [],
                        "final_penalty_months": 0.0
                    }
                }
        else:
            reasoning.append({
                "tier": 1,
                "element": "SUBJECTIVE_ELEMENTS",
                "passed": False,
                "detail": "고의 또는 과실의 완전 결여"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_1_CONSTITUENT_ELEMENTS",
                "verdict": "NOT_GUILTY_NO_CONSTITUENT_ELEMENT",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }

    # Tier 2: Illegality & Justification (위법성 및 위법성 조각사유)
    mitigation_excessive_defense = False
    claimed_defense = tier2.get("claimed_defense", "NONE")
    
    if claimed_defense == "SELF_DEFENSE":
        unlawful = tier2.get("unlawful_attack_imminent", False)
        intent = tier2.get("defensive_intent", False)
        prop = tier2.get("proportionality", False)
        fear = tier2.get("nighttime_or_fear", False)
        
        if unlawful and intent:
            if prop:
                reasoning.append({
                    "tier": 2,
                    "defense": "SELF_DEFENSE",
                    "justified": True,
                    "detail": "형법 제21조 제1항 정당방위 성립 (위법성 조각)"
                })
                return {
                    "case_id": case_id,
                    "stage_reached": "TIER_2_ILLEGALITY",
                    "verdict": "NOT_GUILTY_JUSTIFIED_SELF_DEFENSE",
                    "guilty": False,
                    "reasoning_chain": reasoning,
                    "sentencing": {
                        "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                        "mitigations": [],
                        "final_penalty_months": 0.0
                    }
                }
            else:
                if fear:
                    reasoning.append({
                        "tier": 2,
                        "defense": "EXCESSIVE_DEFENSE_FEAR",
                        "justified": False,
                        "exculpated": True,
                        "detail": "형법 제21조 제3항 야간 등 공포·경악에 의한 면책적 과잉방위 (벌하지 아니함)"
                    })
                    return {
                        "case_id": case_id,
                        "stage_reached": "TIER_2_ILLEGALITY",
                        "verdict": "NOT_PUNISHABLE_EXCULPATED_EXCESSIVE_DEFENSE_FEAR",
                        "guilty": False,
                        "reasoning_chain": reasoning,
                        "sentencing": {
                            "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                            "mitigations": [],
                            "final_penalty_months": 0.0
                        }
                    }
                else:
                    mitigation_excessive_defense = True
                    reasoning.append({
                        "tier": 2,
                        "defense": "EXCESSIVE_DEFENSE",
                        "justified": False,
                        "detail": "상당성 초과 과잉방위 (위법성 미조각, 형법 제21조 제2항 법정감경 대상)"
                    })
        else:
            reasoning.append({
                "tier": 2,
                "defense": "SELF_DEFENSE",
                "justified": False,
                "detail": "현재의 부당한 침해 또는 방위의사 결여로 정당방위 불성립"
            })
            
    elif claimed_defense == "EMERGENCY_NECESSITY":
        danger = tier2.get("imminent_danger", False)
        sup = tier2.get("superior_interest", False)
        last = tier2.get("last_resort", False)
        if danger and sup and last:
            reasoning.append({
                "tier": 2,
                "defense": "EMERGENCY_NECESSITY",
                "justified": True,
                "detail": "형법 제22조 제1항 긴급피난 성립 (위법성 조각)"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_2_ILLEGALITY",
                "verdict": "NOT_GUILTY_JUSTIFIED_NECESSITY",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }
        else:
            reasoning.append({
                "tier": 2,
                "defense": "EMERGENCY_NECESSITY",
                "justified": False,
                "detail": "위난·법익균형·보충성 요건 흠결로 긴급피난 불성립"
            })

    elif claimed_defense == "VICTIM_CONSENT":
        consent = tier2.get("valid_consent", False)
        alienable = tier2.get("alienable_interest", False)
        if consent and alienable:
            reasoning.append({
                "tier": 2,
                "defense": "VICTIM_CONSENT",
                "justified": True,
                "detail": "형법 제24조 피해자의 승낙 성립 (위법성 조각)"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_2_ILLEGALITY",
                "verdict": "NOT_GUILTY_JUSTIFIED_CONSENT",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }
        else:
            reasoning.append({
                "tier": 2,
                "defense": "VICTIM_CONSENT",
                "justified": False,
                "detail": "처분불가 법익 또는 무효인 승낙으로 위법성 미조각"
            })

    elif claimed_defense == "JUSTIFIED_ACT":
        statutory = tier2.get("statutory_or_customary", False)
        if statutory:
            reasoning.append({
                "tier": 2,
                "defense": "JUSTIFIED_ACT",
                "justified": True,
                "detail": "형법 제20조 정당행위 성립 (위법성 조각)"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_2_ILLEGALITY",
                "verdict": "NOT_GUILTY_JUSTIFIED_ACT",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }
        else:
            reasoning.append({
                "tier": 2,
                "defense": "JUSTIFIED_ACT",
                "justified": False,
                "detail": "사회상규 또는 법령·업무 정당행위 요건 미충족"
            })
    else:
        reasoning.append({
            "tier": 2,
            "defense": "NONE",
            "justified": False,
            "detail": "위법성 조각사유 부존재 (위법성 인정)"
        })

    # Tier 3: Culpability (책임론 및 책임조각/감경 사유)
    age = defendant.get("age", 20)
    if age < 14:
        reasoning.append({
            "tier": 3,
            "culpability_factor": "JUVENILE",
            "exculpated": True,
            "detail": f"형법 제9조 형사미성년자(만 {age}세 < 14세)로 책임 조각 (벌하지 아니함)"
        })
        return {
            "case_id": case_id,
            "stage_reached": "TIER_3_CULPABILITY",
            "verdict": "NOT_PUNISHABLE_EXCULPATED_JUVENILE",
            "guilty": False,
            "reasoning_chain": reasoning,
            "sentencing": {
                "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                "mitigations": [],
                "final_penalty_months": 0.0
            }
        }
        
    duress_data = tier3.get("duress", {})
    if duress_data.get("coerced", False) and duress_data.get("unavoidable_force_or_threat", False):
        reasoning.append({
            "tier": 3,
            "culpability_factor": "DURESS",
            "exculpated": True,
            "detail": "형법 제12조 강요된 행위 성립으로 기대가능성 결여, 책임 조각 (벌하지 아니함)"
        })
        return {
            "case_id": case_id,
            "stage_reached": "TIER_3_CULPABILITY",
            "verdict": "NOT_PUNISHABLE_EXCULPATED_DURESS",
            "guilty": False,
            "reasoning_chain": reasoning,
            "sentencing": {
                "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                "mitigations": [],
                "final_penalty_months": 0.0
            }
        }
        
    mol_data = tier3.get("mistake_of_law", {})
    if mol_data.get("mistake_claimed", False):
        if mol_data.get("justifiable_ground", False):
            reasoning.append({
                "tier": 3,
                "culpability_factor": "MISTAKE_OF_LAW",
                "exculpated": True,
                "detail": "형법 제16조 법률의 착오에 정당한 이유 인정, 책임 조각 (벌하지 아니함)"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_3_CULPABILITY",
                "verdict": "NOT_PUNISHABLE_EXCULPATED_MISTAKE_OF_LAW",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }
        else:
            reasoning.append({
                "tier": 3,
                "culpability_factor": "MISTAKE_OF_LAW",
                "exculpated": False,
                "detail": "법률의 착오에 정당한 이유 부존재 (책임 인정)"
            })

    mental_cond = defendant.get("mental_condition", "NORMAL")
    actio_libera = defendant.get("actio_libera_in_causa", False)
    mitigation_diminished = False
    
    if actio_libera:
        reasoning.append({
            "tier": 3,
            "culpability_factor": "ACTIO_LIBERA_IN_CAUSA",
            "detail": "형법 제10조 제3항 원인에 있어서 자유로운 행위 해당 (심신장애 감면 규정 적용 배제)"
        })
    else:
        if mental_cond == "INSANITY":
            reasoning.append({
                "tier": 3,
                "culpability_factor": "INSANITY",
                "exculpated": True,
                "detail": "형법 제10조 제1항 심신상실로 사물변별·의사결정능력 결여, 책임 조각 (벌하지 아니함)"
            })
            return {
                "case_id": case_id,
                "stage_reached": "TIER_3_CULPABILITY",
                "verdict": "NOT_PUNISHABLE_EXCULPATED_INSANITY",
                "guilty": False,
                "reasoning_chain": reasoning,
                "sentencing": {
                    "base_penalty_months": int(charge.get("base_penalty_months", 0)),
                    "mitigations": [],
                    "final_penalty_months": 0.0
                }
            }
        elif mental_cond == "DIMINISHED":
            mitigation_diminished = True
            reasoning.append({
                "tier": 3,
                "culpability_factor": "DIMINISHED_CAPACITY",
                "detail": "형법 제10조 제2항 심신미약 인정 (법정감경 사유)"
            })

    reasoning.append({
        "tier": 3,
        "culpability_factor": "FULL_RESPONSIBILITY",
        "detail": "책임 능력 및 기대가능성 인정 -> 범죄 성립 및 유죄 판결"
    })
    
    base_penalty = float(charge.get("base_penalty_months", 0))
    penalty = base_penalty
    mitigations = []
    
    if mitigation_excessive_defense:
        mitigations.append("EXCESSIVE_DEFENSE_MITIGATION")
        penalty = penalty * 0.5
    if mitigation_diminished:
        mitigations.append("DIMINISHED_CAPACITY_MITIGATION")
        penalty = penalty * 0.5
        
    return {
        "case_id": case_id,
        "stage_reached": "VERDICT_RENDERED",
        "verdict": "CRIME_ESTABLISHED_GUILTY",
        "guilty": True,
        "reasoning_chain": reasoning,
        "sentencing": {
            "base_penalty_months": int(base_penalty),
            "mitigations": mitigations,
            "final_penalty_months": round(penalty, 2)
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    mode = data.get("mode", "EVALUATE_CASE")
    
    if mode == "EVALUATE_CASE":
        case_data = data.get("case", {})
        result = evaluate_single_case(case_data)
        print(json.dumps(result, ensure_ascii=False))
        
    elif mode == "BATCH_TRIAL_ANALYTICS":
        cases = data.get("cases", [])
        total_cases = len(cases)
        verdict_list = []
        guilty_sentences = []
        guilty_count = 0
        justified_count = 0
        exculpated_count = 0
        constituent_fail_count = 0
        verdicts_summary = {}
        
        for c in cases:
            res = evaluate_single_case(c)
            verdict_list.append(res)
            v = res["verdict"]
            verdicts_summary[v] = verdicts_summary.get(v, 0) + 1
            
            if res["guilty"]:
                guilty_count += 1
                guilty_sentences.append(res["sentencing"]["final_penalty_months"])
            elif v.startswith("NOT_GUILTY_JUSTIFIED_"):
                justified_count += 1
            elif v.startswith("NOT_PUNISHABLE_EXCULPATED_"):
                exculpated_count += 1
            elif v == "NOT_GUILTY_NO_CONSTITUENT_ELEMENT":
                constituent_fail_count += 1
                
        avg_sentence = round(sum(guilty_sentences) / len(guilty_sentences), 2) if guilty_sentences else 0.0
        
        out = {
            "total_cases": total_cases,
            "conviction_rate": round(guilty_count / total_cases, 4) if total_cases > 0 else 0.0,
            "justification_rate": round(justified_count / total_cases, 4) if total_cases > 0 else 0.0,
            "exculpation_rate": round(exculpated_count / total_cases, 4) if total_cases > 0 else 0.0,
            "constituent_failure_rate": round(constituent_fail_count / total_cases, 4) if total_cases > 0 else 0.0,
            "average_sentence_months": avg_sentence,
            "verdicts_summary": verdicts_summary,
            "verdict_list": verdict_list
        }
        print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
